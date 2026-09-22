"""Durable per-message delivery with explicit handling of uncertain API results."""
import html
import json
import os
import sqlite3
from datetime import datetime, timezone
import httpx
from paths import DB_FILE, resolve_media
from locking import lock
from database import initialize, connection

SECTIONS = {'politics':'🏛 Политика', 'finance':'💰 Финансы', 'news':'🌍 Новости', 'tech':'💻 Технологии', 'deals':'🔥 Скидки'}

class DeliveryError(RuntimeError):
    pass

def destination():
    return os.getenv('HERMES_TELEGRAM_CHAT_ID') or os.getenv('TELEGRAM_CHANNEL_ID') or os.getenv('TELEGRAM_BOT_CHAT_ID')

def api(method, data, path=None):
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token or not destination():
        raise DeliveryError('Configure TELEGRAM_BOT_TOKEN and HERMES_TELEGRAM_CHAT_ID')
    url = f'https://api.telegram.org/bot{token}/{method}'
    # Do not print exception URLs: they contain the bot token.
    try:
        if path:
            field = 'photo' if method == 'sendPhoto' else 'video'
            with open(path, 'rb') as f:
                response = httpx.post(url, data=data, files={field:(path.name,f)}, timeout=120)
        else:
            response = httpx.post(url, data=data, timeout=60)
    except httpx.RequestError:
        raise DeliveryError('Telegram response unknown; check delivery before retrying this part') from None
    try:
        result = response.json()
    except ValueError:
        raise DeliveryError('Telegram returned an unreadable response; delivery is uncertain') from None
    if not result.get('ok'):
        code = result.get('error_code', response.status_code)
        error = DeliveryError(f'Telegram rejected request ({code}): {result.get("description", "unknown error")}')
        error.rejected = 400 <= code < 500
        raise error
    return result['result']['message_id']

def text_parts(text, limit=4096):
    # Telegram counts UTF-16 code units after parsing entities.
    chunk, units = [], 0
    for character in text:
        width = 2 if ord(character) > 0xFFFF else 1
        if units + width > limit:
            yield {'method':'sendMessage', 'text':html.escape(''.join(chunk))}
            chunk, units = [], 0
        chunk.append(character)
        units += width
    if chunk:
        yield {'method':'sendMessage', 'text':html.escape(''.join(chunk))}


def build_header(start, end):
    from zoneinfo import ZoneInfo
    from rates import get_cbr_rates, get_crypto_rates
    cbr, crypto = get_cbr_rates(), get_crypto_rates()
    lines = ['🗞 HERMES NEWS', '']
    for name, zone in [('Москва', 'Europe/Moscow'), ('Екатеринбург', 'Asia/Yekaterinburg')]:
        tz = ZoneInfo(zone)
        a, b = (datetime.fromisoformat(value).astimezone(tz) for value in (start, end))
        lines.append(f'🕐 {name}: {a:%d.%m %H:%M} — {b:%d.%m %H:%M}')
    lines.extend(['', '💰 КУРСЫ'])
    for code, flag in [('USD','🇺🇸'),('EUR','🇪🇺')]:
        value = cbr.get(code)
        rate = f'{value:.2f} ₽' if value is not None else 'временно недоступен'
        lines.append(f'{flag} {code}/RUB — {rate}')
    btc = crypto.get('BTC')
    rate = ('$' + f'{btc:,.0f}'.replace(',', ' ')) if btc is not None else 'временно недоступен'
    lines.append('₿ BTC/USD — ' + rate)
    lines.append('USD/EUR: официальный курс ЦБ; BTC: CoinGecko на момент подготовки.')
    return '\n'.join(lines)

def make_parts(conn, digest):
    did, start, end, raw = digest
    payload = json.loads(raw)
    items = payload['items']
    target = destination()
    if not target:
        raise DeliveryError('No Telegram destination configured')
    parts = list(text_parts(build_header(start, end)))
    for item in sorted(items, key=lambda x:list(SECTIONS).index(x['section'])):
        ids = item['message_ids']
        sources = conn.execute('SELECT chat_title,post_url,media_path,media_type FROM messages WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall()
        source_lines = list(dict.fromkeys(f'{r[0]}: {r[1]}' for r in sources if r[1]))
        body = f"{SECTIONS[item['section']]}\n\n{item['title']}\n\n{item['summary']}"
        if source_lines:
            body += '\n\n' + '\n'.join(source_lines)
        media = next(((resolve_media(r[2]),r[3]) for r in sources if r[3] in ('photo','video') and resolve_media(r[2])),None)
        if media and len(body.encode('utf-16-le')) // 2 <= 1024:
            path, kind = media
            parts.append({'method':'sendPhoto' if kind=='photo' else 'sendVideo', 'path':str(path), 'caption':html.escape(body)})
        else:
            parts.extend(text_parts(body))
    for part in parts:
        part['chat_id'] = target  # Destination cannot change midway through a digest.
    return parts

def send_all():
    initialize()
    with connection(DB_FILE, timeout=30) as conn:
        digests = conn.execute('SELECT id,period_start,period_end,payload_json FROM digests WHERE sent_at IS NULL ORDER BY id').fetchall()
        for digest in digests:
            did = digest[0]
            if not conn.execute('SELECT 1 FROM delivery_parts WHERE digest_id=?',(did,)).fetchone():
                for i, part in enumerate(make_parts(conn,digest)):
                    conn.execute('INSERT INTO delivery_parts(digest_id,part_no,payload) VALUES (?,?,?)',(did,i,json.dumps(part,ensure_ascii=False)))
                conn.commit()
            rows = conn.execute('SELECT part_no,payload,status FROM delivery_parts WHERE digest_id=? ORDER BY part_no',(did,)).fetchall()
            for number, raw, status in rows:
                if status == 'sent':
                    continue
                if status == 'sending':
                    raise DeliveryError(f'Digest {did}, part {number}: previous delivery uncertain. Check Telegram, then use hermes.py resolve-delivery.')
                part = json.loads(raw)
                method = part.pop('method')
                from pathlib import Path
                path = Path(part.pop('path')) if 'path' in part else None
                if path and not path.exists():
                    path = resolve_media(str(path))
                    if path is None:
                        # Preserve the title as text if an old attachment was removed.
                        method = 'sendMessage'
                        part['text'] = part.pop('caption')
                part['parse_mode'] = 'HTML'
                if method == 'sendMessage':
                    part['disable_web_page_preview'] = 'true'
                conn.execute("UPDATE delivery_parts SET status='sending' WHERE digest_id=? AND part_no=?",(did,number))
                conn.commit()
                try:
                    mid = api(method,part,path)
                except DeliveryError as exc:
                    if getattr(exc,'rejected',False):
                        conn.execute("UPDATE delivery_parts SET status='pending' WHERE digest_id=? AND part_no=?",(did,number))
                        conn.commit()
                    raise
                conn.execute("UPDATE delivery_parts SET status='sent',telegram_message_id=? WHERE digest_id=? AND part_no=?",(mid,did,number))
                conn.commit()
            now = datetime.now(timezone.utc).isoformat()
            conn.execute('UPDATE digests SET sent_at=? WHERE id=?',(now,did))
            conn.execute('UPDATE messages SET sent_at=? WHERE id IN (SELECT message_id FROM digest_messages WHERE digest_id=?)',(now,did))
            conn.execute('INSERT OR IGNORE INTO sent_story_messages SELECT message_id,?,? FROM digest_messages WHERE digest_id=?',(did,now,did))
            conn.execute("UPDATE app_state SET value=MAX(value,?) WHERE key='last_successful_digest_at'",(digest[2],))
            conn.commit()
            print(f'Digest {did}: delivered, {len(rows)} parts',flush=True)
        if not digests:
            print('No pending digests',flush=True)

def main():
    with lock('sender'):
        send_all()

if __name__ == '__main__':
    main()
