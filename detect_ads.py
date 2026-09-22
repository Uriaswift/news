import re
import sqlite3

from paths import DB_FILE


AD_PATTERNS = [
    r"рекомендуем к просмотру",
    r"рекомендуем канал",
    r"подпишитесь на канал",
    r"подписывайтесь на канал",
    r"переходите по ссылке",
    r"становитесь частью нашего сообщества",
    r"только здесь",
    r"эксклюзивные материалы",
    r"на правах рекламы",
    r"реклам[аы]",
    r"промокод",
    r"скидк[аи]\s+\d+%",
    r"подписаться",
    r"подпишись",
    r"ждем вас",
    r"мы ждём вас",
    r"мы ждем вас",
]


def looks_like_ad(text):
    if not text:
        return False

    lowered = text.lower()

    score = 0

    for pattern in AD_PATTERNS:
        if re.search(
            pattern,
            lowered,
            flags=re.IGNORECASE
        ):
            score += 1

    # Если есть сразу несколько рекламных признаков,
    # считаем пост рекламой.
    if score >= 2:
        return True

    # Сильные одиночные признаки.
    strong_patterns = [
        r"на правах рекламы",
        r"переходите по ссылке и",
        r"рекомендуем к просмотру",
    ]

    for pattern in strong_patterns:
        if re.search(
            pattern,
            lowered,
            flags=re.IGNORECASE
        ):
            return True

    return False


def main():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            chat_title,
            cleaned_text
        FROM messages
        WHERE cleaned_text IS NOT NULL AND processed_at IS NULL
    """)

    rows = cursor.fetchall()

    detected = 0

    for message_id, channel, text in rows:
        is_ad = 1 if looks_like_ad(text) else 0

        cursor.execute("""
            UPDATE messages
            SET is_ad = ?, processed_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            is_ad,
            message_id
        ))

        if is_ad:
            detected += 1

    conn.commit()
    conn.close()

    print(
        "Проверено сообщений:",
        len(rows)
    )

    print(
        "Найдено рекламных:",
        detected
    )


if __name__ == "__main__":
    main()