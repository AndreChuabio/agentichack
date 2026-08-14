"""Regression tests for _parse_repo_url.

The production incident: a repo named andrechuabio.github.io was truncated to
"andrechuabio" because the repo group excluded dots, so the site build and
ingest 404d on a repo that plainly exists.
"""

from __future__ import annotations

import pytest

from paperpilot.github_ingest import _parse_repo_url


@pytest.mark.parametrize(
    ("url", "owner", "repo"),
    [
        (
            "https://github.com/AndreChuabio/andrechuabio.github.io",
            "AndreChuabio",
            "andrechuabio.github.io",
        ),
        ("https://github.com/AndreChuabio/MeritAI", "AndreChuabio", "MeritAI"),
        ("https://github.com/AndreChuabio/MeritAI.git", "AndreChuabio", "MeritAI"),
        ("git@github.com:vercel/next.js.git", "vercel", "next.js"),
        ("https://github.com/owner/repo/tree/main", "owner", "repo"),
        ("https://github.com/owner/repo/", "owner", "repo"),
        ("  https://github.com/owner/repo  ", "owner", "repo"),
    ],
)
def test_parse_repo_url(url: str, owner: str, repo: str) -> None:
    assert _parse_repo_url(url) == (owner, repo)


def test_parse_repo_url_rejects_non_github() -> None:
    with pytest.raises(ValueError):
        _parse_repo_url("https://gitlab.com/owner/repo")
