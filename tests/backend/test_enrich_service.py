"""Profile autofill proposes, it never writes, and it must stay countable.

Every source is stubbed out here: the point of these tests is the shape of the
result and the trace event the ENRICH quota counts, not whether any particular
vendor answered.
"""

from unittest.mock import patch

from backend import quotas
from backend.services import enrich_service
from paperpilot import trace


def _dead() -> enrich_service._Fetched:
    """A source that could not be read at all, as opposed to one that was
    read and had nothing to say. The two must never collapse."""
    return enrich_service._Fetched("", False, "GitHub could not be read: stubbed")


def test_every_source_failing_still_returns_a_result(monkeypatch):
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    monkeypatch.setattr(trace, "insert_trace", lambda *a, **k: None)
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_material", return_value=_dead()), \
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
         patch.object(enrich_service, "_github_material", return_value=_dead()), \
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
         patch.object(enrich_service, "_github_material", return_value=_dead()), \
         patch.object(enrich_service, "_propose", return_value={}):
        enrich_service.autofill("22222222-2222-2222-2222-222222222222", {})
    ends = [c for c in captured if c[1] == "profile_enrich.end"]
    assert len(ends) == 1
    assert ends[0][0] == "22222222-2222-2222-2222-222222222222"
    assert ends[0][1].startswith(quotas.ENRICH.kind_prefix)


def test_autofill_never_writes_the_profile(monkeypatch):
    """Patch the writer where it actually lives, not a local alias.

    This previously patched enrich_service.upsert_profile -- a symbol imported
    into that module for no reason but this assertion. It would have kept
    passing if autofill started writing through market_service directly, which
    is the only way it realistically would. Patching the real function means the
    test fails if any write path appears.
    """
    from backend.services import market_service

    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    monkeypatch.setattr(trace, "insert_trace", lambda *a, **k: None)
    with patch.object(enrich_service.nimble_client, "extract", return_value=None), \
         patch.object(enrich_service, "_github_material", return_value=_dead()), \
         patch.object(enrich_service, "_propose", return_value={}), \
         patch.object(market_service, "upsert_profile") as writer:
        enrich_service.autofill("u1", {"site_url": "https://x.dev"})
    writer.assert_not_called()
    assert not hasattr(enrich_service, "upsert_profile"), (
        "the module that must never write should not import a writer at all"
    )


def test_github_failure_is_reported_as_a_failure_not_as_an_empty_account():
    """A dead token and an empty account must not read the same to the user."""
    with patch.object(enrich_service, "_gh_client", side_effect=RuntimeError("401")):
        fetched = enrich_service._github_material("https://github.com/andre")
    assert not fetched.ok
    assert "could not be read" in fetched.detail


def test_github_material_includes_the_repos_not_just_the_bio():
    """The repo list is the substantive half; a bio alone proposes generic copy."""
    from types import SimpleNamespace

    user = SimpleNamespace(name="Andre Chuabio", bio="AI engineer")
    repo = SimpleNamespace(
        full_name="andre/mediguard",
        html_url="https://github.com/andre/mediguard",
        description="HIPAA-compliant DLP layer",
        language="Python",
        stars=3,
        pushed_at="2026-01-01",
        fork=False,
    )
    with patch.object(enrich_service, "_gh_client") as gh, \
         patch.object(enrich_service, "list_user_repos", return_value=[repo]):
        gh.return_value.get_user.return_value = user
        fetched = enrich_service._github_material("https://github.com/andre")
    assert fetched.ok
    assert "mediguard" in fetched.text
    assert "HIPAA-compliant DLP layer" in fetched.text
