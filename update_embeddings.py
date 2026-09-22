import json
import sqlite3

import numpy as np
from sentence_transformers import SentenceTransformer

from paths import (
    DB_FILE,
    EMBEDDINGS_FILE,
    METADATA_FILE,
    ensure_directories,
)


MODEL_NAME = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

BATCH_SIZE = 32


def main():
    ensure_directories()

    if EMBEDDINGS_FILE.exists():
        embeddings = np.load(
            EMBEDDINGS_FILE
        )

        print(
            "Существующих embeddings:",
            len(embeddings)
        )
    else:
        embeddings = np.empty(
            (0, 384),
            dtype=np.float32
        )

        print(
            "Файл embeddings пока отсутствует."
        )

    if METADATA_FILE.exists():
        with open(
            METADATA_FILE,
            "r",
            encoding="utf-8"
        ) as file:
            metadata = json.load(file)
    else:
        metadata = []

    existing_ids = {
        item["id"]
        for item in metadata
    }

    print(
        "Записей metadata:",
        len(metadata)
    )

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            chat_id,
            chat_title,
            chat_username,
            telegram_message_id,
            message_date,
            cleaned_text,
            post_url

        FROM messages

        WHERE cleaned_text IS NOT NULL
          AND TRIM(cleaned_text) != ''
          AND COALESCE(is_ad, 0) = 0

        ORDER BY message_date
    """)

    rows = cursor.fetchall()
    conn.close()

    new_rows = [
        row
        for row in rows
        if row[0] not in existing_ids
    ]

    print()
    print(
        "Новых сообщений для embeddings:",
        len(new_rows)
    )

    if not new_rows:
        print()
        print(
            "Новых embeddings считать не нужно."
        )
        return

    texts = []
    new_metadata = []

    for row in new_rows:
        (
            message_id,
            chat_id,
            chat_title,
            chat_username,
            telegram_message_id,
            message_date,
            cleaned_text,
            post_url
        ) = row

        texts.append(
            cleaned_text
        )

        new_metadata.append({
            "id": message_id,
            "chat_id": chat_id,
            "chat_title": chat_title,
            "chat_username": chat_username,
            "telegram_message_id": telegram_message_id,
            "message_date": message_date,
            "post_url": post_url,
        })

    print()
    print(
        "Загружаю embedding-модель..."
    )

    model = SentenceTransformer(
        MODEL_NAME
    )

    print()
    print(
        "Считаю embeddings только для новых сообщений..."
    )

    new_embeddings = model.encode(
        texts,
        batch_size=BATCH_SIZE,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )

    new_embeddings = np.asarray(
        new_embeddings,
        dtype=np.float32
    )

    if len(embeddings) == 0:
        embeddings = new_embeddings
    else:
        embeddings = np.vstack([
            embeddings,
            new_embeddings
        ])

    metadata.extend(
        new_metadata
    )

    np.save(
        EMBEDDINGS_FILE,
        embeddings
    )

    with open(
        METADATA_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2
        )

    print()
    print("=" * 70)

    print(
        "Добавлено embeddings:",
        len(new_embeddings)
    )

    print(
        "Всего embeddings:",
        len(embeddings)
    )

    print(
        "Всего metadata:",
        len(metadata)
    )

    print("=" * 70)


if __name__ == "__main__":
    main()