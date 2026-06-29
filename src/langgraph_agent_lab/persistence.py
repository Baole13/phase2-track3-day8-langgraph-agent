"""Checkpointer adapter."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> object | None:
    """Return a LangGraph checkpointer.

    TODO(student): implement SQLite support for the persistence extension track.
    The starter provides MemorySaver only — SQLite/Postgres are extension tasks.

    For SQLite:
    - pip install langgraph-checkpoint-sqlite
    - Use SqliteSaver with sqlite3.connect() and WAL mode
    - See: https://langchain-ai.github.io/langgraph/how-tos/persistence/
    """
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires langgraph-checkpoint-sqlite. "
                "Install it with: pip install langgraph-checkpoint-sqlite"
            ) from exc

        raw_path = database_url or "outputs/langgraph_agent_lab.sqlite"
        sqlite_path = raw_path.removeprefix("sqlite:///")
        path = Path(sqlite_path)
        resolved_path = path.resolve(strict=False)
        if not str(resolved_path).isascii():
            path = Path(tempfile.gettempdir()) / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("SELECT 1;")
        except sqlite3.OperationalError:
            fallback_path = Path(tempfile.gettempdir()) / path.name
            conn = sqlite3.connect(fallback_path, check_same_thread=False)
            conn.execute("PRAGMA synchronous=NORMAL;")
        return SqliteSaver(conn=conn)
    if kind == "postgres":
        raise NotImplementedError(
            "TODO(student): implement Postgres checkpointer (optional extension)"
        )
    raise ValueError(f"Unknown checkpointer kind: {kind}")
