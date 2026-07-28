"""Supabase (Postgres + pgvector) data layer for the FastAPI backend.

This is the Supabase counterpart to clickhouse_client.py. The legacy Streamlit
app keeps talking to ClickHouse; the new backend imports this module instead.
Schema is owned by supabase/migrations/, not created here.

Connection is driven by the SUPABASE_DB_URL env var (a full Postgres DSN). The
backend connects as the service role, so RLS is bypassed and per-user scoping is
enforced in application code by always passing the authenticated user_id (a
Supabase auth UUID) into the query helpers below.

Embeddings (openai/text-embedding-3-small, 1536-dim) are sent as pgvector
literal strings and ranked with the cosine-distance operator <=>, replacing
ClickHouse's Array(Float32) + cosineDistance.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any, Iterable, Sequence

import psycopg
from psycopg_pool import ConnectionPool

EMBED_DIM = 1536

# A process-wide connection pool. Opening a fresh Postgres connection to the
# Supabase pooler (TLS + pooler auth) costs ~300-500ms, which dominated every
# request when callers connected per call. The pool reuses warm connections so
# requests pay near-zero connect time.
_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    """Lazily build the shared pool from SUPABASE_DB_URL (thread-safe)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    conninfo=os.environ["SUPABASE_DB_URL"],
                    min_size=1,
                    max_size=10,
                    max_idle=300.0,
                    kwargs={"autocommit": True},
                    open=True,
                )
    return _pool


class _PooledConnection:
    """Proxy that returns its connection to the pool on close().

    Preserves the existing `conn = get_conn(); try: ...; finally: conn.close()`
    call pattern -- close() checks the connection back in instead of tearing
    down the socket. All other attribute access (execute, cursor, ...) is
    forwarded to the real connection.
    """

    def __init__(self, pool: ConnectionPool, conn: psycopg.Connection) -> None:
        self._pool = pool
        self._conn: psycopg.Connection | None = conn

    def close(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            self._pool.putconn(conn)

    def __getattr__(self, name: str) -> Any:
        if self._conn is None:
            raise RuntimeError("connection already returned to the pool")
        return getattr(self._conn, name)


def get_conn() -> Any:
    """Check out a pooled Postgres connection.

    Returns a proxy whose close() returns the connection to the pool, so the
    existing get_conn()/close() call sites keep working but stop paying the
    per-request connection handshake. Autocommit is on.
    """
    pool = _get_pool()
    return _PooledConnection(pool, pool.getconn())


def _vec(embedding: Sequence[float]) -> str:
    """Format an embedding as a pgvector literal, e.g. '[0.1,0.2,...]'.

    pgvector accepts the literal as text and casts it with ::vector in SQL.
    """
    if len(embedding) != EMBED_DIM:
        raise ValueError(
            f"embedding has {len(embedding)} dims, expected {EMBED_DIM}"
        )
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"


# ---------------------------------------------------------------------------
# trace_log
# ---------------------------------------------------------------------------

def insert_trace(
    session_id: str,
    user_id: str | None,
    kind: str,
    payload: dict[str, Any],
    conn: psycopg.Connection | None = None,
) -> None:
    """Append a single trace event to trace_log.

    user_id is the authenticated Supabase auth UUID, or None for system/CLI
    traces that no end user should be able to read back.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        conn.execute(
            "INSERT INTO trace_log (session_id, user_id, ts, kind, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            (session_id, user_id, datetime.now(), kind, json.dumps(payload, default=str)),
        )
    finally:
        if owns:
            conn.close()


def fetch_traces(
    session_id: str, user_id: str, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Return all trace events for a session in chronological order.

    user_id is required and scopes the read. session_id alone is not a
    secret -- it is echoed to the client and threaded through requests, so a
    caller who guessed or replayed another tenant's session_id must not be
    able to read that tenant's trace events (which can include cost_usd and
    prompt/criterion metadata) through the service-role connection.
    """
    if not user_id:
        raise ValueError("user_id is required")
    owns = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT ts, kind, payload FROM trace_log "
            "WHERE session_id = %s AND user_id = %s ORDER BY ts",
            (session_id, user_id),
        ).fetchall()
    finally:
        if owns:
            conn.close()
    return [{"ts": r[0], "kind": r[1], "payload": r[2]} for r in rows]


# ---------------------------------------------------------------------------
# session_artifacts
# ---------------------------------------------------------------------------

def insert_artifact(
    session_id: str,
    user_id: str | None,
    artifact_kind: str,
    artifact_name: str,
    content: str,
    repo: str = "",
    venue: str = "",
    metadata: dict[str, Any] | None = None,
    content_hash: str = "",
    conn: psycopg.Connection | None = None,
) -> None:
    """Append one generated artifact (paper, plugin, etc.) to session_artifacts.

    Best-effort at the caller layer: a Supabase outage must never block the
    user-facing download, so callers wrap this in try/except.
    """
    owns = conn is None
    conn = conn or get_conn()
    size = len(content.encode("utf-8"))
    try:
        conn.execute(
            "INSERT INTO session_artifacts "
            "(session_id, user_id, ts, artifact_kind, repo, venue, artifact_name, "
            " size_bytes, content_hash, content, metadata) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                session_id,
                user_id,
                datetime.now(),
                artifact_kind,
                repo,
                venue,
                artifact_name,
                size,
                content_hash,
                content,
                json.dumps(metadata or {}, default=str),
            ),
        )
    finally:
        if owns:
            conn.close()


def fetch_artifacts(
    user_id: str,
    session_id: str | None = None,
    artifact_kind: str | None = None,
    limit: int = 15,
    conn: psycopg.Connection | None = None,
) -> list[dict[str, Any]]:
    """Return artifact rows for one user (newest first).

    user_id is required so the Past Sessions panel never leaks across tenants.
    session_id and artifact_kind are optional refinements.
    """
    owns = conn is None
    conn = conn or get_conn()
    where = ["user_id = %s"]
    params: list[Any] = [user_id]
    if session_id is not None:
        where.append("session_id = %s")
        params.append(session_id)
    if artifact_kind is not None:
        where.append("artifact_kind = %s")
        params.append(artifact_kind)
    params.append(limit)
    sql = (
        "SELECT session_id, ts, artifact_kind, repo, venue, artifact_name, "
        "size_bytes, content_hash, metadata FROM session_artifacts "
        "WHERE " + " AND ".join(where) + " ORDER BY ts DESC LIMIT %s"
    )
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        if owns:
            conn.close()
    return [
        {
            "session_id": r[0],
            "ts": r[1],
            "artifact_kind": r[2],
            "repo": r[3],
            "venue": r[4],
            "artifact_name": r[5],
            "size_bytes": r[6],
            "content_hash": r[7],
            "metadata": r[8] or {},
        }
        for r in rows
    ]


def fetch_artifact_content(
    session_id: str,
    artifact_name: str,
    user_id: str,
    conn: psycopg.Connection | None = None,
) -> str | None:
    """Pull the raw content blob for one specific artifact (newest match).

    user_id is required and always scopes the lookup to that caller. The
    backend connects as the service role and bypasses RLS, so this filter is
    the only guard against one tenant reading another tenant's cached
    artifact by guessing or replaying a session id -- it used to be an
    optional parameter that, when omitted, silently dropped the filter
    entirely. Making it required means a caller who forgets it gets a
    TypeError at call time instead of a cross-tenant read at runtime.
    """
    owns = conn is None
    conn = conn or get_conn()
    where = ["session_id = %s", "artifact_name = %s", "user_id = %s"]
    params: list[Any] = [session_id, artifact_name, user_id]
    sql = (
        "SELECT content FROM session_artifacts "
        "WHERE " + " AND ".join(where) + " ORDER BY ts DESC LIMIT 1"
    )
    try:
        row = conn.execute(sql, params).fetchone()
    finally:
        if owns:
            conn.close()
    return row[0] if row else None


def session_owner(
    session_id: str, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the user_id already associated with a session, or None.

    Checks session_artifacts, then trace_log, for the first row recording a
    non-null user_id under this session_id. Used to guard against a
    caller-supplied session_id (e.g. POST /extract-plugin's optional
    session_id, meant to reuse a prior /ingest bundle) being reused to write
    rows into another tenant's session namespace. An unknown session_id
    returns None -- a fresh session, not a violation.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT user_id FROM session_artifacts "
            "WHERE session_id = %s AND user_id IS NOT NULL LIMIT 1",
            (session_id,),
        ).fetchone()
        if row and row[0]:
            return row[0]
        row = conn.execute(
            "SELECT user_id FROM trace_log "
            "WHERE session_id = %s AND user_id IS NOT NULL LIMIT 1",
            (session_id,),
        ).fetchone()
        if row and row[0]:
            return row[0]
        return None
    finally:
        if owns:
            conn.close()


# ---------------------------------------------------------------------------
# Vector search (cosine distance via <=>)
# ---------------------------------------------------------------------------

def match_cfp(
    q_emb: Sequence[float],
    horizon_days: int,
    limit: int,
    conn: psycopg.Connection | None = None,
) -> list[tuple[str, str, str, Any, str, float, int]]:
    """Rank open CFPs by cosine distance to the query embedding.

    Mirrors the ClickHouse query in cfp_match.rank_venues. Returns rows of
    (id, name, scope, deadline, url, dist, days_until_deadline) ordered by
    ascending cosine distance, filtered to deadlines within the horizon.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, scope, deadline, url, "
            "       scope_emb <=> %s::vector AS dist, "
            "       (deadline - current_date) AS days "
            "FROM cfp "
            "WHERE deadline > current_date "
            "  AND deadline < current_date + %s "
            "ORDER BY dist ASC LIMIT %s",
            (_vec(q_emb), horizon_days, limit),
        ).fetchall()
    finally:
        if owns:
            conn.close()
    return [
        (r[0], r[1], r[2], r[3], r[4], float(r[5]), int(r[6])) for r in rows
    ]


def list_cfp(
    search: str | None = None,
    format_filter: str | None = None,
    upcoming_only: bool = False,
    conn: psycopg.Connection | None = None,
) -> list[tuple[str, str, str, Any, str, str]]:
    """List CFPs, optionally filtered, ordered chronologically by deadline.

    Plain (non-semantic) listing for the CFP landing page. Returns rows of
    (id, name, scope, deadline, format, url). Deadlines are ordered ascending
    with nulls last; ties break on name for a stable order.
    """
    owns = conn is None
    conn = conn or get_conn()
    clauses: list[str] = []
    params: list[Any] = []
    if search:
        clauses.append("(name ILIKE %s OR scope ILIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    if format_filter:
        clauses.append("format = %s")
        params.append(format_filter)
    if upcoming_only:
        clauses.append("deadline >= current_date")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    try:
        rows = conn.execute(
            "SELECT id, name, scope, deadline, format, url "
            f"FROM cfp {where} "
            "ORDER BY deadline ASC NULLS LAST, name ASC",
            params,
        ).fetchall()
    finally:
        if owns:
            conn.close()
    return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows]


def match_arxiv(
    q_emb: Sequence[float],
    limit: int,
    conn: psycopg.Connection | None = None,
) -> list[tuple[str, str, str, int, list[str]]]:
    """Pre-filter arxiv candidates by cosine distance to the summary embedding.

    Mirrors arxiv_lookup.candidates_from_clickhouse. Returns rows of
    (id, title, abstract, year, authors) ordered by ascending cosine distance.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, abstract, year, authors "
            "FROM arxiv ORDER BY emb <=> %s::vector ASC LIMIT %s",
            (_vec(q_emb), limit),
        ).fetchall()
    finally:
        if owns:
            conn.close()
    return [
        (r[0], r[1], r[2], int(r[3]) if r[3] is not None else 0, list(r[4] or []))
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Bulk corpus upserts (used by the ClickHouse -> Supabase migration script)
# ---------------------------------------------------------------------------

def upsert_cfp(
    rows: Iterable[tuple[str, str, str, Any, str, str, Sequence[float]]],
    conn: psycopg.Connection | None = None,
) -> int:
    """Upsert CFP rows: (id, name, scope, deadline, format, url, scope_emb)."""
    owns = conn is None
    conn = conn or get_conn()
    n = 0
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO cfp (id, name, scope, deadline, format, url, scope_emb) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s::vector) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "name=EXCLUDED.name, scope=EXCLUDED.scope, deadline=EXCLUDED.deadline, "
                    "format=EXCLUDED.format, url=EXCLUDED.url, scope_emb=EXCLUDED.scope_emb",
                    (r[0], r[1], r[2], r[3], r[4], r[5], _vec(r[6])),
                )
                n += 1
    finally:
        if owns:
            conn.close()
    return n


def upsert_arxiv(
    rows: Iterable[tuple[str, str, str, int, Sequence[str], Sequence[float]]],
    conn: psycopg.Connection | None = None,
) -> int:
    """Upsert arxiv rows: (id, title, abstract, year, authors, emb)."""
    owns = conn is None
    conn = conn or get_conn()
    n = 0
    try:
        with conn.cursor() as cur:
            for r in rows:
                cur.execute(
                    "INSERT INTO arxiv (id, title, abstract, year, authors, emb) "
                    "VALUES (%s, %s, %s, %s, %s, %s::vector) "
                    "ON CONFLICT (id) DO UPDATE SET "
                    "title=EXCLUDED.title, abstract=EXCLUDED.abstract, year=EXCLUDED.year, "
                    "authors=EXCLUDED.authors, emb=EXCLUDED.emb",
                    (r[0], r[1], r[2], int(r[3]), list(r[4]), _vec(r[5])),
                )
                n += 1
    finally:
        if owns:
            conn.close()
    return n


# ---------------------------------------------------------------------------
# Purchases / entitlements (Stripe)
# ---------------------------------------------------------------------------

def record_pending_purchase(
    user_id: str,
    product: str,
    stripe_session_id: str,
    amount_cents: int,
    currency: str = "usd",
    conn: psycopg.Connection | None = None,
) -> None:
    """Insert a pending purchase row for a started Stripe Checkout session.

    Idempotent on stripe_session_id: a retried checkout for the same session is a
    no-op rather than a duplicate row.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        conn.execute(
            "INSERT INTO purchases "
            "(user_id, product, status, amount_cents, currency, stripe_session_id) "
            "VALUES (%s, %s, 'pending', %s, %s, %s) "
            "ON CONFLICT (stripe_session_id) DO NOTHING",
            (user_id, product, amount_cents, currency, stripe_session_id),
        )
    finally:
        if owns:
            conn.close()


def mark_purchase_paid(
    stripe_session_id: str,
    stripe_payment_intent: str | None = None,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Mark a purchase paid from a verified Stripe webhook.

    Returns True only when a row moved from not-paid to paid, so a duplicate
    webhook delivery is a no-op.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        cur = conn.execute(
            "UPDATE purchases "
            "SET status='paid', stripe_payment_intent=%s, updated_at=now() "
            "WHERE stripe_session_id=%s AND status <> 'paid'",
            (stripe_payment_intent, stripe_session_id),
        )
        return cur.rowcount > 0
    finally:
        if owns:
            conn.close()


def has_paid_product(
    user_id: str,
    product: str,
    conn: psycopg.Connection | None = None,
) -> bool:
    """True when the user has at least one paid purchase of ``product``."""
    owns = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM purchases "
            "WHERE user_id=%s AND product=%s AND status='paid' LIMIT 1",
            (user_id, product),
        ).fetchone()
        return row is not None
    finally:
        if owns:
            conn.close()


# ---------------------------------------------------------------------------
# Cost and quota queries over trace_log
# ---------------------------------------------------------------------------

def user_cost_usd(
    user_id: str,
    since: datetime | None = None,
    conn: psycopg.Connection | None = None,
) -> float:
    """Total LLM spend attributed to one user, in USD.

    Reads cost_usd out of the trace_log payload written by paperpilot.trace.
    Events with no cost_usd (start events, non-LLM steps) contribute zero.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM((payload->>'cost_usd')::numeric), 0) "
            "FROM trace_log "
            "WHERE user_id = %s AND (%s IS NULL OR ts >= %s)",
            (user_id, since, since),
        ).fetchone()
        return float(row[0]) if row else 0.0
    finally:
        if owns:
            conn.close()


def user_event_count(
    user_id: str,
    kind_prefix: str,
    since: datetime,
    conn: psycopg.Connection | None = None,
) -> int:
    """Count a user's trace events of a given kind since a timestamp.

    Quota enforcement counts completed work, so callers should pass the
    '.end' suffix in kind_prefix (e.g. 'evidence_dossier') and this matches
    kind LIKE '<prefix>%.end'.
    """
    owns = conn is None
    conn = conn or get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM trace_log "
            "WHERE user_id = %s AND kind LIKE %s AND ts >= %s",
            (user_id, f"{kind_prefix}%.end", since),
        ).fetchone()
        return int(row[0]) if row else 0
    finally:
        if owns:
            conn.close()
