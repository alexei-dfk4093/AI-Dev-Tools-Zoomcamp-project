import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "economind.db"


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    target_path = db_path or DEFAULT_DB_PATH
    target_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                parent_span_id TEXT,
                name TEXT NOT NULL,
                started_at TEXT NOT NULL,
                duration_ms REAL NOT NULL,
                status TEXT NOT NULL,
                attributes_json TEXT NOT NULL DEFAULT '{}'
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                span_id TEXT,
                level TEXT NOT NULL,
                logger_name TEXT NOT NULL,
                message TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL NOT NULL,
                dimensions_json TEXT NOT NULL DEFAULT '{}',
                trace_id TEXT,
                recorded_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_spans_trace ON telemetry_spans(trace_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_spans_parent ON telemetry_spans(parent_span_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_logs_trace ON telemetry_logs(trace_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_telemetry_metrics_name ON telemetry_metrics(name);"
        )
        conn.commit()


def insert_span(span: dict[str, Any], db_path: Path | None = None) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO telemetry_spans (
                trace_id, span_id, parent_span_id, name, started_at,
                duration_ms, status, attributes_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                span["trace_id"],
                span["span_id"],
                span["parent_span_id"],
                span["name"],
                span["started_at"],
                span["duration_ms"],
                span["status"],
                json.dumps(span["attributes"], ensure_ascii=False),
            ),
        )
        conn.commit()


def insert_log(
    *,
    trace_id: str | None,
    span_id: str | None,
    level: str,
    logger_name: str,
    message: str,
    db_path: Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO telemetry_logs (
                trace_id, span_id, level, logger_name, message, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                trace_id,
                span_id,
                level,
                logger_name,
                message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def insert_metric(
    *,
    name: str,
    value: float,
    dimensions: dict[str, Any],
    trace_id: str | None = None,
    db_path: Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO telemetry_metrics (
                name, value, dimensions_json, trace_id, recorded_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                name,
                value,
                json.dumps(dimensions, ensure_ascii=False),
                trace_id,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def prune_spans(limit: int, db_path: Path | None = None) -> None:
    _prune("telemetry_spans", limit, db_path)


def prune_logs(limit: int, db_path: Path | None = None) -> None:
    _prune("telemetry_logs", limit, db_path)


def prune_metrics(limit: int, db_path: Path | None = None) -> None:
    _prune("telemetry_metrics", limit, db_path)


def _prune(
    table: str,
    limit: int,
    db_path: Path | None = None,
) -> None:
    """Keep only the newest ``limit`` rows so telemetry cannot grow unbounded."""
    with get_connection(db_path) as conn:
        conn.execute(
            f"""
            DELETE FROM {table}
            WHERE id NOT IN (
                SELECT id FROM {table} ORDER BY id DESC LIMIT ?
            )
            """,
            (limit,),
        )
        conn.commit()


def list_root_spans(
    limit: int = 30,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the newest root spans; each root span starts one journey."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, span_id, parent_span_id, name, started_at,
                   duration_ms, status, attributes_json
            FROM telemetry_spans
            WHERE parent_span_id IS NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_span_row(row) for row in rows]


def _span_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "trace_id": row["trace_id"],
        "span_id": row["span_id"],
        "parent_span_id": row["parent_span_id"],
        "name": row["name"],
        "started_at": row["started_at"],
        "duration_ms": row["duration_ms"],
        "status": row["status"],
        "attributes": _load_json(row["attributes_json"]),
    }


def _load_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def get_spans_for_trace(
    trace_id: str,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, span_id, parent_span_id, name, started_at,
                   duration_ms, status, attributes_json
            FROM telemetry_spans
            WHERE trace_id = ?
            ORDER BY started_at, id
            """,
            (trace_id,),
        ).fetchall()
    return [_span_row(row) for row in rows]


def get_logs_for_trace(
    trace_id: str,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT trace_id, span_id, level, logger_name, message, recorded_at
            FROM telemetry_logs
            WHERE trace_id = ?
            ORDER BY id
            LIMIT ?
            """,
            (trace_id, limit),
        ).fetchall()
    return [
        {
            "trace_id": row["trace_id"],
            "span_id": row["span_id"],
            "level": row["level"],
            "logger_name": row["logger_name"],
            "message": row["message"],
            "recorded_at": row["recorded_at"],
        }
        for row in rows
    ]


def get_metrics_for_trace(
    trace_id: str,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT name, value, dimensions_json, trace_id, recorded_at
            FROM telemetry_metrics
            WHERE trace_id = ?
            ORDER BY id
            """,
            (trace_id,),
        ).fetchall()
    return [
        {
            "name": row["name"],
            "value": row["value"],
            "dimensions": _load_json(row["dimensions_json"]),
            "trace_id": row["trace_id"],
            "recorded_at": row["recorded_at"],
        }
        for row in rows
    ]


def count_trace_spans(
    trace_ids: list[str],
    db_path: Path | None = None,
) -> dict[str, dict[str, int]]:
    """Return span totals per trace id: total spans and errored spans."""
    if not trace_ids:
        return {}
    placeholders = ", ".join("?" for _ in trace_ids)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT trace_id,
                   COUNT(*) AS span_count,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count
            FROM telemetry_spans
            WHERE trace_id IN ({placeholders})
            GROUP BY trace_id
            """,
            trace_ids,
        ).fetchall()
        log_rows = conn.execute(
            f"""
            SELECT trace_id, COUNT(*) AS log_count
            FROM telemetry_logs
            WHERE trace_id IN ({placeholders})
            GROUP BY trace_id
            """,
            trace_ids,
        ).fetchall()

    summary = {
        row["trace_id"]: {
            "span_count": int(row["span_count"]),
            "error_count": int(row["error_count"] or 0),
        }
        for row in rows
    }
    log_counts = {
        row["trace_id"]: int(row["log_count"])
        for row in log_rows
    }
    for trace_id in summary:
        summary[trace_id]["log_count"] = log_counts.get(trace_id, 0)
    return summary


def metric_rows(
    name: str,
    limit: int = 4000,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the newest recorded samples for one metric name."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT name, value, dimensions_json, trace_id, recorded_at
            FROM telemetry_metrics
            WHERE name = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (name, limit),
        ).fetchall()
    return [
        {
            "name": row["name"],
            "value": row["value"],
            "dimensions": _load_json(row["dimensions_json"]),
            "trace_id": row["trace_id"],
            "recorded_at": row["recorded_at"],
        }
        for row in rows
    ]
