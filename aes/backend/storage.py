from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class HistoryStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT NOT NULL,
                    filename TEXT,
                    default_essay_set INTEGER,
                    item_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    submission_id INTEGER NOT NULL,
                    row_no INTEGER NOT NULL,
                    essay_set INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    scaled_score REAL NOT NULL,
                    essay_text TEXT NOT NULL,
                    preview TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    FOREIGN KEY(submission_id) REFERENCES submissions(id)
                )
                """
            )

    def save_submission(
        self,
        source_type: str,
        filename: str | None,
        default_essay_set: int | None,
        records: list[dict[str, Any]],
    ) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO submissions (source_type, filename, default_essay_set, item_count)
                VALUES (?, ?, ?, ?)
                """,
                (source_type, filename, default_essay_set, len(records)),
            )
            submission_id = int(cursor.lastrowid)

            conn.executemany(
                """
                INSERT INTO records (
                    submission_id, row_no, essay_set, score, scaled_score, essay_text, preview, analysis_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        submission_id,
                        int(item["row"]),
                        int(item["essay_set"]),
                        int(item["score"]),
                        float(item["scaled_score"]),
                        str(item["essay_text"]),
                        str(item["preview"]),
                        json.dumps(item["analysis"], ensure_ascii=False),
                    )
                    for item in records
                ],
            )

        return submission_id

    def get_submissions(
        self,
        limit: int = 20,
        offset: int = 0,
        default_essay_set: int | None | str = "all",
        source_type: str = "all",
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            where_clauses: list[str] = []
            params: list[Any] = []

            if default_essay_set is None:
                where_clauses.append("default_essay_set IS NULL")
            elif default_essay_set != "all":
                where_clauses.append("default_essay_set = ?")
                params.append(int(default_essay_set))

            if source_type != "all":
                where_clauses.append("source_type = ?")
                params.append(source_type)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            rows = conn.execute(
                f"""
                SELECT id, source_type, filename, default_essay_set, item_count, created_at
                FROM submissions
                {where_sql}
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, limit, offset],
            ).fetchall()

        return [dict(r) for r in rows]

    def count_submissions(
        self,
        default_essay_set: int | None | str = "all",
        source_type: str = "all",
    ) -> int:
        with self._connect() as conn:
            where_clauses: list[str] = []
            params: list[Any] = []

            if default_essay_set is None:
                where_clauses.append("default_essay_set IS NULL")
            elif default_essay_set != "all":
                where_clauses.append("default_essay_set = ?")
                params.append(int(default_essay_set))

            if source_type != "all":
                where_clauses.append("source_type = ?")
                params.append(source_type)

            where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
            row = conn.execute(
                f"SELECT COUNT(1) AS total FROM submissions {where_sql}",
                params,
            ).fetchone()
            return int(row["total"]) if row is not None else 0

    def get_submission_detail(self, submission_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            submission = conn.execute(
                """
                SELECT id, source_type, filename, default_essay_set, item_count, created_at
                FROM submissions
                WHERE id = ?
                """,
                (submission_id,),
            ).fetchone()
            if submission is None:
                return None

            records = conn.execute(
                """
                SELECT row_no, essay_set, score, scaled_score, essay_text, preview, analysis_json
                FROM records
                WHERE submission_id = ?
                ORDER BY row_no ASC
                """,
                (submission_id,),
            ).fetchall()

        payload = dict(submission)
        payload["records"] = [
            {
                "row": int(r["row_no"]),
                "essay_set": int(r["essay_set"]),
                "score": int(r["score"]),
                "scaled_score": float(r["scaled_score"]),
                "essay_text": r["essay_text"],
                "preview": r["preview"],
                "analysis": json.loads(r["analysis_json"]),
            }
            for r in records
        ]
        return payload

    def delete_submission(self, submission_id: int) -> bool:
        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM submissions WHERE id = ?",
                (submission_id,),
            ).fetchone()
            if exists is None:
                return False

            conn.execute("DELETE FROM records WHERE submission_id = ?", (submission_id,))
            conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
        return True
