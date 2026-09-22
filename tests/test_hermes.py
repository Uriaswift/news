import importlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# The suite must never touch real sessions, the live DB, or Telegram.
sandbox = tempfile.TemporaryDirectory()
os.environ['HERMES_DATA_DIR'] = sandbox.name
os.environ['TELEGRAM_BOT_TOKEN'] = 'test-token'
os.environ['HERMES_TELEGRAM_CHAT_ID'] = '-100123'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import database
from paths import DB_FILE, MEDIA_DIR
import send_pending_digests as sender
import hourly_digest as generator

class HermesTests(unittest.TestCase):
    def setUp(self):
        self.cbr = patch('rates.get_cbr_rates',return_value={'USD':90,'EUR':100}); self.cbr.start(); self.addCleanup(self.cbr.stop)
        self.crypto = patch('rates.get_crypto_rates',return_value={'BTC':65000}); self.crypto.start(); self.addCleanup(self.crypto.stop)
        database.initialize()
        with database.connection(DB_FILE) as c:
            for table in ('delivery_parts','digest_messages','sent_story_messages','digests','messages'):
                c.execute('DELETE FROM '+table)

    def digest(self):
        with database.connection(DB_FILE) as c:
            c.execute("INSERT INTO messages(id,telegram_message_id,chat_id,message_date,text) VALUES (1,1,1,'2026-09-22T10:00:00+00:00','Sample')")
            payload={'items':[{'section':'news','title':'Title <&>','summary':'Summary','message_ids':[1]}]}
            c.execute("INSERT INTO digests(id,period_start,period_end,generated_at,text,payload_json) VALUES (1,'2026-09-22T10:00:00+00:00','2026-09-22T11:00:00+00:00','now','text',?)",(json.dumps(payload),))
            c.execute('INSERT INTO digest_messages VALUES(1,1)')

    def test_header_rates_and_two_timezones(self):
        text=sender.build_header('2026-09-22T12:58:00+00:00','2026-09-22T13:02:00+00:00')
        self.assertIn('Москва: 22.09 15:58 — 22.09 16:02',text)
        self.assertIn('Екатеринбург: 22.09 17:58 — 22.09 18:02',text)
        self.assertIn('USD/RUB — 90.00',text)
        self.assertIn('EUR/RUB — 100.00',text)
        self.assertIn('BTC/USD — $65 000',text)

    def test_fresh_and_legacy_schema(self):
        database.initialize()
        with database.connection(DB_FILE) as c:
            self.assertEqual(c.execute('PRAGMA quick_check').fetchone()[0],'ok')
            self.assertIn('delivery_parts',{r[0] for r in c.execute("SELECT name FROM sqlite_master")})
            c.execute('ALTER TABLE digests DROP COLUMN payload_json')
        database.initialize()
        with database.connection(DB_FILE) as c:
            self.assertIn('payload_json',{r[1] for r in c.execute('PRAGMA table_info(digests)')})

    def test_delivery_checkpoint_retry(self):
        self.digest()
        err=sender.DeliveryError('rejected'); err.rejected=True
        with patch.object(sender,'api',side_effect=[101,err]) as api:
            with self.assertRaises(sender.DeliveryError): sender.main()
            self.assertEqual(api.call_count,2)
        with patch.object(sender,'api',return_value=102) as api:
            sender.main()
            self.assertEqual(api.call_count,1)
        with database.connection(DB_FILE) as c:
            self.assertIsNotNone(c.execute('SELECT sent_at FROM digests').fetchone()[0])
            self.assertIsNotNone(c.execute('SELECT sent_at FROM messages').fetchone()[0])

    def test_unknown_delivery_never_retries_automatically(self):
        self.digest()
        with patch.object(sender,'api',side_effect=sender.DeliveryError('unknown')):
            with self.assertRaises(sender.DeliveryError): sender.main()
        with patch.object(sender,'api') as api:
            with self.assertRaises(sender.DeliveryError): sender.main()
            api.assert_not_called()

    def test_html_splitting(self):
        import html
        text='😀<&>'*2200
        parts=list(sender.text_parts(text))
        self.assertEqual(''.join(html.unescape(p['text']) for p in parts),text)
        self.assertTrue(all(len(html.unescape(p['text']).encode('utf-16-le'))//2<=4096 for p in parts))

    def test_destination_frozen(self):
        self.digest()
        with patch.object(sender,'api',side_effect=sender.DeliveryError('unknown')):
            with self.assertRaises(sender.DeliveryError): sender.main()
        with database.connection(DB_FILE) as c:
            payload=json.loads(c.execute('SELECT payload FROM delivery_parts LIMIT 1').fetchone()[0])
            self.assertEqual(payload['chat_id'],'-100123')

    def test_invalid_model_response(self):
        with self.assertRaises(ValueError): generator.validate_payload([],set())
        self.assertEqual(generator.validate_payload({'items':[{'section':'news','title':'x','summary':'y','message_ids':None}]},{1}),[])
        self.assertEqual(generator.validate_payload({'items':[{'section':'news','title':'x','summary':'y','message_ids':[999]}]},{1}),[])

    def test_no_generation_over_pending(self):
        self.digest()
        with patch.object(generator.ollama,'Client') as client:
            with self.assertRaises(RuntimeError): generator.main()
            client.assert_not_called()

    def test_portable_media(self):
        from paths import resolve_media
        folder=MEDIA_DIR/'photos'; folder.mkdir(parents=True,exist_ok=True)
        (folder/'image.jpg').write_bytes(b'test')
        self.assertEqual(resolve_media(r'D:\hermes-data\media\photos\image.jpg'),folder/'image.jpg')
        self.assertEqual(resolve_media('photos/image.jpg'),folder/'image.jpg')
        self.assertIsNone(resolve_media('../../outside'))

    def test_photo_and_news_are_one_message(self):
        self.digest()
        folder=MEDIA_DIR/'photos'; folder.mkdir(parents=True,exist_ok=True)
        (folder/'article.jpg').write_bytes(b'test')
        with database.connection(DB_FILE) as c:
            c.execute("UPDATE messages SET media_type='photo',media_path='photos/article.jpg'")
            digest=c.execute('SELECT id,period_start,period_end,payload_json FROM digests').fetchone()
            parts=sender.make_parts(c,digest)
        self.assertEqual(len(parts),2)  # Header + one photo containing the full article.
        self.assertEqual(parts[1]['method'],'sendPhoto')
        self.assertIn('Summary',parts[1]['caption'])

    def test_long_news_is_one_text_without_duplicate_photo(self):
        self.digest()
        folder=MEDIA_DIR/'photos'; folder.mkdir(parents=True,exist_ok=True)
        (folder/'article.jpg').write_bytes(b'test')
        with database.connection(DB_FILE) as c:
            c.execute("UPDATE messages SET media_type='photo',media_path='photos/article.jpg'")
            digest=list(c.execute('SELECT id,period_start,period_end,payload_json FROM digests').fetchone())
            payload=json.loads(digest[3]);payload['items'][0]['summary']='x'*1100
            digest[3]=json.dumps(payload)
            parts=sender.make_parts(c,digest)
        self.assertEqual(len(parts),2)
        self.assertEqual(parts[1]['method'],'sendMessage')

    def test_lock_across_processes(self):
        from locking import lock
        with lock('pipeline'):
            result=subprocess.run([sys.executable,'-c',"from locking import lock\nwith lock('pipeline'): pass"],cwd=Path(__file__).resolve().parents[1],capture_output=True)
        self.assertNotEqual(result.returncode,0)

    def test_queue_drains_before_failed_generation(self):
        import hour_pipeline
        calls=[]
        def run(name):
            calls.append(name)
            if name=='clean_messages.py': raise RuntimeError('test')
        with patch.object(hour_pipeline,'run',side_effect=run):
            with self.assertRaises(RuntimeError): hour_pipeline.main()
        self.assertEqual(calls,['send_pending_digests.py','clean_messages.py'])

if __name__=='__main__': unittest.main()
