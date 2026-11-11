import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from app.schemas.news import AffectedAsset, NewsArticle

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
            CREATE TABLE IF NOT EXISTS articles (
                id TEXT PRIMARY KEY,
                source TEXT,
                published_at TEXT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                summary TEXT,
                article_content TEXT,
                summary_source TEXT NOT NULL,
                importance TEXT NOT NULL,
                category TEXT NOT NULL,
                summary_prompt_version INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(articles)").fetchall()
        }
        if "article_content" not in columns:
            conn.execute("ALTER TABLE articles ADD COLUMN article_content TEXT")
        if "summary_prompt_version" not in columns:
            conn.execute(
                "ALTER TABLE articles ADD COLUMN summary_prompt_version INTEGER NOT NULL DEFAULT 0"
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_cursors (
                provider TEXT PRIMARY KEY,
                next_page INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_state (
                provider TEXT PRIMARY KEY,
                last_success_at TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS article_market_assets (
                article_id TEXT PRIMARY KEY,
                prompt_version INTEGER NOT NULL,
                assets_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS article_insights (
                article_id TEXT PRIMARY KEY,
                prompt_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        conn.commit()


def get_provider_cursor(
    provider: str,
    db_path: Path | None = None,
) -> int | None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_cursors (
                provider TEXT PRIMARY KEY,
                next_page INTEGER NOT NULL
            );
            """
        )
        row = conn.execute(
            "SELECT next_page FROM provider_cursors WHERE provider = ?",
            (provider,),
        ).fetchone()
        return int(row["next_page"]) if row else None


def set_provider_cursor(
    provider: str,
    next_page: int,
    db_path: Path | None = None,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_cursors (
                provider TEXT PRIMARY KEY,
                next_page INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO provider_cursors (provider, next_page)
            VALUES (?, ?)
            ON CONFLICT(provider) DO UPDATE SET next_page = excluded.next_page
            """,
            (provider, next_page),
        )
        conn.commit()


def get_provider_state(
    provider: str,
    db_path: Path | None = None,
) -> datetime | None:
    """Return the timestamp of the last successful provider fetch, if any."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_state (
                provider TEXT PRIMARY KEY,
                last_success_at TIMESTAMP
            );
            """
        )
        row = conn.execute(
            "SELECT last_success_at FROM provider_state WHERE provider = ?",
            (provider,),
        ).fetchone()

    if row is None or not row["last_success_at"]:
        return None

    return _parse_timestamp(row["last_success_at"])


def set_provider_state(
    provider: str,
    timestamp: datetime | None = None,
    db_path: Path | None = None,
) -> None:
    """Record that the provider was fetched successfully."""
    moment = timestamp or datetime.now(timezone.utc)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_state (
                provider TEXT PRIMARY KEY,
                last_success_at TIMESTAMP
            );
            """
        )
        conn.execute(
            """
            INSERT INTO provider_state (provider, last_success_at)
            VALUES (?, ?)
            ON CONFLICT(provider) DO UPDATE SET last_success_at = excluded.last_success_at
            """,
            (provider, moment.strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()


def _parse_timestamp(value: str) -> datetime | None:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def get_newest_published_at(
    category: str | None = None,
    db_path: Path | None = None,
) -> str | None:
    """Return the newest publication timestamp currently stored."""
    with get_connection(db_path) as conn:
        if category and category != "all":
            row = conn.execute(
                "SELECT MAX(published_at) AS newest FROM articles WHERE category = ?",
                (category,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT MAX(published_at) AS newest FROM articles"
            ).fetchone()

    return row["newest"] if row and row["newest"] else None


def get_existing_article_ids(db_path: Path | None = None) -> set[str]:
    """Return the ids of every stored article, used to skip known items."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT id FROM articles").fetchall()
    return {row["id"] for row in rows}


def update_article_content(
    article_id: str,
    content: str,
    db_path: Path | None = None,
) -> None:
    """Store the extracted body text for an article."""
    if not content:
        return

    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE articles SET article_content = ? WHERE id = ?",
            (content, article_id),
        )
        conn.commit()


def get_articles_missing_content(
    limit: int = 10,
    db_path: Path | None = None,
) -> list[NewsArticle]:
    """Return stored articles that still have no extracted body text."""
    with get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT id, source, published_at, url, title, summary, summary_source,
                   importance, category, summary_prompt_version
            FROM articles
            WHERE article_content IS NULL OR length(article_content) < 200
            ORDER BY published_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    results: list[NewsArticle] = []
    for row in rows:
        try:
            results.append(
                NewsArticle(
                    id=row["id"],
                    source=row["source"],
                    published_at=row["published_at"],
                    url=row["url"],
                    title=row["title"],
                    summary=row["summary"],
                    summary_source=row["summary_source"],
                    summary_prompt_version=row["summary_prompt_version"],
                    importance=row["importance"],
                    category=row["category"],
                )
            )
        except Exception as exc:
            logger.warning("Failed to deserialize article %s: %s", row["id"], exc)

    return results


def get_article_insights(
    article_id: str,
    prompt_version: int,
    db_path: Path | None = None,
) -> dict | None:
    """Return the cached article analysis payload, if it is still current."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS article_insights (
                article_id TEXT PRIMARY KEY,
                prompt_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        row = conn.execute(
            """
            SELECT payload_json FROM article_insights
            WHERE article_id = ? AND prompt_version = ?
            """,
            (article_id, prompt_version),
        ).fetchone()

    if row is None:
        return None

    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError):
        return None

    return payload if isinstance(payload, dict) else None


def save_article_insights(
    article_id: str,
    prompt_version: int,
    payload: dict,
    db_path: Path | None = None,
) -> None:
    """Store the article analysis payload for reuse."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS article_insights (
                article_id TEXT PRIMARY KEY,
                prompt_version INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO article_insights (article_id, prompt_version, payload_json)
            VALUES (?, ?, ?)
            ON CONFLICT(article_id) DO UPDATE SET
                prompt_version = excluded.prompt_version,
                payload_json = excluded.payload_json
            """,
            (
                article_id,
                prompt_version,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def save_articles(articles: list[NewsArticle], db_path: Path | None = None) -> int:
    if not articles:
        return 0

    inserted_count = 0
    with get_connection(db_path) as conn:
        for article in articles:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO articles (
                    id, source, published_at, url, title, summary, article_content,
                    summary_source, importance, category, summary_prompt_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.id,
                    article.source,
                    article.published_at,
                    str(article.url),
                    article.title,
                    article.summary,
                    article.article_content,
                    article.summary_source,
                    article.importance,
                    article.category,
                    article.summary_prompt_version,
                ),
            )
            inserted_count += cursor.rowcount
        conn.commit()
    return inserted_count


def get_articles(
    limit: int = 20,
    offset: int = 0,
    category: str | None = None,
    db_path: Path | None = None,
) -> list[NewsArticle]:
    with get_connection(db_path) as conn:
        if category and category != "all":
            cursor = conn.execute(
                """
                SELECT id, source, published_at, url, title, summary, summary_source, importance, category, summary_prompt_version
                FROM articles
                WHERE category = ?
                ORDER BY published_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                (category, limit, offset),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, source, published_at, url, title, summary, summary_source, importance, category, summary_prompt_version
                FROM articles
                ORDER BY published_at DESC, created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        rows = cursor.fetchall()

    result: list[NewsArticle] = []
    for row in rows:
        try:
            result.append(
                NewsArticle(
                    id=row["id"],
                    source=row["source"],
                    published_at=row["published_at"],
                    url=row["url"],
                    title=row["title"],
                    summary=row["summary"],
                    summary_source=row["summary_source"],
                    summary_prompt_version=row["summary_prompt_version"],
                    importance=row["importance"],
                    category=row["category"],
                )
            )
        except Exception as exc:
            logger.warning("Failed to deserialize cached article %s: %s", row["id"], exc)

    return result


def get_article(article_id: str, db_path: Path | None = None) -> NewsArticle | None:
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, source, published_at, url, title, summary, article_content,
                   summary_source, importance, category, summary_prompt_version
            FROM articles
            WHERE id = ?
            """,
            (article_id,),
        ).fetchone()

    if row is None:
        return None

    try:
        return NewsArticle(
            id=row["id"],
            source=row["source"],
            published_at=row["published_at"],
            url=row["url"],
            title=row["title"],
            summary=row["summary"],
            article_content=row["article_content"],
            summary_source=row["summary_source"],
            summary_prompt_version=row["summary_prompt_version"],
            importance=row["importance"],
            category=row["category"],
        )
    except Exception as exc:
        logger.warning("Failed to deserialize cached article %s: %s", article_id, exc)
        return None


def update_article_summaries(
    summaries: dict[str, str],
    prompt_version: int,
) -> None:
    if not summaries:
        return

    with get_connection() as conn:
        conn.executemany(
            """
            UPDATE articles
            SET summary = ?, summary_source = 'ai', summary_prompt_version = ?
            WHERE id = ?
            """,
            [
                (summary, prompt_version, article_id)
                for article_id, summary in summaries.items()
            ],
        )
        conn.commit()


def count_articles(category: str | None = None, db_path: Path | None = None) -> int:
    with get_connection(db_path) as conn:
        if category and category != "all":
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM articles WHERE category = ?",
                (category,),
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM articles")
        row = cursor.fetchone()
        return int(row["cnt"]) if row else 0
