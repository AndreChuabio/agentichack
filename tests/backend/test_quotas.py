"""Quotas are enforced in the backend, not the UI.

Track and the help assistant run on Merit's own API key, so both need a
server-side bound. Enforcement happens in FastAPI because the backend
connects to Supabase as service role and bypasses RLS -- a limit enforced
only in the Next.js client is enforced nowhere.

This file also proves the dossier quota is actually wired to a real emitted
trace event. The original plan gave DOSSIER a kind_prefix of
"evidence_dossier", but build_dossier never called trace.step, so no row was
ever written with that kind and the quota could never fire. The fix wraps
the dossier build in trace.step; the test below exercises the real
(unmocked) build_dossier + trace.step + user_event_count LIKE-pattern path
to prove a completed dossier build now produces a countable event.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import quotas
from backend.auth import AuthUser, get_current_user
from backend.main import app
from backend.services import evidence_service
from paperpilot import supabase_client, trace
from paperpilot.outreach.evidence import USCIS_O1A_CRITERIA, EvidenceItem

# ---------------------------------------------------------------------------
# backend.quotas: Quota dataclass + enforce() (from the task brief)
# ---------------------------------------------------------------------------


def test_under_quota_passes(monkeypatch):
    monkeypatch.setattr(quotas, "user_event_count", lambda *a, **k: 2)
    quotas.enforce("user-1", quotas.DOSSIER)  # 2 < 3, no raise


def test_at_quota_raises_429(monkeypatch):
    monkeypatch.setattr(quotas, "user_event_count", lambda *a, **k: 3)
    with pytest.raises(HTTPException) as exc:
        quotas.enforce("user-1", quotas.DOSSIER)
    assert exc.value.status_code == 429
    assert "3 per month" in exc.value.detail


def test_narrative_quota_is_monthly_thirty(monkeypatch):
    assert quotas.NARRATIVE.limit == 30
    assert quotas.NARRATIVE.window_days == 30


def test_assist_quota_is_daily_twenty(monkeypatch):
    assert quotas.ASSIST.limit == 20
    assert quotas.ASSIST.window_days == 1


def test_ledger_failure_fails_closed_with_retryable_503(monkeypatch):
    """An unreadable ledger must refuse, not over-serve.

    Every quota guards a Merit-funded surface, and the ledger becomes
    unreadable exactly at peak load -- failing open there disengages the
    cost control at the worst possible moment. Reading stored evidence is
    never quota-gated, so the caller keeps access to their own data.
    """

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(quotas, "user_event_count", boom)
    with pytest.raises(HTTPException) as exc_info:
        quotas.enforce("user-1", quotas.DOSSIER)
    assert exc_info.value.status_code == 503
    assert "try again" in exc_info.value.detail.lower()


# ---------------------------------------------------------------------------
# Quota kind_prefixes must match what the surfaces actually emit.
# ---------------------------------------------------------------------------


def test_dossier_quota_kind_prefix_is_evidence_dossier():
    assert quotas.DOSSIER.kind_prefix == "evidence_dossier"


def test_narrative_quota_kind_prefix_is_evidence_draft():
    assert quotas.NARRATIVE.kind_prefix == "evidence_draft"


def test_assist_quota_kind_prefix_is_assist():
    assert quotas.ASSIST.kind_prefix == "assist"


# ---------------------------------------------------------------------------
# The dossier quota must count a REAL emitted event, not zero.
#
# build_dossier never called trace.step in the original code, so no row was
# ever inserted with kind "evidence_dossier.end" and DOSSIER's quota could
# never trip. This drives the real (unmocked) build_dossier + trace.step +
# user_event_count LIKE-pattern logic end to end, with only the Supabase
# connection and the LLM call stubbed out.
# ---------------------------------------------------------------------------


class _FakeConn:
    def close(self):
        pass


def test_build_dossier_emits_a_countable_evidence_dossier_event(monkeypatch):
    user_id = "11111111-1111-1111-1111-111111111111"

    # No declared evidence for any criterion -> _draft_all_narratives short
    # circuits to "" per criterion without touching the LLM Gateway, so this
    # test exercises build_dossier's own trace.step wiring in isolation.
    empty_grouped = {k: [] for k, _ in USCIS_O1A_CRITERIA}

    monkeypatch.setattr(evidence_service.supabase_client, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        evidence_service, "evidence_by_criterion", lambda user_id, conn=None: empty_grouped
    )
    monkeypatch.setattr(
        evidence_service, "count_satisfied_criteria", lambda user_id, conn=None: 0
    )
    monkeypatch.setattr(
        evidence_service, "_find_user_profile_by_id", lambda user_id, conn=None: None
    )

    # Ledger must be "configured" for trace.log_event to reach insert_trace,
    # and insert_trace itself is stubbed to capture what would have been
    # written to trace_log without needing a live Postgres connection.
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str, str | None, str, dict]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, user_id, kind, payload: captured.append(
            (session_id, user_id, kind, payload)
        ),
    )

    pdf_bytes = evidence_service.build_dossier(user_id)

    assert pdf_bytes  # a real PDF was produced, not empty bytes

    end_events = [c for c in captured if c[2] == "evidence_dossier.end"]
    assert len(end_events) == 1, (
        "build_dossier must emit exactly one evidence_dossier.end trace "
        f"event; captured kinds were {[c[2] for c in captured]}"
    )
    _, event_user_id, _, _ = end_events[0]
    assert event_user_id == user_id, (
        "the trace_log row must carry the real user_id, not NULL, or "
        "user_event_count can never scope usage to this user"
    )

    # Prove user_event_count's LIKE pattern for the DOSSIER quota actually
    # matches the kind that was just emitted -- ties the instrumentation
    # directly to the quota that depends on it.
    like_pattern = f"{quotas.DOSSIER.kind_prefix}%.end"
    assert fnmatch.fnmatch("evidence_dossier.end", like_pattern.replace("%", "*"))


def test_user_event_count_counts_the_real_dossier_row(monkeypatch):
    """End-to-end proof that user_event_count(..., "evidence_dossier", ...)
    would return >= 1 against a trace_log row shaped like the one
    build_dossier now writes -- not the always-zero result from before the
    fix (kind_prefix "evidence_dossier" never matched "evidence_draft.*")."""
    user_id = "22222222-2222-2222-2222-222222222222"

    class FakeCursor:
        def fetchone(self):
            return (1,)

    class FakeConn:
        def execute(self, sql, params):
            assert params == (user_id, "evidence_dossier%.end", since)
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(supabase_client, "get_conn", lambda: FakeConn())
    since = datetime(2026, 1, 1)
    count = supabase_client.user_event_count(user_id, "evidence_dossier", since)
    assert count == 1


# ---------------------------------------------------------------------------
# The NARRATIVE quota must count a REAL emitted event too.
#
# The real Track UI client (web/lib/api.ts evidence.narrative) POSTs with no
# body, so backend.routers.evidence.draft_narrative resolves session_id=None
# and calls evidence_service.draft_criterion_narrative(session_id=None) --
# this is the actual production path, not a hypothetical. Before the fix,
# the fallback `f"evidence_draft_{user_id}"` was a plain string never
# registered with trace.new_session, so the emitted "evidence_draft.<crit>
# .end" row carried a NULL user_id and user_event_count(user_id, ...) could
# never see it: the 30/30-day narrative quota never fired. This drives the
# real (unmocked) draft_criterion_narrative + trace.step + user_event_count
# path end to end, with only the Supabase connection and the LLM call
# stubbed out.
# ---------------------------------------------------------------------------


class _FakeDelta:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)


class _FakeUsage:
    prompt_tokens = 10
    completion_tokens = 5


class _FakeStreamEvent:
    def __init__(self, content=None, usage=None):
        self.choices = [_FakeChoice(content)] if content is not None else []
        self.usage = usage


def _fake_stream():
    yield _FakeStreamEvent(content="On behalf of the beneficiary, ")
    yield _FakeStreamEvent(content="the evidence demonstrates...", usage=_FakeUsage())


class _FakeCompletions:
    def create(self, **kwargs):
        return _fake_stream()


class _FakeChat:
    completions = _FakeCompletions()


class _FakeLLMClient:
    chat = _FakeChat()


def test_draft_criterion_narrative_emits_a_countable_evidence_draft_event(monkeypatch):
    """This is the real Track UI path: web/lib/api.ts posts no body, so the
    route passes session_id=None straight into draft_criterion_narrative."""
    user_id = "33333333-3333-3333-3333-333333333333"
    criterion = USCIS_O1A_CRITERIA[0][0]

    monkeypatch.setattr(evidence_service.supabase_client, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        evidence_service, "list_evidence", lambda user_id, criterion=None, conn=None: []
    )
    monkeypatch.setattr(
        evidence_service, "_find_user_profile_by_id", lambda user_id, conn=None: None
    )
    monkeypatch.setattr(evidence_service, "get_client", lambda: _FakeLLMClient())

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str, str | None, str, dict]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, user_id, kind, payload: captured.append(
            (session_id, user_id, kind, payload)
        ),
    )

    narrative = evidence_service.draft_criterion_narrative(
        user_id=user_id, criterion=criterion, session_id=None
    )

    assert narrative  # the streamed text was actually assembled and returned

    end_events = [c for c in captured if c[2] == f"evidence_draft.{criterion}.end"]
    assert len(end_events) == 1, (
        "draft_criterion_narrative must emit exactly one "
        f"evidence_draft.{criterion}.end trace event; captured kinds were "
        f"{[c[2] for c in captured]}"
    )
    _, event_user_id, _, _ = end_events[0]
    assert event_user_id == user_id, (
        "the trace_log row must carry the real user_id, not NULL, or "
        "user_event_count can never scope narrative usage to this user -- "
        "this is the exact quota bypass a session_id=None caller hits on "
        "the real Track UI narrative path"
    )

    like_pattern = f"{quotas.NARRATIVE.kind_prefix}%.end"
    assert fnmatch.fnmatch(f"evidence_draft.{criterion}.end", like_pattern.replace("%", "*"))


# ---------------------------------------------------------------------------
# Quota bypass via caller-supplied session_id.
#
# backend/routers/evidence.py forwards NarrativeRequest.session_id /
# DossierRequest.session_id -- both Optional[str], caller-controlled -- into
# these services. Before the fix, `sid = session_id or trace.new_session(
# user_id)` only minted a user-bound session when session_id was empty. Any
# NON-EMPTY caller-supplied session_id was never registered via
# trace.new_session, so trace.log_event resolved no user binding for it and
# wrote the row with a NULL user_id. user_event_count only counts rows with a
# non-NULL user_id, so a client could send any non-empty session_id (e.g. a
# constant string) and draft unlimited narratives/dossiers on Merit's own
# API key forever. These tests drive the real (unmocked) service + trace.step
# + user_event_count path with a non-empty caller session_id, mirroring what
# a real client sends.
# ---------------------------------------------------------------------------


def test_draft_criterion_narrative_with_caller_session_id_is_still_countable(monkeypatch):
    """A non-empty, caller-supplied session_id must not defeat the NARRATIVE
    quota. This is the exact shape of the bypass: a client posts a body with
    its own session_id instead of leaving it empty."""
    user_id = "44444444-4444-4444-4444-444444444444"
    criterion = USCIS_O1A_CRITERIA[0][0]
    caller_session_id = "client-supplied-session-id"

    monkeypatch.setattr(evidence_service.supabase_client, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        evidence_service, "list_evidence", lambda user_id, criterion=None, conn=None: []
    )
    monkeypatch.setattr(
        evidence_service, "_find_user_profile_by_id", lambda user_id, conn=None: None
    )
    monkeypatch.setattr(evidence_service, "get_client", lambda: _FakeLLMClient())

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str, str | None, str, dict]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, user_id, kind, payload: captured.append(
            (session_id, user_id, kind, payload)
        ),
    )

    narrative = evidence_service.draft_criterion_narrative(
        user_id=user_id, criterion=criterion, session_id=caller_session_id
    )

    assert narrative

    end_events = [c for c in captured if c[2] == f"evidence_draft.{criterion}.end"]
    assert len(end_events) == 1, (
        "draft_criterion_narrative must emit exactly one "
        f"evidence_draft.{criterion}.end trace event; captured kinds were "
        f"{[c[2] for c in captured]}"
    )
    event_session_id, event_user_id, _, _ = end_events[0]
    assert event_session_id == caller_session_id, (
        "the caller's session_id must be preserved on the emitted row for "
        "correlation, not silently swapped for a different one"
    )
    assert event_user_id == user_id, (
        "a non-empty caller-supplied session_id must still be bound to the "
        "authenticated user_id -- otherwise the row is written with a NULL "
        "user_id and user_event_count(user_id, 'evidence_draft', since) "
        "never counts it, defeating the 30/month narrative quota"
    )


def test_build_dossier_with_caller_session_id_is_still_countable(monkeypatch):
    """A non-empty, caller-supplied session_id must not defeat the DOSSIER
    quota, and the internal per-criterion narrative calls threaded through
    build_dossier must stay bound to the same user without double-minting a
    second session id."""
    user_id = "55555555-5555-5555-5555-555555555555"
    caller_session_id = "client-supplied-dossier-session"
    criterion = USCIS_O1A_CRITERIA[0][0]

    item = EvidenceItem(
        id="ev-1",
        user_id=user_id,
        criterion=criterion,
        title="Award",
        description="desc",
        evidence_url="https://example.com",
        evidence_date=None,
        declared_at=datetime(2026, 1, 1),
        status="ready",
    )
    grouped = {k: ([item] if k == criterion else []) for k, _ in USCIS_O1A_CRITERIA}

    monkeypatch.setattr(evidence_service.supabase_client, "get_conn", lambda: _FakeConn())
    monkeypatch.setattr(
        evidence_service, "evidence_by_criterion", lambda user_id, conn=None: grouped
    )
    monkeypatch.setattr(
        evidence_service, "count_satisfied_criteria", lambda user_id, conn=None: 1
    )
    monkeypatch.setattr(
        evidence_service, "_find_user_profile_by_id", lambda user_id, conn=None: None
    )
    monkeypatch.setattr(
        evidence_service, "list_evidence", lambda user_id, criterion=None, conn=None: [item]
    )
    monkeypatch.setattr(evidence_service, "get_client", lambda: _FakeLLMClient())

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str, str | None, str, dict]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, user_id, kind, payload: captured.append(
            (session_id, user_id, kind, payload)
        ),
    )

    pdf_bytes = evidence_service.build_dossier(user_id, session_id=caller_session_id)

    assert pdf_bytes

    dossier_events = [c for c in captured if c[2] == "evidence_dossier.end"]
    assert len(dossier_events) == 1
    _, dossier_user_id, _, _ = dossier_events[0]
    assert dossier_user_id == user_id, (
        "evidence_dossier.end must carry the real user_id even when the "
        "caller supplied a non-empty session_id, or the 3/month dossier "
        "quota is defeated the same way as the narrative quota"
    )

    draft_events = [c for c in captured if c[2] == f"evidence_draft.{criterion}.end"]
    assert len(draft_events) == 1, (
        "build_dossier's internal _draft_all_narratives call must still "
        f"emit the per-criterion narrative event; captured kinds were "
        f"{[c[2] for c in captured]}"
    )
    _, draft_user_id, _, _ = draft_events[0]
    assert draft_user_id == user_id, (
        "the narrative call threaded internally by build_dossier must also "
        "carry the real user_id, not NULL"
    )

    # No double-mint: every row emitted by this one build_dossier call must
    # share the same session_id -- the sid computed once at the top of
    # build_dossier, threaded through _draft_all_narratives.
    session_ids = {c[0] for c in captured}
    assert session_ids == {caller_session_id}, (
        f"build_dossier must thread a single bound session id throughout, "
        f"not mint a second one; saw session ids {session_ids}"
    )


# ---------------------------------------------------------------------------
# Routes must call quotas.enforce() before doing any work.
# ---------------------------------------------------------------------------

_USER = AuthUser(id="00000000-0000-0000-0000-000000000099", email="clown@example.com")


def _quota_exceeded(*_a, **_k):
    raise HTTPException(status_code=429, detail="quota exceeded")


def test_dossier_route_blocks_at_quota(monkeypatch):
    monkeypatch.setattr(quotas, "enforce", _quota_exceeded)
    monkeypatch.setattr(
        evidence_service,
        "build_dossier",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("build_dossier must not run once the quota is exceeded")
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            resp = client.post("/dossier")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 429


# ---------------------------------------------------------------------------
# The paid dossier: entitlement is checked before the quota, and which quota
# applies depends on who is paying for the call.
#
# The original order ran the free 3-per-30-days cap first, so a customer who
# had paid $99 and regenerated a fourth time was told they had exhausted a cap
# that exists to bound Merit's API spend -- on a surface they were funding
# themselves. And has_entitlement had no error handling, so a Supabase blip
# surfaced as a bare 500 on the download somebody had just paid for.
# ---------------------------------------------------------------------------


def _paid_dossier_route(monkeypatch, *, entitled: bool, lookup_raises: bool = False):
    """Wire the dossier route with billing live and a stubbed ledger."""
    from paperpilot import supabase_client as sc

    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_live_123")

    def has_paid_product(user_id, product, conn=None):
        if lookup_raises:
            raise RuntimeError("supabase down")
        return entitled

    monkeypatch.setattr(sc, "has_paid_product", has_paid_product)
    monkeypatch.setattr(
        evidence_service, "build_dossier", lambda *a, **k: b"%PDF-1.4 fake"
    )
    monkeypatch.setattr(evidence_service, "dossier_filename", lambda user_id: "d.pdf")

    seen: list = []
    monkeypatch.setattr(quotas, "enforce", lambda user_id, quota: seen.append(quota))
    return seen


def _post_dossier():
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            return client.post("/dossier")
    finally:
        app.dependency_overrides.clear()


def test_unpaid_caller_gets_402_and_the_quota_is_never_consulted(monkeypatch):
    seen = _paid_dossier_route(monkeypatch, entitled=False)
    resp = _post_dossier()
    assert resp.status_code == 402
    assert seen == [], "an unpaid caller must not burn a quota slot"


def test_paying_caller_gets_the_abuse_ceiling_not_the_free_cap(monkeypatch):
    seen = _paid_dossier_route(monkeypatch, entitled=True)
    resp = _post_dossier()
    assert resp.status_code == 200
    assert seen == [quotas.DOSSIER_PAID], (
        "a customer who paid $99 must not hit the 3-per-month cap that exists "
        "to bound Merit's own API spend"
    )
    assert quotas.DOSSIER_PAID.limit == 30


def test_free_dossier_keeps_the_merit_cost_cap_while_the_paywall_is_dark(monkeypatch):
    """No price configured means Merit is still paying, so the free cap stands.

    has_entitlement returns True for everyone when billing is disabled, so
    gating the higher ceiling on entitlement alone would silently remove the
    cost cap the moment the paywall shipped dark.
    """
    monkeypatch.delenv("STRIPE_PRICE_DOSSIER", raising=False)
    monkeypatch.setattr(
        evidence_service, "build_dossier", lambda *a, **k: b"%PDF-1.4 fake"
    )
    monkeypatch.setattr(evidence_service, "dossier_filename", lambda user_id: "d.pdf")
    seen: list = []
    monkeypatch.setattr(quotas, "enforce", lambda user_id, quota: seen.append(quota))

    resp = _post_dossier()

    assert resp.status_code == 200
    assert seen == [quotas.DOSSIER]


def test_entitlement_lookup_failure_is_a_clear_503_not_a_bare_500(monkeypatch):
    _paid_dossier_route(monkeypatch, entitled=True, lookup_raises=True)
    resp = _post_dossier()
    assert resp.status_code == 503
    assert "verify your purchase" in resp.json()["detail"]


def test_narrative_route_blocks_at_quota(monkeypatch):
    monkeypatch.setattr(quotas, "enforce", _quota_exceeded)
    monkeypatch.setattr(
        evidence_service,
        "draft_criterion_narrative",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("draft_criterion_narrative must not run once the quota is exceeded")
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            resp = client.post("/evidence/awards/narrative")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 429


def test_assist_route_blocks_at_quota(monkeypatch):
    from backend.routers import assist as assist_router

    monkeypatch.setattr(quotas, "enforce", _quota_exceeded)
    # assist.py imports assist_answer by name (`from ... import assist_answer`),
    # so the reference to patch is the router module's, not assist_service's.
    monkeypatch.setattr(
        assist_router,
        "assist_answer",
        lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("assist_answer must not run once the quota is exceeded")
        ),
    )
    app.dependency_overrides[get_current_user] = lambda: _USER
    try:
        with TestClient(app) as client:
            resp = client.post("/assist", json={"question": "how do I win an O-1A?"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 429
