from contextlib import contextmanager
import sqlite3
from paths import DB_FILE, ensure_directories

def ensure_column(
    cursor,
    column,
    definition
):
    cursor.execute(
        "PRAGMA table_info(messages)"
    )

    columns = {
        row[1]
        for row in cursor.fetchall()
    }

    if column not in columns:
        cursor.execute(
            f"""
            ALTER TABLE messages
            ADD COLUMN {column} {definition}
            """
        )


def init_db():
    ensure_directories()

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            telegram_message_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,

            chat_title TEXT,
            chat_username TEXT,

            message_date TEXT NOT NULL,

            text TEXT,
            post_url TEXT,

            created_at TEXT
                DEFAULT CURRENT_TIMESTAMP,

            cleaned_text TEXT,

            processed_at TEXT,
            sent_at TEXT,

            is_ad INTEGER DEFAULT 0,
            category TEXT DEFAULT 'other',

            has_media INTEGER DEFAULT 0,
            media_type TEXT,
            grouped_id INTEGER,
            media_path TEXT,

            UNIQUE (
                chat_id,
                telegram_message_id
            )
        )
    """)

    ensure_column(
        cursor,
        "has_media",
        "INTEGER DEFAULT 0"
    )

    ensure_column(
        cursor,
        "media_type",
        "TEXT"
    )

    ensure_column(
        cursor,
        "grouped_id",
        "INTEGER"
    )

    ensure_column(
        cursor,
        "media_path",
        "TEXT"
    )

    conn.commit()
    conn.close()



def initialize():
    init_db()
    with connection(DB_FILE, timeout=30) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        for name, kind in {'cleaned_text':'TEXT','processed_at':'TEXT','sent_at':'TEXT','is_ad':'INTEGER DEFAULT 0', 'category':"TEXT DEFAULT 'other'"}.items():
            ensure_column(conn.cursor(), name, kind)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event_messages (event_id INTEGER NOT NULL, message_id INTEGER NOT NULL, UNIQUE(event_id,message_id));
            CREATE TABLE IF NOT EXISTS digests (id INTEGER PRIMARY KEY AUTOINCREMENT, period_start TEXT NOT NULL, period_end TEXT NOT NULL, generated_at TEXT NOT NULL, text TEXT NOT NULL, sent_at TEXT, model TEXT, input_chars INTEGER, payload_json TEXT);
            CREATE TABLE IF NOT EXISTS digest_messages (digest_id INTEGER NOT NULL, message_id INTEGER NOT NULL, UNIQUE(digest_id,message_id));
            CREATE TABLE IF NOT EXISTS sent_story_messages (message_id INTEGER PRIMARY KEY, first_digest_id INTEGER NOT NULL, sent_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS delivery_parts (digest_id INTEGER NOT NULL, part_no INTEGER NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', telegram_message_id INTEGER, PRIMARY KEY(digest_id,part_no));
            CREATE INDEX IF NOT EXISTS messages_delivery_idx ON messages(sent_at,message_date);
            CREATE INDEX IF NOT EXISTS event_messages_message_idx ON event_messages(message_id);
        """)
        columns = {r[1] for r in conn.execute('PRAGMA table_info(digests)')}
        if 'payload_json' not in columns:
            conn.execute('ALTER TABLE digests ADD COLUMN payload_json TEXT')
        from datetime import datetime, timedelta, timezone
        start = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        conn.execute("INSERT OR IGNORE INTO app_state VALUES ('last_successful_digest_at', ?)", (start,))

@contextmanager
def connection(*args, **kwargs):
    conn = sqlite3.connect(*args, **kwargs)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
