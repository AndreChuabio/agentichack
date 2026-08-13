from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.services import site_service
from backend import quotas
from paperpilot import trace
from paperpilot.site_models import SitePack, Theme


def _evidence(item_id: str, title: str = "Award") -> SimpleNamespace:
    """One evidence row. A plain namespace, not a MagicMock: MagicMock treats
    ``name`` specially and would silently hand the code a mock where a string
    is expected."""
    return SimpleNamespace(
        id=item_id,
        criterion="awards",
        title=title,
        description="desc",
        evidence_url="https://example.com",
        evidence_date=None,
    )


def _profile() -> SimpleNamespace:
    return SimpleNamespace(
        name="Andre Chuabio",
        title="AI Engineer",
        about="Builder",
        voice_tone="warm",
        github_url="",
        linkedin_url="",
        scholar_url="",
        site_url="",
    )


def _patches(evidence_rows, pack=None, bundle_side_effect=None):
    pack = pack or SitePack(name="Andre Chuabio")
    return (
        patch.object(site_service, "get_profile", return_value=_profile()),
        patch.object(site_service, "list_evidence", return_value=evidence_rows),
        patch.object(site_service, "build_pack", return_value=pack),
        patch.object(
            site_service,
            "fetch_repo_bundle",
            side_effect=bundle_side_effect or (lambda url: "bundle"),
        ),
        patch.object(site_service.supabase_client, "insert_artifact", return_value=None),
    )


def test_evidence_not_owned_by_caller_is_rejected():
    p1, p2, p3, p4, p5 = _patches([_evidence("owned-1")])
    with p1, p2, p3, p4, p5, pytest.raises(HTTPException) as exc:
        site_service.build_site(
            user_id="u1", repo_urls=[], evidence_ids=["someone-elses-id"]
        )
    assert exc.value.status_code == 403


def test_only_requested_evidence_reaches_the_pack():
    rows = [_evidence("a", "Kept"), _evidence("b", "Not requested")]
    captured = {}

    def _capture(**kwargs):
        captured.update(kwargs)
        return SitePack(name="Andre")

    p1, p2, _, p4, p5 = _patches(rows)
    with p1, p2, p4, p5, patch.object(site_service, "build_pack", side_effect=_capture):
        site_service.build_site(user_id="u1", repo_urls=[], evidence_ids=["a"])
    titles = [item["title"] for item in captured["evidence"]]
    assert titles == ["Kept"]


def test_unreachable_repo_is_skipped_not_fatal():
    def _boom(url: str) -> str:
        if "bad" in url:
            raise RuntimeError("404 from GitHub")
        return "bundle"

    p1, p2, p3, p4, p5 = _patches([], bundle_side_effect=_boom)
    with p1, p2, p3, p4, p5:
        result = site_service.build_site(
            user_id="u1",
            repo_urls=["https://github.com/x/good", "https://github.com/x/bad"],
            evidence_ids=[],
        )
    assert len(result.skipped) == 1
    assert "bad" in result.skipped[0]["repo_url"]
    assert result.zip_bytes


def test_single_repo_with_session_reuses_the_cached_bundle():
    p1, p2, p3, p4, p5 = _patches([])
    with p1, p2, p3, p4, p5, patch.object(
        site_service, "_check_session_ownership", return_value=None
    ), patch.object(site_service, "_load_bundle", return_value="cached") as loader:
        site_service.build_site(
            user_id="u1",
            repo_urls=["https://github.com/x/good"],
            evidence_ids=[],
            session_id="s1",
        )
    loader.assert_called_once()


def test_multi_repo_never_reuses_the_session_bundle():
    p1, p2, p3, p4, p5 = _patches([])
    with p1, p2, p3, p4, p5, patch.object(
        site_service, "_check_session_ownership", return_value=None
    ), patch.object(site_service, "_load_bundle") as loader:
        site_service.build_site(
            user_id="u1",
            repo_urls=["https://github.com/x/a", "https://github.com/x/b"],
            evidence_ids=[],
            session_id="s1",
        )
    loader.assert_not_called()


def test_persistence_failure_does_not_block_the_download():
    p1, p2, p3, p4, _ = _patches([])
    with p1, p2, p3, p4, patch.object(
        site_service.supabase_client, "insert_artifact", side_effect=RuntimeError("db down")
    ):
        result = site_service.build_site(user_id="u1", repo_urls=[], evidence_ids=[])
    assert result.zip_bytes


# ---------------------------------------------------------------------------
# Regression: the SITE quota counts trace_log rows whose kind LIKE
# 'site_build%.end' AND whose user_id is the caller. A build that emitted only
# 'site.extract.end', or that emitted rows against an unbound session (so
# trace_log.user_id is NULL), leaves nothing the quota can ever count -- the
# 5-per-30-days cap on a free surface that spends an LLM call plus a GitHub
# fetch per repo then reads zero forever and never trips. This is the same bug
# already fixed once for the dossier; see the sibling regression test at
# tests/backend/test_quotas.py.
# ---------------------------------------------------------------------------


def test_build_site_emits_a_countable_site_build_event(monkeypatch):
    user_id = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str | None, str]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, uid, kind, payload: captured.append((uid, kind)),
    )

    p1, p2, p3, p4, p5 = _patches([])
    with p1, p2, p3, p4, p5:
        site_service.build_site(user_id=user_id, repo_urls=[], evidence_ids=[])

    ends = [c for c in captured if c[1] == "site_build.end"]
    assert len(ends) == 1, f"kinds captured were {[c[1] for c in captured]}"

    # The row must carry the caller, or the quota's WHERE user_id = %s skips it.
    assert ends[0][0] == user_id

    # And the kind must satisfy the LIKE pattern the quota actually uses.
    assert ends[0][1].startswith(quotas.SITE.kind_prefix)
    assert ends[0][1].endswith(".end")


def test_caller_supplied_session_still_binds_to_the_caller(monkeypatch):
    """A client-chosen session_id must not write NULL-user rows.

    An unregistered session resolves to no user at log time, which is exactly
    how a non-empty caller-supplied session_id used to bypass a quota forever.
    """
    user_id = "33333333-3333-3333-3333-333333333333"
    monkeypatch.setenv("SUPABASE_DB_URL", "postgresql://stub")
    captured: list[tuple[str | None, str]] = []
    monkeypatch.setattr(
        trace,
        "insert_trace",
        lambda session_id, uid, kind, payload: captured.append((uid, kind)),
    )

    p1, p2, p3, p4, p5 = _patches([])
    with p1, p2, p3, p4, p5, patch.object(
        site_service, "_check_session_ownership", return_value=None
    ):
        site_service.build_site(
            user_id=user_id,
            repo_urls=[],
            evidence_ids=[],
            session_id="client-chosen-id",
        )

    ends = [c for c in captured if c[1] == "site_build.end"]
    assert ends, f"kinds captured were {[c[1] for c in captured]}"
    assert ends[0][0] == user_id


def test_theme_reported_is_the_one_actually_rendered():
    """The response must name what was rendered, not what the model asked for."""
    pack = SitePack(name="Andre", theme=Theme(palette="neon", layout="zigzag"))
    p1, p2, p3, p4, p5 = _patches([], pack=pack)
    with p1, p2, p3, p4, p5:
        result = site_service.build_site(user_id="u1", repo_urls=[], evidence_ids=[])
    assert result.theme == {"palette": "slate", "layout": "stack"}
