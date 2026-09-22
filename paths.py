"""Filesystem locations, independent of the current working directory."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')
DATA_DIR = Path(os.getenv('HERMES_DATA_DIR', 'data')).expanduser()
if not DATA_DIR.is_absolute():
    DATA_DIR = BASE_DIR / DATA_DIR
DATA_DIR = DATA_DIR.resolve()
DB_DIR = DATA_DIR / 'db'
DB_FILE = DB_DIR / 'news.db'
EMBEDDINGS_DIR = DATA_DIR / 'embeddings'
EMBEDDINGS_FILE = EMBEDDINGS_DIR / 'embeddings.npy'
METADATA_FILE = EMBEDDINGS_DIR / 'embeddings_meta.json'
MEDIA_DIR = DATA_DIR / 'media'
BACKUPS_DIR = DATA_DIR / 'backups'
LOGS_DIR = DATA_DIR / 'logs'
ARCHIVE_DIR = DATA_DIR / 'archive'
SESSION_FILE = DATA_DIR / 'sessions' / 'news_collector'

def ensure_directories():
    for directory in (DB_DIR, EMBEDDINGS_DIR, MEDIA_DIR, BACKUPS_DIR,
                      LOGS_DIR, ARCHIVE_DIR, SESSION_FILE.parent):
        directory.mkdir(parents=True, exist_ok=True)

def resolve_media(value):
    if not value:
        return None
    portable = value.replace('\\', '/')
    if '/media/' in portable:
        portable = portable.split('/media/', 1)[1]
    elif portable.startswith('media/'):
        portable = portable[6:]
    candidate = (MEDIA_DIR / portable).resolve()
    if candidate.is_relative_to(MEDIA_DIR.resolve()) and candidate.is_file():
        return candidate
    return None
