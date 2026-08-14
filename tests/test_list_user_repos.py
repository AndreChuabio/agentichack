"""Repo listing for the publish picker: ordering, owner parsing, and the cap."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from paperpilot.github_ingest import list_user_repos


def _repo(name, pushed, fork=False, stars=0):
    return SimpleNamespace(
        full_name=f"andre/{name}",
        html_url=f"https://github.com/andre/{name}",
        description="d",
        language="Python",
        stargazers_count=stars,
        pushed_at=datetime(2026, 1, pushed),
        fork=fork,
    )


def test_repos_sort_newest_first_with_forks_last():
    repos = [_repo("old", 1), _repo("forked", 9, fork=True), _repo("new", 5)]
    with patch("paperpilot.github_ingest._gh_client") as gh:
        gh.return_value.get_user.return_value.get_repos.return_value = repos
        result = list_user_repos("andre")
    assert [r.full_name.split("/")[1] for r in result] == ["new", "old", "forked"]


def test_owner_accepts_a_full_profile_url():
    with patch("paperpilot.github_ingest._gh_client") as gh:
        gh.return_value.get_user.return_value.get_repos.return_value = []
        list_user_repos("https://github.com/AndreChuabio")
        gh.return_value.get_user.assert_called_once_with("AndreChuabio")


def test_limit_is_honoured():
    repos = [_repo(f"r{i}", 1 + (i % 27)) for i in range(10)]
    with patch("paperpilot.github_ingest._gh_client") as gh:
        gh.return_value.get_user.return_value.get_repos.return_value = repos
        assert len(list_user_repos("andre", limit=3)) == 3


def test_a_repo_with_no_push_date_sorts_last_not_first():
    """An absent timestamp is not "newest".

    The first implementation inverted the timestamp characters arithmetically,
    so an empty string sorted ahead of every real date and a repo GitHub had no
    push date for appeared at the top of the picker as the user's latest work.
    """
    undated = _repo("undated", 1)
    undated.pushed_at = None
    repos = [undated, _repo("recent", 20), _repo("older", 2)]
    with patch("paperpilot.github_ingest._gh_client") as gh:
        gh.return_value.get_user.return_value.get_repos.return_value = repos
        result = list_user_repos("andre")
    assert [r.full_name.split("/")[1] for r in result] == ["recent", "older", "undated"]
