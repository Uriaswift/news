import json
import sqlite3
from pathlib import Path

from paths import DB_FILE


CATEGORIES_FILE = (
    Path(__file__).parent
    / "channel_categories.json"
)


def main():
    if not CATEGORIES_FILE.exists():
        raise FileNotFoundError(
            f"Не найден файл: {CATEGORIES_FILE}"
        )

    with open(
        CATEGORIES_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        categories = json.load(file)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT
            chat_title
        FROM messages
        WHERE chat_title IS NOT NULL
          AND TRIM(chat_title) != ''
        ORDER BY chat_title
    """)

    channels = [
        row[0]
        for row in cursor.fetchall()
    ]

    for channel in channels:
        category = categories.get(
            channel,
            "other"
        )

        cursor.execute("""
            UPDATE messages
            SET category = ?
            WHERE chat_title = ?
        """, (
            category,
            channel
        ))

    conn.commit()

    print()
    print("Категории применены.")
    print()

    cursor.execute("""
        SELECT
            COALESCE(category, 'NULL'),
            COUNT(*)
        FROM messages
        GROUP BY category
        ORDER BY category
    """)

    for category, count in cursor.fetchall():
        print(
            f"{category}: {count} сообщений"
        )

    conn.close()


if __name__ == "__main__":
    main()