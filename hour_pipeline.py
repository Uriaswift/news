"""Drain the durable outbox before generating another digest."""
import os
import subprocess
import sys
from paths import BASE_DIR
from locking import lock
from database import initialize

def run(script):
    print('Running ' + script, flush=True)
    result = subprocess.run([sys.executable, '-u', str(BASE_DIR / script)],
                            cwd=BASE_DIR, timeout=int(os.getenv('HERMES_STEP_TIMEOUT', '900')))
    if result.returncode:
        raise RuntimeError(f'{script} failed ({result.returncode})')

def main():
    with lock('pipeline'):
        initialize()
        run('send_pending_digests.py')
        for script in ('clean_messages.py', 'detect_ads.py', 'apply_categories.py'):
            run(script)
        if os.getenv('HERMES_EMBEDDINGS', '0') == '1':
            run('update_embeddings.py')
            run('build_clusters.py')
        run('hourly_digest.py')
        run('send_pending_digests.py')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
