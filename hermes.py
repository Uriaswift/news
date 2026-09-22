"""Hermes service, setup and diagnostics. Python 3.11+."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import threading
from datetime import datetime, timezone
from paths import BASE_DIR, DB_FILE, LOGS_DIR, DATA_DIR, ensure_directories
from database import initialize, connection
from locking import lock

def configure_logging(name):
    ensure_directories()
    handlers = [RotatingFileHandler(LOGS_DIR / (name+'-service.log'), maxBytes=5_000_000, backupCount=3, encoding='utf-8')]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s', handlers=handlers, force=True)
    logging.getLogger('httpx').setLevel(logging.WARNING)

def worker(command):
    configure_logging(command)
    if command == 'collector':
        import collector
        collector.main()
    else:
        import hour_pipeline
        hour_pipeline.main()

def serve():
    with lock('service'):
        initialize()
        configure_logging('service')
        log = logging.getLogger('hermes')
        stop = False
        def stopping(*_):
            nonlocal stop
            stop = True
        signal.signal(signal.SIGTERM, stopping)
        signal.signal(signal.SIGINT, stopping)
        (DATA_DIR/'stop.request').unlink(missing_ok=True)
        children = {}
        due = {'collector':0, 'pipeline':0}
        try:
            while not stop and not (DATA_DIR/'stop.request').exists():
                for name in due:
                    child = children.get(name)
                    if child and child.poll() is not None:
                        code = child.returncode
                        log.info('%s exited with code %s',name,code)
                        delay = 30 if name == 'collector' or code else int(os.getenv('HERMES_INTERVAL_SECONDS','3600'))
                        due[name] = time.monotonic() + delay
                        del children[name]
                    if name not in children and time.monotonic() >= due[name]:
                        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
                        executable = str(Path(sys.executable).with_name('python.exe')) if os.name == 'nt' else sys.executable
                        children[name] = subprocess.Popen([executable,'-u',str(BASE_DIR/'hermes.py'),name],cwd=BASE_DIR,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                        def relay(process, label):
                            for line in process.stdout:
                                log.info('%s: %s',label,line.rstrip())
                            process.stdout.close()
                        threading.Thread(target=relay,args=(children[name],name),daemon=True).start()
                        log.info('%s started, PID %s',name,children[name].pid)
                time.sleep(1)
        finally:
            for child in children.values():
                if child.poll() is None:
                    child.terminate()
            for child in children.values():
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            (DATA_DIR/'stop.request').unlink(missing_ok=True)
            log.info('Service stopped')

def status(network=False):
    failures = []
    if not DB_FILE.exists():
        print('FAIL: database missing; run python hermes.py init')
        return 1
    with connection(f'{DB_FILE.as_uri()}?mode=ro',uri=True) as conn:
        integrity = conn.execute('PRAGMA quick_check').fetchone()[0]
        print('Database:',integrity)
        if integrity != 'ok': failures.append('Database integrity')
        total,latest = conn.execute('SELECT COUNT(*),MAX(message_date) FROM messages').fetchone()
        print('Collected messages:',total,'latest post:',latest)
        print('Pending digests:',conn.execute('SELECT COUNT(*) FROM digests WHERE sent_at IS NULL').fetchone()[0])
        print('Latest sent digest:',conn.execute('SELECT MAX(sent_at) FROM digests').fetchone()[0])
        heartbeat = conn.execute("SELECT value FROM app_state WHERE key='collector_heartbeat'").fetchone()
        if not heartbeat or (datetime.now(timezone.utc)-datetime.fromisoformat(heartbeat[0])).total_seconds()>120:
            failures.append('Collector heartbeat missing or older than 120 seconds')
        uncertain = conn.execute("SELECT digest_id,part_no FROM delivery_parts WHERE status='sending'").fetchall()
        if uncertain: failures.append('Uncertain delivery parts: '+str(uncertain))
    if network:
        import httpx
        from send_pending_digests import destination
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        try:
            response = httpx.post(f'https://api.telegram.org/bot{token}/getChat', data={'chat_id':destination()},timeout=15)
            data = response.json()
            if not data.get('ok'): failures.append('Telegram destination unavailable')
            else: print('Telegram destination:',data['result'].get('username'),data['result']['type'])
        except Exception as exc:
            failures.append('Telegram check: '+type(exc).__name__)
        try:
            response = httpx.get(os.getenv('OLLAMA_HOST','http://localhost:11434').rstrip('/')+'/api/tags',timeout=15)
            response.raise_for_status()
            names = [m['name'] for m in response.json().get('models',[])]
            model = os.getenv('OLLAMA_MODEL','glm-5.3-flash:cloud')
            print('Ollama models:',names)
            if model not in names: failures.append('Configured Ollama model is not installed')
        except Exception as exc:
            failures.append('Ollama check: '+type(exc).__name__)
    for failure in failures: print('FAIL:',failure)
    return int(bool(failures))

def main():
    os.environ['PYTHONUTF8']='1'
    os.environ['PYTHONIOENCODING']='utf-8'
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser(description='Hermes Telegram news service')
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('init','login','run','collector','pipeline','send','stop'):
        sub.add_parser(name)
    p=sub.add_parser('status'); p.add_argument('--network',action='store_true')
    p=sub.add_parser('resolve-delivery')
    p.add_argument('digest',type=int); p.add_argument('part',type=int)
    p.add_argument('--result',choices=['sent','retry'],required=True,help='After checking the channel: sent, or retry if absent')
    args=parser.parse_args()
    if args.command=='init': initialize()
    elif args.command=='login':
        import collector
        collector.main(login=True)
    elif args.command=='run': serve()
    elif args.command in ('collector','pipeline'): worker(args.command)
    elif args.command=='send':
        from send_pending_digests import main as send
        send()
    elif args.command=='status': return status(args.network)
    elif args.command=='stop':
        ensure_directories(); (DATA_DIR/'stop.request').touch()
    elif args.command=='resolve-delivery':
        with lock('sender'), connection(DB_FILE,timeout=30) as conn:
            result=conn.execute("UPDATE delivery_parts SET status=? WHERE digest_id=? AND part_no=? AND status='sending'",('sent' if args.result=='sent' else 'pending',args.digest,args.part))
            if result.rowcount!=1: raise RuntimeError('No uncertain part with these IDs')
    return 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        # Third-party exceptions may contain credentials in URLs. Log safe errors only.
        message = str(exc) if isinstance(exc,RuntimeError) else type(exc).__name__
        if isinstance(exc,OSError): message += ': ' + str(exc.filename)
        print('ERROR:',message,file=sys.stderr,flush=True)
        raise SystemExit(1)
