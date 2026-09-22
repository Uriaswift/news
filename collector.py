"""Collect subscribed broadcast channels and recover posts missed during downtime."""
import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events
from telethon.tl.types import Channel
from paths import DB_FILE, MEDIA_DIR, SESSION_FILE, BASE_DIR
from database import initialize, connection
from locking import lock

log = logging.getLogger('hermes.collector')

def make_client():
    try:
        api_id = int(os.environ['TELEGRAM_API_ID'])
        api_hash = os.environ['TELEGRAM_API_HASH']
    except (KeyError, ValueError):
        raise RuntimeError('Configure TELEGRAM_API_ID and TELEGRAM_API_HASH in .env') from None
    return TelegramClient(str(SESSION_FILE), api_id, api_hash, auto_reconnect=True)

async def collect(login=False):
    initialize()
    # SQLite backup also accounts for a journal; no bare copy of an active session.
    legacy = BASE_DIR / 'news_collector.session'
    target = SESSION_FILE.with_suffix('.session')
    if not target.exists() and legacy.exists():
        with connection(legacy) as source, connection(target) as dest:
            source.backup(dest)
    client = make_client()
    if login:
        await client.start(phone=os.getenv('TELEGRAM_PHONE'))
        await client.disconnect()
        return
    await client.connect()
    if not await client.is_user_authorized():
        await client.disconnect()
        raise RuntimeError('Telegram login required: python hermes.py login')

    mutex = asyncio.Lock()
    destination = os.getenv('TELEGRAM_CHANNEL_ID', '')

    async def save(message, chat):
        if not isinstance(chat, Channel) or chat.megagroup:
            return
        chat_id = int('-100' + str(chat.id))
        if str(chat_id) == destination or ('@' + (chat.username or '')) == destination:
            return  # Never feed our own digests back into the collector.
        async with mutex:
            with connection(DB_FILE, timeout=30) as conn:
                if conn.execute('SELECT 1 FROM messages WHERE chat_id=? AND telegram_message_id=?', (chat_id, message.id)).fetchone():
                    return
            text = message.message or ''
            media_type = 'photo' if message.photo else ('video' if message.video else None)
            if not text.strip() and not media_type:
                return
            media_path = None
            if media_type and os.getenv('HERMES_DOWNLOAD_MEDIA', '1') == '1':
                size = getattr(message.file, 'size', 0) or 0
                if size <= int(os.getenv('HERMES_MAX_MEDIA_MB','30')) * 1024 * 1024:
                    folder = MEDIA_DIR / (media_type + 's')
                    folder.mkdir(parents=True, exist_ok=True)
                    try:
                        path = await asyncio.wait_for(message.download_media(file=str(folder / f'{chat_id}_{message.id}')), timeout=60)
                        if path:
                            from pathlib import Path
                            media_path = Path(path).relative_to(MEDIA_DIR).as_posix()
                    except Exception as exc:
                        log.warning('Media download failed: %s', type(exc).__name__)
            with connection(DB_FILE, timeout=30) as conn:
                conn.execute('''INSERT OR IGNORE INTO messages
                    (telegram_message_id,chat_id,chat_title,chat_username,message_date,text,post_url,has_media,media_type,grouped_id,media_path)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                    (message.id,chat_id,chat.title,chat.username,message.date.isoformat(),text,
                     f'https://t.me/{chat.username}/{message.id}' if chat.username else None,
                     int(bool(media_type)),media_type,message.grouped_id,media_path))

    async def handler(event):
        try:
            await save(event.message, await event.get_chat())
        except Exception:
            log.exception('Incoming post failed; periodic recovery will retry')

    client.add_event_handler(handler, events.NewMessage)
    log.info('Telegram authorized; collector connected')

    async def recover():
        while True:
            with connection(DB_FILE, timeout=30) as conn:
                last = conn.execute("SELECT value FROM app_state WHERE key='collector_recovered_at'").fetchone()
                if not last:
                    last = conn.execute('SELECT MAX(message_date) FROM messages').fetchone()
            now = datetime.now(timezone.utc)
            cutoff = datetime.fromisoformat(last[0]) - timedelta(minutes=5) if last and last[0] else now-timedelta(hours=1)
            async for dialog in client.iter_dialogs():
                chat = dialog.entity
                if not isinstance(chat, Channel) or chat.megagroup:
                    continue
                # Newest first; stop at the persisted recovery checkpoint.
                async for message in client.iter_messages(chat):
                    if message.date < cutoff:
                        break
                    await save(message, chat)
            with connection(DB_FILE, timeout=30) as conn:
                conn.execute("INSERT INTO app_state VALUES ('collector_recovered_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(now.isoformat(),))
            log.info('Recovery complete')
            await asyncio.sleep(300)

    async def heartbeat():
        while True:
            await client.get_me()  # Confirm the authenticated connection is responsive.
            with connection(DB_FILE, timeout=30) as conn:
                conn.execute("INSERT INTO app_state VALUES ('collector_heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (datetime.now(timezone.utc).isoformat(),))
            await asyncio.sleep(30)

    tasks = [asyncio.create_task(recover()), asyncio.create_task(heartbeat()), asyncio.ensure_future(client.disconnected)]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        raise RuntimeError('Collector connection ended')
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await client.disconnect()

def main(login=False):
    with lock('collector'):
        asyncio.run(collect(login))

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    main()
