import json
import sqlite3
from datetime import datetime

import numpy as np

from paths import (
    DB_FILE,
    EMBEDDINGS_FILE,
    METADATA_FILE,
)


# Насколько новый пост должен быть похож
# на ЦЕНТР кластера.
CENTROID_THRESHOLD = 0.86

# Дополнительная проверка:
# хотя бы с одним постом внутри кластера
# similarity должна быть высокой.
MEMBER_THRESHOLD = 0.90

# Максимальное временное окно одного EVENT.
MAX_EVENT_HOURS = 8

# Минимальный размер события.
MIN_CLUSTER_SIZE = 2

# Ограничиваем размер одного EVENT,
# чтобы он не превращался в огромную тему.
MAX_CLUSTER_SIZE = 15


def parse_date(value):
    return datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )


def init_cluster_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_messages (
            event_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,

            UNIQUE(event_id, message_id),

            FOREIGN KEY(event_id)
                REFERENCES events(id),

            FOREIGN KEY(message_id)
                REFERENCES messages(id)
        )
    """)

    conn.commit()


def normalize_vector(vector):
    norm = np.linalg.norm(vector)

    if norm == 0:
        return vector

    return vector / norm


def calculate_centroid(
    embeddings,
    indexes
):
    vectors = embeddings[indexes]

    centroid = vectors.mean(
        axis=0
    )

    return normalize_vector(
        centroid
    )


def get_cluster_time_range(
    metadata,
    indexes
):
    dates = [
        parse_date(
            metadata[index]["message_date"]
        )
        for index in indexes
    ]

    return min(dates), max(dates)


def can_join_cluster(
    candidate_index,
    cluster_indexes,
    embeddings,
    metadata
):
    # Не даём событию бесконечно разрастаться.
    if (
        len(cluster_indexes)
        >= MAX_CLUSTER_SIZE
    ):
        return False

    candidate = metadata[
        candidate_index
    ]

    candidate_date = parse_date(
        candidate["message_date"]
    )

    # Проверяем временной диапазон.
    cluster_start, cluster_end = (
        get_cluster_time_range(
            metadata,
            cluster_indexes
        )
    )

    new_start = min(
        cluster_start,
        candidate_date
    )

    new_end = max(
        cluster_end,
        candidate_date
    )

    hours_span = (
        new_end - new_start
    ).total_seconds() / 3600

    if hours_span > MAX_EVENT_HOURS:
        return False

    # Проверяем similarity к центру кластера.
    centroid = calculate_centroid(
        embeddings,
        cluster_indexes
    )

    candidate_vector = embeddings[
        candidate_index
    ]

    centroid_similarity = float(
        candidate_vector @ centroid
    )

    if (
        centroid_similarity
        < CENTROID_THRESHOLD
    ):
        return False

    # Дополнительно требуем,
    # чтобы кандидат был очень похож
    # хотя бы на один конкретный пост.
    member_vectors = embeddings[
        cluster_indexes
    ]

    member_similarities = (
        member_vectors
        @ candidate_vector
    )

    best_member_similarity = float(
        member_similarities.max()
    )

    if (
        best_member_similarity
        < MEMBER_THRESHOLD
    ):
        return False

    return True


def main():
    print(
        "Загружаю embeddings..."
    )

    embeddings = np.load(
        EMBEDDINGS_FILE
    )

    with open(
        METADATA_FILE,
        "r",
        encoding="utf-8"
    ) as file:
        metadata = json.load(file)

    print(
        "Сообщений:",
        len(metadata)
    )

    # Обрабатываем по времени.
    indexes = list(
        range(len(metadata))
    )

    indexes.sort(
        key=lambda index:
        parse_date(
            metadata[index][
                "message_date"
            ]
        )
    )

    clusters = []

    print()
    print(
        "Строю строгие EVENT..."
    )
    print()

    for candidate_index in indexes:

        best_cluster = None
        best_score = -1

        for cluster_indexes in clusters:

            if not can_join_cluster(
                candidate_index,
                cluster_indexes,
                embeddings,
                metadata
            ):
                continue

            centroid = calculate_centroid(
                embeddings,
                cluster_indexes
            )

            score = float(
                embeddings[
                    candidate_index
                ]
                @ centroid
            )

            if score > best_score:
                best_score = score
                best_cluster = (
                    cluster_indexes
                )

        if best_cluster is not None:
            best_cluster.append(
                candidate_index
            )
        else:
            clusters.append([
                candidate_index
            ])

    # Оставляем только настоящие
    # многопостовые события.
    final_clusters = [
        cluster
        for cluster in clusters
        if len(cluster)
        >= MIN_CLUSTER_SIZE
    ]

    final_clusters.sort(
        key=len,
        reverse=True
    )

    print(
        "Всего кластеров:",
        len(final_clusters)
    )

    conn = sqlite3.connect(
        DB_FILE
    )

    init_cluster_tables(conn)

    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM event_messages"
    )

    cursor.execute(
        "DELETE FROM events"
    )

    conn.commit()

    now = datetime.now().isoformat()

    for cluster in final_clusters:

        cursor.execute("""
            INSERT INTO events (
                created_at
            )
            VALUES (?)
        """, (now,))

        event_id = (
            cursor.lastrowid
        )

        for index in cluster:

            message_id = (
                metadata[index]["id"]
            )

            cursor.execute("""
                INSERT INTO event_messages (
                    event_id,
                    message_id
                )
                VALUES (?, ?)
            """, (
                event_id,
                message_id
            ))

    conn.commit()

    print()
    print(
        "EVENT сохранены."
    )
    print()

    cursor.execute("""
        SELECT
            e.id,
            COUNT(*) AS cnt
        FROM events e

        JOIN event_messages em
          ON em.event_id = e.id

        GROUP BY e.id

        ORDER BY cnt DESC

        LIMIT 30
    """)

    rows = cursor.fetchall()

    print(
        "Самые крупные события:"
    )
    print()

    for event_id, count in rows:
        print(
            f"EVENT {event_id}: "
            f"{count} сообщений"
        )

    conn.close()


if __name__ == "__main__":
    main()