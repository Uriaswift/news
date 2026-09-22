import re
import sqlite3


from paths import DB_FILE


def clean_text(text: str) -> str:
    if not text:
        return ""

    # Удаляем невидимые Unicode-символы.
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        text = text.replace(ch, "")

    # Удаляем URL.
    text = re.sub(
        r"https?://\S+",
        " ",
        text,
        flags=re.IGNORECASE
    )

    # Удаляем t.me ссылки без http.
    text = re.sub(
        r"(?:www\.)?t\.me/\S+",
        " ",
        text,
        flags=re.IGNORECASE
    )

    # Удаляем Telegram usernames вида @channelname.
    text = re.sub(
        r"(?<!\w)@[A-Za-z0-9_]{4,}",
        " ",
        text
    )

    lines = text.splitlines()
    cleaned_lines = []

    # Если строка целиком похожа на служебный хвост,
    # выкидываем её.
    line_patterns = [
        r"^\s*подписаться.*$",
        r"^\s*подписывайтесь.*$",
        r"^\s*подписывайся.*$",
        r"^\s*наш канал.*$",
        r"^\s*наш telegram.*$",
        r"^\s*наш телеграм.*$",
        r"^\s*читать далее.*$",
        r"^\s*читать полностью.*$",
        r"^\s*источник\s*:?.*$",
        r"^\s*прислать новость.*$",
        r"^\s*предложить новость.*$",
        r"^\s*мы в max.*$",
        r"^\s*мы в telegram.*$",
    ]

    for line in lines:
        line = line.strip()

        if not line:
            continue

        skip = False

        for pattern in line_patterns:
            if re.match(pattern, line, flags=re.IGNORECASE):
                skip = True
                break

        if skip:
            continue

        # Убираем часто встречающиеся хвосты внутри строки.
        line = re.sub(
            r"\bподписаться\b.*$",
            "",
            line,
            flags=re.IGNORECASE
        )

        line = re.sub(
            r"\bподписывайтесь\b.*$",
            "",
            line,
            flags=re.IGNORECASE
        )

        line = re.sub(
            r"\bв\s+max\b.*$",
            "",
            line,
            flags=re.IGNORECASE
        )

        line = re.sub(
            r"\bв\s+telegram\b.*$",
            "",
            line,
            flags=re.IGNORECASE
        )

        line = line.strip(" |•—-👉✔📌")

        if line:
            cleaned_lines.append(line)

    text = " ".join(cleaned_lines)

    # Нормализуем пробелы.
    text = re.sub(r"\s+", " ", text)

    # Пробелы перед знаками препинания.
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)

    return text.strip()


def column_exists(cursor, table_name, column_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    return any(column[1] == column_name for column in columns)


def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    if not column_exists(
        cursor,
        "messages",
        "cleaned_text"
    ):
        cursor.execute("""
            ALTER TABLE messages
            ADD COLUMN cleaned_text TEXT
        """)

        conn.commit()

    cursor.execute("""
        SELECT
            id,
            text
        FROM messages
        WHERE processed_at IS NULL
    """)

    rows = cursor.fetchall()

    print("Сообщений для обработки:", len(rows))

    processed = 0
    empty_after_cleaning = 0

    for message_id, original_text in rows:
        cleaned = clean_text(original_text)

        if not cleaned:
            empty_after_cleaning += 1

        cursor.execute("""
            UPDATE messages
            SET cleaned_text = ?
            WHERE id = ?
        """, (
            cleaned,
            message_id
        ))

        processed += 1

    conn.commit()
    conn.close()

    print()
    print("Готово.")
    print("Обработано сообщений:", processed)
    print("Пустых после очистки:", empty_after_cleaning)


if __name__ == "__main__":
    main()