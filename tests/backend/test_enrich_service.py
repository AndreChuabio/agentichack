"""Profile autofill proposes, it never writes, and it must stay countable.

Every source is stubbed out here: the point of these tests is the shape of the
result and the trace event the ENRICH quota counts, not whether any particular
vendor answered.
"""

from unittest.mock import patch

from backend import quotas
from backend.services import enrich_service
from paperpilot import trace


def test_every_source_failing_still_returns_a_result(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    monkeypatch.setattr(trace, "insert_trace", lambda *a, **k: None)
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_bio", return_value=""), \
         patch.object(enrich_service, "_propose", return_value={}):
        result = enrich_service.autofill(
            "u1",
            {"linkedin_url": "https://linkedin.com/in/x", "site_url": "https://x.dev"},
        )
    assert result.proposed == {}
    assert all(not s.ok for s in result.sources)
    assert any(s.source == "linkedin" for s in result.sources)


def test_linkedin_failure_is_named_not_hidden(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    monkeypatch.setattr(trace, "insert_trace", lambda *a, **k: None)
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_bio", return_value=""), \
         patch.object(enrich_service, "_propose", return_value={}):
        result = enrich_service.autofill("u1", {"linkedin_url": "https://linkedin.com/in/x"})
    linkedin = [s for s in result.sources if s.source == "linkedin"][0]
    assert not linkedin.ok
    assert linkedin.detail


def test_autofill_emits_a_countable_enrich_event(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str | None, str]] = []
    monkeypatch.setattr(
        trace, "insert_trace", lambda sid, uid, kind, payload: captured.append((uid, kind))
    )
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_bio", return_value=""), \
         patch.object(enrich_service, "_propose", return_value={}):
        enrich_service.autofill("22222222-2222-2222-2222-222222222222", {})
    ends = [c for c in captured if c[1] == "profile_enrich.end"]
    assert len(ends) == 1
    assert ends[0][0] == "22222222-2222-2222-2222-222222222222"
    assert ends[0][1].startswith(quotas.ENRICH.kind_prefix)


def test_autofill_never_writes_the_profile(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    monkeypatch.setattr(trace, "insert_trace", lambda *a, **k: None)
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_bio", return_value=""), \
         patch.object(enrich_service, "_propose", return_value={}), \
         patch.object(enrich_service, "upsert_profile") as writer:
        enrich_service.autofill("u1", {"site_url": "https://x.dev"})
    writer.assert_not_called()
