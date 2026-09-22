import json
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta

import ollama

from paths import DB_FILE
from database import connection


# ============================================================
# UTF-8
# ============================================================

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(
        encoding="utf-8",
        errors="replace"
    )

if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(
        encoding="utf-8",
        errors="replace"
    )


# ============================================================
# CONFIG
# ============================================================

MODEL = os.getenv("OLLAMA_MODEL", "glm-5.3-flash:cloud")

STATE_KEY = "last_successful_digest_at"

MAX_TEXT_PER_MESSAGE = 700

MAX_MESSAGES_PER_EVENT = 6

ALLOWED_SECTIONS = {
    "politics",
    "finance",
    "news",
    "tech",
    "deals",
}


# ============================================================
# TIME / STATE
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    )


def get_start_time(cursor):
    cursor.execute("""
        SELECT value
        FROM app_state
        WHERE key = ?
    """, (
        STATE_KEY,
    ))

    row = cursor.fetchone()

    if not row:
        raise RuntimeError(
            "Нет last_successful_digest_at"
        )

    return row[0]


def update_state(
    cursor,
    value
):
    cursor.execute("""
        INSERT INTO app_state (
            key,
            value
        )
        VALUES (?, ?)

        ON CONFLICT(key)
        DO UPDATE SET
            value = excluded.value
    """, (
        STATE_KEY,
        value
    ))


# ============================================================
# EVENTS
# ============================================================

def load_events(
    cursor,
    start_time,
    end_time
):
    """
    Ищем EVENT, в которых появились НОВЫЕ,
    ещё не отправленные сообщения за текущий период.

    Важно:
    старые уже отправленные сообщения внутри EVENT
    больше НЕ блокируют весь EVENT.
    """

    cursor.execute("""
        SELECT DISTINCT
            em.event_id

        FROM event_messages em

        JOIN messages m
          ON m.id = em.message_id

        WHERE m.message_date > ?
          AND m.message_date <= ?

          AND COALESCE(
              m.is_ad,
              0
          ) = 0

          AND m.sent_at IS NULL
    """, (
        start_time,
        end_time
    ))

    event_ids = [
        row[0]
        for row in cursor.fetchall()
    ]

    events = []

    for event_id in event_ids:

        cursor.execute("""
            SELECT
                m.id,
                m.chat_title,
                m.message_date,
                m.cleaned_text,
                m.post_url,
                COALESCE(
                    m.category,
                    'other'
                )

            FROM event_messages em

            JOIN messages m
              ON m.id = em.message_id

            WHERE em.event_id = ?

              AND m.message_date > ?
              AND m.message_date <= ?

              AND COALESCE(
                  m.is_ad,
                  0
              ) = 0

              AND m.sent_at IS NULL

              AND m.cleaned_text
                  IS NOT NULL

              AND TRIM(
                  m.cleaned_text
              ) != ''

            ORDER BY
                m.message_date DESC

            LIMIT ?
        """, (
            event_id,
            start_time,
            end_time,
            MAX_MESSAGES_PER_EVENT
        ))

        rows = cursor.fetchall()

        # Даже если после удаления старых сообщений
        # остался только один новый источник,
        # новость всё равно не теряем.
        if rows:
            events.append(
                rows
            )

    return events


# ============================================================
# SINGLE POSTS
# ============================================================

def load_singles(
    cursor,
    start_time,
    end_time
):
    """
    Сообщения, которые вообще не попали
    ни в один EVENT.
    """

    cursor.execute("""
        SELECT
            m.id,
            m.chat_title,
            m.message_date,
            m.cleaned_text,
            m.post_url,
            COALESCE(
                m.category,
                'other'
            )

        FROM messages m

        LEFT JOIN event_messages em
          ON em.message_id = m.id

        WHERE em.message_id IS NULL

          AND COALESCE(
              m.is_ad,
              0
          ) = 0

          AND m.sent_at IS NULL

          AND m.message_date > ?
          AND m.message_date <= ?

          AND m.cleaned_text
              IS NOT NULL

          AND LENGTH(
              TRIM(m.cleaned_text)
          ) >= 80

        ORDER BY
            m.message_date DESC
    """, (
        start_time,
        end_time
    ))

    return cursor.fetchall()


# ============================================================
# PROMPT
# ============================================================

def build_prompt(
    events,
    singles
):
    parts = ["""
Ты редактор персонального новостного Telegram-канала.

Составь дайджест только из предоставленных ниже материалов.

Верни ТОЛЬКО валидный JSON.
Никакого Markdown вокруг JSON.

Структура:

{
  "items": [
    {
      "section": "news",
      "title": "Короткий заголовок",
      "summary": "Краткое содержание.",
      "message_ids": [123, 124]
    }
  ]
}


Допустимые section:

politics
finance
news
tech
deals


КАТЕГОРИИ:

politics
— внутренняя и международная политика;
— выборы;
— законодательство;
— дипломатия;
— решения государственных органов.

finance
— валюты;
— банки;
— ставки;
— инфляция;
— бюджет;
— налоги;
— рынки;
— нефть;
— криптовалюты;
— экономика;
— крупные компании.

news
— общество;
— происшествия;
— международные события;
— культура;
— наука;
— обычные новости.

tech
— IT;
— AI;
— технологии;
— гаджеты;
— программирование;
— игры;
— интернет;
— цифровые сервисы.

deals
— скидки;
— распродажи;
— товары;
— акции;
— промокоды.


ПРАВИЛА:

1. Используй только переданные материалы.

2. Не придумывай факты.

3. Объединяй сообщения,
   которые описывают одно событие.

4. Одна реальная новость должна
   появиться только ОДИН раз.

5. Если несколько источников говорят
   об одном событии,
   создай один item и перечисли
   все использованные message_ids.

6. Не делай несколько item
   с одной и той же новостью
   в разных формулировках.

7. Не включай рекламу Telegram-каналов,
   саморекламу,
   просьбы подписаться
   и бессодержательные сообщения.

8. Summary обычно 1–3 предложения.

9. message_ids обязательны.

10. В message_ids разрешено использовать
    ТОЛЬКО ID, реально переданные ниже.

11. Категорию определяй по содержанию
    новости, а не только по названию канала.

12. Не добавляй курсы USD/EUR/BTC/ETH.
    Их добавляет программа отдельно.

13. Для deals не придумывай ссылку.
    Ссылка будет восстановлена программой
    по message_id.

14. Если нормальных материалов нет:

{
  "items": []
}
"""]

    # --------------------------------------------------------
    # EVENTS
    # --------------------------------------------------------

    for event_number, event in enumerate(
        events,
        start=1
    ):
        parts.append(
            "\n\n"
            + "=" * 80
            + f"\nEVENT {event_number}\n"
        )

        for row in event:

            (
                message_id,
                channel,
                date,
                text,
                url,
                channel_category
            ) = row

            parts.append(f"""

ID: {message_id}
Канал: {channel}
Дата: {date}
Тип канала: {channel_category}
Ссылка: {url or "-"}

{text[:MAX_TEXT_PER_MESSAGE]}
""")

    # --------------------------------------------------------
    # SINGLES
    # --------------------------------------------------------

    if singles:
        parts.append(
            "\n\n"
            + "=" * 80
            + "\nSINGLE POSTS\n"
        )

    for row in singles:

        (
            message_id,
            channel,
            date,
            text,
            url,
            channel_category
        ) = row

        parts.append(f"""

ID: {message_id}
Канал: {channel}
Дата: {date}
Тип канала: {channel_category}
Ссылка: {url or "-"}

{text[:MAX_TEXT_PER_MESSAGE]}
""")

    return "".join(parts)


# ============================================================
# RESPONSE VALIDATION
# ============================================================

def validate_payload(
    payload,
    allowed_ids
):
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    items = payload.get(
        "items",
        []
    )

    if not isinstance(
        items,
        list
    ):
        return []

    result = []

    used_message_ids = set()

    for item in items:

        if not isinstance(
            item,
            dict
        ):
            continue

        section = item.get(
            "section"
        )

        title = str(
            item.get(
                "title",
                ""
            )
        ).strip()

        summary = str(
            item.get(
                "summary",
                ""
            )
        ).strip()

        raw_ids = item.get(
            "message_ids",
            []
        )

        if (
            section
            not in ALLOWED_SECTIONS
        ):
            continue

        if not title:
            continue

        if not summary:
            continue

        if not isinstance(raw_ids, list):
            continue

        valid_ids = []

        for value in raw_ids:

            try:
                value = int(value)

            except Exception:
                continue

            if value not in allowed_ids:
                continue

            if value in valid_ids:
                continue

            valid_ids.append(
                value
            )

        if not valid_ids:
            continue

        # Если модель уже использовала
        # абсолютно все эти сообщения
        # в предыдущем item,
        # второй item считаем дублем.
        if all(
            value in used_message_ids
            for value in valid_ids
        ):
            print(
                "[DEDUP] Модель создала "
                "повторный item, пропускаю:",
                title
            )

            continue

        used_message_ids.update(
            valid_ids
        )

        result.append({
            "section": section,
            "title": title,
            "summary": summary,
            "message_ids": valid_ids,
        })

    return result


# ============================================================
# FALLBACK TEXT
# ============================================================

def fallback_text(items):
    lines = []

    for item in items:

        lines.append(
            item["title"]
        )

        lines.append(
            item["summary"]
        )

        lines.append("")

    return "\n".join(
        lines
    ).strip()


# ============================================================
# MAIN
# ============================================================

def generate(conn):

    cursor = conn.cursor()

    start_time = (
        get_start_time(
            cursor
        )
    )

    end_time = min(now_utc(), datetime.fromisoformat(start_time) + timedelta(hours=1)).isoformat()
    if cursor.execute('SELECT 1 FROM digests WHERE sent_at IS NULL LIMIT 1').fetchone():
        raise RuntimeError('Send the pending digest before generating another one')
    recovered = cursor.execute("SELECT value FROM app_state WHERE key='collector_recovered_at'").fetchone()
    if not recovered:
        raise RuntimeError('Waiting for initial collector recovery; the digest checkpoint is unchanged')
    end_time = min(end_time, recovered[0])
    if end_time <= start_time:
        raise RuntimeError('Waiting for collector recovery to advance')

    print()
    print("=" * 80)
    print("ПОЧАСОВОЙ ДАЙДЖЕСТ")
    print("=" * 80)

    print()
    print(
        "Период БД:",
        start_time,
        "->",
        end_time
    )

    events = load_events(
        cursor,
        start_time,
        end_time
    )

    singles = load_singles(
        cursor,
        start_time,
        end_time
    )

    print()
    print(
        "EVENT:",
        len(events)
    )

    print(
        "SINGLE:",
        len(singles)
    )

    candidate_ids = set()

    for event in events:
        for row in event:
            candidate_ids.add(
                row[0]
            )

    for row in singles:
        candidate_ids.add(
            row[0]
        )

    print(
        "Кандидатов:",
        len(candidate_ids)
    )

    # --------------------------------------------------------
    # NOTHING NEW
    # --------------------------------------------------------

    if not events and not singles:

        print(
            "Новых материалов "
            "за период нет."
        )

        update_state(
            cursor,
            end_time
        )

        conn.commit()

        return

    # --------------------------------------------------------
    # LLM
    # --------------------------------------------------------

    prompt = build_prompt(
        events,
        singles
    )

    print(
        "Размер промпта:",
        len(prompt)
    )

    response = ollama.Client(timeout=float(os.getenv("OLLAMA_TIMEOUT", "180"))).chat(
        model=MODEL,
        format="json",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты редактор новостей. "
                    "Возвращай только "
                    "валидный JSON."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw = (
        response["message"]["content"]
        .strip()
    )

    try:
        payload = json.loads(
            raw
        )

    except Exception:

        print(
            "Модель вернула "
            "невалидный JSON:"
        )

        print(raw)


        raise

    items = validate_payload(
        payload,
        candidate_ids
    )

    print(
        "Итоговых новостей:",
        len(items)
    )

    # --------------------------------------------------------
    # MODEL REJECTED EVERYTHING
    # --------------------------------------------------------

    if not items and payload.get("items"):
        raise ValueError("All generated items failed validation; keeping the period for retry")

    if not items:

        print(
            "Модель не выбрала "
            "полезных материалов."
        )

        update_state(
            cursor,
            end_time
        )

        conn.commit()

        return

    # --------------------------------------------------------
    # SAVE DIGEST
    # --------------------------------------------------------

    payload_json = json.dumps(
        {
            "items": items
        },
        ensure_ascii=False
    )

    text = fallback_text(
        items
    )

    generated_at = (
        now_utc()
        .isoformat()
    )

    cursor.execute("""
        INSERT INTO digests (
            period_start,
            period_end,
            generated_at,
            text,
            model,
            input_chars,
            payload_json
        )

        VALUES (
            ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        start_time,
        end_time,
        generated_at,
        text,
        MODEL,
        len(prompt),
        payload_json
    ))

    digest_id = (
        cursor.lastrowid
    )

    # --------------------------------------------------------
    # ONLY ACTUALLY SELECTED MESSAGES
    # --------------------------------------------------------

    selected_ids = set()

    for item in items:
        selected_ids.update(
            item["message_ids"]
        )

    for message_id in selected_ids:

        cursor.execute("""
            INSERT OR IGNORE
            INTO digest_messages (
                digest_id,
                message_id
            )

            VALUES (?, ?)
        """, (
            digest_id,
            message_id
        ))

    conn.commit()

    print()
    print(
        "Digest ID:",
        digest_id
    )

    print(
        "Выбрано исходных сообщений:",
        len(selected_ids)
    )


def main():
    with connection(DB_FILE, timeout=30) as conn:
        generate(conn)


if __name__ == "__main__":
    main()