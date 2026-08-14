"""GitHub repo → concatenated text bundle for long-context LLM ingestion.

We grab the README, top-level structure, and a ranked sample of source files,
then cap the total at ~600K tokens so Gemini's 1M-context window has plenty
of headroom.

Auth: prefers GITHUB_TOKEN env var; falls back to `gh auth token` shell-out.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Iterable

from github import Auth, Github
from github.GithubException import GithubException
from github.Repository import Repository

import tiktoken

import os

# Generous ceiling so we always leave room for the prompt + the response.
DEFAULT_TOKEN_CAP = 600_000
# Hard cap on serial PyGithub per-file fetches. Even if the token budget
# allows more, demo latency suffers past ~30 files (each fetch is ~0.5-1s).
DEFAULT_MAX_FILES = 30

# Files we want to prioritise (highest signal for a research-paper summary).
PRIORITY_EXTENSIONS = (
    ".md",
    ".rst",
    ".txt",
    ".ipynb",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".rs",
    ".go",
    ".java",
    ".cpp",
    ".c",
    ".h",
    ".hpp",
    ".cu",
    ".sql",
    ".toml",
    ".yaml",
    ".yml",
)
SKIP_PATH_PARTS = (
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    ".pytest_cache",
    "site-packages",
    ".git",
)
SKIP_PATHS_EXACT = {"package-lock.json", "yarn.lock", "uv.lock", "poetry.lock"}


@dataclass
class RepoBundle:
    owner: str
    name: str
    description: str
    readme: str
    files: list[tuple[str, str]]
    file_count: int
    total_tokens: int


# The repo group must allow dots -- user.github.io pages and next.js-style
# names are real repos -- while still shedding a literal trailing ".git" and
# stopping at a path segment. The previous pattern excluded dots entirely,
# which truncated "andrechuabio.github.io" to "andrechuabio" and 404d.
_REPO_URL_RE = re.compile(
    r"github\.com[:/](?P<owner>[^/\s]+)/(?P<repo>[^/\s]+?)(?:\.git)?(?=[/\s]|$)"
)


def _parse_repo_url(url: str) -> tuple[str, str]:
    match = _REPO_URL_RE.search(url.strip())
    if not match:
        raise ValueError(f"Could not parse owner/repo from URL: {url}")
    return match.group("owner"), match.group("repo")


def _get_token() -> str:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError(
            "No GitHub token. Set GITHUB_TOKEN or run `gh auth login`."
        ) from exc


def _gh_client() -> Github:
    return Github(auth=Auth.Token(_get_token()))


_ENCODER = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_ENCODER.encode(text, disallowed_special=()))


def _walk_repo_files(repo: Repository) -> Iterable[tuple[str, int]]:
    """Yield (path, size) for every blob in the default branch."""
    tree = repo.get_git_tree(repo.default_branch, recursive=True)
    for entry in tree.tree:
        if entry.type != "blob":
            continue
        path = entry.path
        if any(part in path for part in SKIP_PATH_PARTS):
            continue
        if path in SKIP_PATHS_EXACT:
            continue
        size = entry.size or 0
        yield path, size


def _rank_files(files: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Sort so README-y / docs come first, then prioritised extensions by size."""

    def key(item: tuple[str, int]) -> tuple[int, int]:
        path, size = item
        name = path.lower()
        # Tier 0: top-level README / contributing / claims.md / etc.
        if "/" not in path and (
            name.startswith("readme") or name in {"contributing.md", "claims.md"}
        ):
            return (0, -size)
        # Tier 1: priority extensions.
        for i, ext in enumerate(PRIORITY_EXTENSIONS):
            if name.endswith(ext):
                return (1 + i, -size)
        # Tier 99: everything else, smallest first.
        return (99, size)

    return sorted(files, key=key)


def fetch_repo(
    url: str,
    token_cap: int = DEFAULT_TOKEN_CAP,
    max_files: int = DEFAULT_MAX_FILES,
) -> RepoBundle:
    """Pull a public/private repo and assemble a token-capped bundle."""
    owner, name = _parse_repo_url(url)
    gh = _gh_client()
    repo = gh.get_repo(f"{owner}/{name}")

    try:
        readme = repo.get_readme().decoded_content.decode("utf-8", errors="replace")
    except GithubException:
        readme = ""

    files_meta = list(_walk_repo_files(repo))
    files_meta = _rank_files(files_meta)

    used_tokens = count_tokens(readme)
    bundle_files: list[tuple[str, str]] = []

    for path, _size in files_meta:
        if used_tokens >= token_cap or len(bundle_files) >= max_files:
            break
        try:
            blob = repo.get_contents(path)
        except GithubException:
            continue
        try:
            body = blob.decoded_content.decode("utf-8", errors="replace")
        except (UnicodeDecodeError, AttributeError):
            continue
        # Trim each file to a sane size so one huge generated file can't dominate.
        max_per_file = min(40_000, token_cap - used_tokens)
        body_tokens = count_tokens(body)
        if body_tokens > max_per_file:
            # Truncate by characters proportionally — cheap and good enough.
            keep_chars = int(len(body) * (max_per_file / max(body_tokens, 1)))
            body = body[:keep_chars] + "\n... [truncated]"
            body_tokens = count_tokens(body)
        used_tokens += body_tokens
        bundle_files.append((path, body))

    return RepoBundle(
        owner=owner,
        name=name,
        description=repo.description or "",
        readme=readme,
        files=bundle_files,
        file_count=len(bundle_files),
        total_tokens=used_tokens,
    )


@dataclass(frozen=True)
class RepoSummary:
    """One repo as the picker shows it. Not the bundle -- just enough to choose."""

    full_name: str
    html_url: str
    description: str
    language: str
    stars: int
    pushed_at: str
    fork: bool


def _owner_login(owner: str) -> str:
    """The login out of a bare handle or a full profile URL."""
    text = owner.strip().rstrip("/")
    if "github.com" in text:
        return text.split("github.com/", 1)[1].split("/")[0]
    return text




def list_user_repos(owner: str, limit: int = 100) -> list[RepoSummary]:
    """A user's public repos, most recently pushed first and forks last.

    Forks sort last rather than being dropped: a fork can be the interesting
    work, and the user is the one picking. Accepts either a bare handle or the
    profile URL already stored on the Market profile, so the caller does not
    have to know which it has.
    """
    login = _owner_login(owner)
    if not login:
        raise ValueError("a GitHub owner or profile URL is required")
    gh = _gh_client()
    summaries = [
        RepoSummary(
            full_name=repo.full_name,
            html_url=repo.html_url,
            description=repo.description or "",
            language=repo.language or "",
            stars=int(repo.stargazers_count or 0),
            pushed_at=repo.pushed_at.isoformat() if repo.pushed_at else "",
            fork=bool(repo.fork),
        )
        for repo in gh.get_user(login).get_repos()
    ]
    # Two stable passes rather than one composite key: the date wants
    # descending and the fork flag ascending, which a single sort cannot
    # express. The previous attempt inverted the timestamp characters
    # arithmetically, which also sorted a repo with no push date -- an empty
    # string -- to the very top as though it were the newest thing the user
    # owned. Sorting descending puts the empty ones last, where they belong.
    summaries.sort(key=lambda r: r.pushed_at or "", reverse=True)
    summaries.sort(key=lambda r: r.fork)
    return summaries[:limit]


def render_bundle(bundle: RepoBundle) -> str:
    """Render the bundle into a single prompt-ready string."""
    parts = [
        f"# Repository: {bundle.owner}/{bundle.name}",
        f"Description: {bundle.description}",
        "",
        "## README",
        bundle.readme.strip() or "(no README found)",
        "",
        "## Files",
    ]
    for path, body in bundle.files:
        parts.append(f"\n### `{path}`\n```\n{body}\n```")
    return "\n".join(parts)
