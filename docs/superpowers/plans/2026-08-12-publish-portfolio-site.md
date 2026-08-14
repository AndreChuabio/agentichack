# Publish Portfolio Site Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Publish surface that turns a user's Merit profile, selected GitHub repos, and explicitly selected O-1A evidence into a downloadable static portfolio site they push to their own `<user>.github.io` repo.

**Architecture:** Mirrors the existing Productize pipeline. One LLM call fills a `SitePack`; a pure templating module turns that into a zip. The model writes prose and picks a palette and layout from two enums; it never emits markup. Every interpolated value is HTML-escaped at the render boundary.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, psycopg, pytest, Next.js App Router, TypeScript, Tailwind, Playwright.

## Global Constraints

- No emojis and no exclamation marks in code, comments, docstrings, or commit messages.
- Never credit Claude or any AI tool in commit messages or code comments.
- TypeScript: no `any`. Declare explicit interfaces.
- Python: PEP8, docstrings on every public function, imports at top of file.
- Every value interpolated into HTML goes through `html.escape(..., quote=True)`. No raw passthrough anywhere.
- `site_render.py` makes no LLM calls and performs no I/O beyond building an in-memory zip.
- The build includes exactly the `evidence_ids` in the request. Never read `metadata.publish` to decide inclusion.
- Existing `DOSSIER` entitlement and quota behaviour must remain byte-identical.
- Run `pytest` from the repo root. Commit after every task.

---

### Task 1: Site models and safety helpers

**Files:**
- Create: `paperpilot/site_models.py`
- Test: `tests/test_site_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Palette`, `Layout`, `DEFAULT_PALETTE`, `DEFAULT_LAYOUT`, `resolve_palette(value: str) -> Palette`, `resolve_layout(value: str) -> Layout`, `safe_href(value: str) -> str`, `site_slug(name: str) -> str`, and the Pydantic models `Theme`, `Project`, `EvidenceBlock`, `Links`, `SitePack`.

These models live in their own module rather than inside `site_extract.py` (where `skill_extract.py` keeps `PluginPack`) because both `site_extract` and `site_render` consume them, and a shared module keeps the dependency arrow from pointing sideways.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_site_models.py
from paperpilot.site_models import (
    DEFAULT_LAYOUT,
    DEFAULT_PALETTE,
    Layout,
    Palette,
    SitePack,
    resolve_layout,
    resolve_palette,
    safe_href,
    site_slug,
)


def test_resolve_palette_accepts_known_name():
    assert resolve_palette("ember") is Palette.EMBER


def test_resolve_palette_falls_back_on_invented_name():
    assert resolve_palette("chartreuse-dream") is DEFAULT_PALETTE


def test_resolve_layout_falls_back_on_invented_name():
    assert resolve_layout("") is DEFAULT_LAYOUT
    assert resolve_layout("grid") is Layout.GRID


def test_safe_href_allows_http_and_https():
    assert safe_href("https://github.com/AndreChuabio") == "https://github.com/AndreChuabio"
    assert safe_href("http://example.com") == "http://example.com"


def test_safe_href_rejects_script_schemes():
    assert safe_href("javascript:alert(1)") == ""
    assert safe_href("data:text/html,<script>") == ""
    assert safe_href("  JavaScript:alert(1)") == ""


def test_site_slug_is_one_safe_segment():
    assert site_slug("Andre Chuabio") == "andre-chuabio"
    assert site_slug("!!!") == "portfolio"
    assert site_slug("") == "portfolio"


def test_sitepack_defaults_are_empty_and_valid():
    pack = SitePack()
    assert pack.projects == []
    assert pack.evidence == []
    assert resolve_palette(pack.theme.palette) is DEFAULT_PALETTE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperpilot.site_models'`

- [ ] **Step 3: Write the implementation**

```python
# paperpilot/site_models.py
"""Shared models for the Publish portfolio site generator.

Both site_extract (which fills a SitePack from one LLM call) and site_render
(which turns one into a zip) consume these, so they live apart from either
rather than one importing the other's internals.

Every helper here is a pure function of its argument, and the two resolve_*
helpers never raise: a model that invents a palette name costs the default
theme rather than the build.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field


class Palette(StrEnum):
    """The colour schemes site_render knows how to emit CSS for."""

    SLATE = "slate"
    INK = "ink"
    MOSS = "moss"
    EMBER = "ember"


class Layout(StrEnum):
    """How the project cards are arranged."""

    STACK = "stack"
    SPLIT = "split"
    GRID = "grid"


DEFAULT_PALETTE = Palette.SLATE
DEFAULT_LAYOUT = Layout.STACK

_SLUG_UNSAFE = re.compile(r"[^a-z0-9]+")
_SAFE_SCHEMES = ("http://", "https://")


def resolve_palette(value: str) -> Palette:
    """The named palette, or the default when the name is not one we render."""
    try:
        return Palette(str(value).strip().lower())
    except ValueError:
        return DEFAULT_PALETTE


def resolve_layout(value: str) -> Layout:
    """The named layout, or the default when the name is not one we render."""
    try:
        return Layout(str(value).strip().lower())
    except ValueError:
        return DEFAULT_LAYOUT


def safe_href(value: str) -> str:
    """The URL when it is http(s), else the empty string.

    This is the line that stops a ``javascript:`` payload pasted into a profile
    URL field from becoming an href on a page the user publishes under their
    own name. Callers treat an empty result as "render no link".
    """
    url = str(value).strip()
    return url if url.lower().startswith(_SAFE_SCHEMES) else ""


def site_slug(name: str) -> str:
    """One safe path segment for the zip root, never empty and never a dot."""
    slug = _SLUG_UNSAFE.sub("-", str(name).lower()).strip("-")
    return slug or "portfolio"


class Theme(BaseModel):
    """What the model asked for. Resolved through resolve_* before rendering."""

    palette: str = DEFAULT_PALETTE.value
    layout: str = DEFAULT_LAYOUT.value


class Project(BaseModel):
    """One repo rendered as a project card."""

    title: str = ""
    repo_url: str = ""
    blurb: str = ""
    tech: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)


class EvidenceBlock(BaseModel):
    """One O-1A evidence row the user explicitly chose to publish."""

    criterion: str = ""
    title: str = ""
    blurb: str = ""
    url: str = ""
    date: str = ""


class Links(BaseModel):
    """The profile's outbound links. Each is validated by safe_href at render."""

    github: str = ""
    linkedin: str = ""
    scholar: str = ""
    site: str = ""


class SitePack(BaseModel):
    """Everything one generated site is rendered from.

    Every field defaults to empty so a model that omits a section produces a
    thinner site rather than a validation error that costs the whole build.
    """

    name: str = ""
    title: str = ""
    tagline: str = ""
    about: list[str] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    evidence: list[EvidenceBlock] = Field(default_factory=list)
    links: Links = Field(default_factory=Links)
    theme: Theme = Field(default_factory=Theme)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_models.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add paperpilot/site_models.py tests/test_site_models.py
git commit -m "feat(publish): site models, theme enums, and URL safety helpers"
```

---

### Task 2: Entitlements per-product and the site quota

**Files:**
- Modify: `backend/entitlements.py`
- Modify: `backend/quotas.py`
- Test: `tests/backend/test_entitlements_products.py`

**Interfaces:**
- Consumes: nothing
- Produces: `entitlements.PORTFOLIO = "portfolio"`, `entitlements.billing_enabled(product: str = DOSSIER) -> bool`, `entitlements.has_entitlement(user_id: str, product: str) -> bool` (signature unchanged), `quotas.SITE` (a `Quota`).

`billing_enabled()` currently reads only `STRIPE_PRICE_DOSSIER`, so it means "is the dossier paywalled" rather than "is this product paywalled". The default argument keeps every existing call site working unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_entitlements_products.py
import backend.entitlements as ent
from backend import quotas


def test_dossier_billing_still_reads_its_own_env(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_DOSSIER", raising=False)
    assert ent.billing_enabled() is False
    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_123")
    assert ent.billing_enabled() is True


def test_portfolio_bills_independently_of_dossier(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_DOSSIER", "price_123")
    monkeypatch.delenv("STRIPE_PRICE_PORTFOLIO", raising=False)
    assert ent.billing_enabled(ent.PORTFOLIO) is False


def test_portfolio_is_free_while_its_price_is_unset(monkeypatch):
    monkeypatch.delenv("STRIPE_PRICE_PORTFOLIO", raising=False)
    assert ent.has_entitlement("any-user-id", ent.PORTFOLIO) is True


def test_site_quota_is_five_per_thirty_days():
    assert quotas.SITE.limit == 5
    assert quotas.SITE.window_days == 30
    assert quotas.SITE.kind_prefix == "site_build"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_entitlements_products.py -v`
Expected: FAIL with `AttributeError: module 'backend.entitlements' has no attribute 'PORTFOLIO'`

- [ ] **Step 3: Modify `backend/entitlements.py`**

Replace the `DOSSIER = "dossier"` line and the `billing_enabled` / `has_entitlement` functions with:

```python
# Product keys. Keep in sync with the Stripe products and the purchases.product column.
DOSSIER = "dossier"
PORTFOLIO = "portfolio"


def _price_env(product: str) -> str:
    """The env var naming this product's Stripe price."""
    return f"STRIPE_PRICE_{product.upper()}"


def billing_enabled(product: str = DOSSIER) -> bool:
    """True when a Stripe price is configured for ``product``.

    When unset that product stays free, so a paywall can ship dark and be
    switched on later just by setting the env var. No redeploy of a different
    code path is needed. Per-product rather than global so a second product can
    ship dark while the first is already charging; the default keeps every
    existing dossier call site unchanged.
    """
    return bool(os.environ.get(_price_env(product)))


def has_entitlement(user_id: str, product: str) -> bool:
    """True when the user may access ``product``.

    Free (True) whenever billing is disabled for that product; otherwise
    requires a paid purchase.
    """
    if not billing_enabled(product):
        return True
    return supabase_client.has_paid_product(user_id, product)
```

- [ ] **Step 4: Modify `backend/quotas.py`**

Add below the existing `ASSIST` line:

```python
SITE = Quota(kind_prefix="site_build", limit=5, window_days=30, noun="portfolio site build")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/backend/test_entitlements_products.py tests/backend/test_quotas.py -v`
Expected: PASS, including the pre-existing quota tests

- [ ] **Step 6: Commit**

```bash
git add backend/entitlements.py backend/quotas.py tests/backend/test_entitlements_products.py
git commit -m "feat(publish): per-product billing checks and the site build quota"
```

---

### Task 3: Site renderer

**Files:**
- Create: `paperpilot/site_render.py`
- Test: `tests/test_site_render.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces: `render_style_css(palette: Palette) -> str`, `render_main_js() -> str`, `render_index_html(pack: SitePack, *, inline_css: bool = False) -> str`, `render_site_readme(pack: SitePack) -> str`, `build_site_zip(pack: SitePack) -> bytes`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_site_render.py
import io
import zipfile

import pytest

from paperpilot.site_models import EvidenceBlock, Links, Project, SitePack, Theme
from paperpilot.site_render import (
    build_site_zip,
    render_index_html,
    render_site_readme,
)


def _pack() -> SitePack:
    return SitePack(
        name="Andre Chuabio",
        title="AI Engineer",
        tagline="Health tech and quant infra.",
        about=["I build AI products.", "Health tech is my other obsession."],
        projects=[
            Project(
                title="MediGuard",
                repo_url="https://github.com/AndreChuabio/mediguard",
                blurb="HIPAA-compliant DLP layer for LLMs.",
                tech=["Python", "FastAPI"],
                highlights=["Live on PyPI"],
            )
        ],
        evidence=[
            EvidenceBlock(
                criterion="awards",
                title="Hackathon winner",
                blurb="First place.",
                url="https://example.com/award",
                date="2026-03-01",
            )
        ],
        links=Links(github="https://github.com/AndreChuabio"),
        theme=Theme(palette="ember", layout="grid"),
    )


def test_zip_contains_exactly_the_four_site_files():
    data = build_site_zip(_pack())
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = sorted(zf.namelist())
    assert names == [
        "andre-chuabio/README.md",
        "andre-chuabio/index.html",
        "andre-chuabio/main.js",
        "andre-chuabio/style.css",
    ]


def test_index_renders_content_and_merit_footer():
    html = render_index_html(_pack())
    assert "Andre Chuabio" in html
    assert "MediGuard" in html
    assert "Hackathon winner" in html
    assert 'href="https://meritai.me"' in html


@pytest.mark.parametrize(
    "hostile",
    ['<script>alert(1)</script>', '" onload="alert(1)', "</title><script>x</script>"],
)
def test_hostile_text_is_escaped_not_executed(hostile):
    html = render_index_html(SitePack(name=hostile, about=[hostile]))
    assert "<script>" not in html
    assert ' onload="' not in html
    assert "&lt;" in html or "&quot;" in html


def test_javascript_url_never_becomes_an_href():
    pack = SitePack(
        name="X",
        links=Links(github="javascript:alert(1)"),
        projects=[Project(title="P", repo_url="javascript:alert(1)")],
    )
    html = render_index_html(pack)
    assert "javascript:" not in html.lower()


def test_unknown_theme_falls_back_rather_than_raising():
    pack = SitePack(name="X", theme=Theme(palette="nope", layout="nope"))
    html = render_index_html(pack)
    assert "<h1>X</h1>" in html


def test_preview_and_zip_share_a_body():
    pack = _pack()
    preview = render_index_html(pack, inline_css=True)
    with zipfile.ZipFile(io.BytesIO(build_site_zip(pack))) as zf:
        shipped = zf.read("andre-chuabio/index.html").decode()
    assert preview.split("<body>", 1)[1] == shipped.split("<body>", 1)[1]
    assert "<style>" in preview
    assert '<link rel="stylesheet"' in shipped


def test_readme_warns_about_permanence():
    readme = render_site_readme(_pack())
    assert "world-readable" in readme
    assert "git push" in readme
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_render.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperpilot.site_render'`

- [ ] **Step 3: Write the implementation**

```python
# paperpilot/site_render.py
"""Render a SitePack into a static portfolio site zip.

  <slug>/
    index.html
    style.css
    main.js
    README.md

No LLM calls. Pure templating -- the same posture skill_render.py takes, for a
sharper reason: every value interpolated here came from a model, a profile
field, or a repo README, and this module is the single boundary where any of it
becomes markup. Everything goes through html.escape(quote=True) and nothing is
ever passed through raw, so the model can write prose and pick two enum values
and can never write a tag.
"""

from __future__ import annotations

import html
import io
import zipfile

from paperpilot.site_models import (
    Palette,
    SitePack,
    resolve_layout,
    resolve_palette,
    safe_href,
    site_slug,
)

_PALETTE_CSS: dict[Palette, dict[str, str]] = {
    Palette.SLATE: {
        "bg": "#f8fafc", "fg": "#0f172a", "accent": "#4f46e5",
        "muted": "#64748b", "card": "#ffffff",
    },
    Palette.INK: {
        "bg": "#0b0f19", "fg": "#e6edf7", "accent": "#7c9cff",
        "muted": "#94a3b8", "card": "#131a2a",
    },
    Palette.MOSS: {
        "bg": "#f6f8f4", "fg": "#14241a", "accent": "#2f7d55",
        "muted": "#5b6b60", "card": "#ffffff",
    },
    Palette.EMBER: {
        "bg": "#fffaf5", "fg": "#24140b", "accent": "#c2410c",
        "muted": "#7c5f4d", "card": "#ffffff",
    },
}


def _e(value: str) -> str:
    """Escape one value for HTML, attribute contexts included."""
    return html.escape(str(value), quote=True)


def _links(pack: SitePack) -> list[tuple[str, str]]:
    """The profile links that survived URL validation, label and href."""
    pairs = (
        ("GitHub", pack.links.github),
        ("LinkedIn", pack.links.linkedin),
        ("Scholar", pack.links.scholar),
        ("Site", pack.links.site),
    )
    return [(label, href) for label, raw in pairs if (href := safe_href(raw))]


def _card(title: str, url: str, blurb: str, meta: str = "") -> list[str]:
    """One card: an optionally linked heading, optional meta line, blurb."""
    href = safe_href(url)
    heading = _e(title)
    if href:
        heading = f'<a href="{_e(href)}" rel="noopener">{heading}</a>'
    parts = ['<article class="card">', f"<h3>{heading}</h3>"]
    if meta:
        parts.append(f'<p class="tagline">{_e(meta)}</p>')
    if blurb:
        parts.append(f"<p>{_e(blurb)}</p>")
    return parts


def render_style_css(palette: Palette) -> str:
    """The whole stylesheet for one palette. No external fonts or assets."""
    c = _PALETTE_CSS[palette]
    return f""":root {{
  --bg: {c["bg"]};
  --fg: {c["fg"]};
  --accent: {c["accent"]};
  --muted: {c["muted"]};
  --card: {c["card"]};
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--fg);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 4rem 1.25rem; }}
h1 {{ font-size: 2.5rem; line-height: 1.15; margin: 0 0 .5rem; }}
h2 {{ font-size: 1.25rem; margin: 3rem 0 1rem; }}
.title {{ color: var(--accent); font-weight: 600; margin: 0 0 1rem; }}
.tagline {{ color: var(--muted); font-size: 1.05rem; margin: 0 0 1.25rem; }}
.links a {{ color: var(--accent); margin-right: 1rem; text-decoration: none; }}
.links a:hover {{ text-decoration: underline; }}
.card {{
  background: var(--card);
  border: 1px solid rgba(127, 127, 127, .18);
  border-radius: 12px;
  padding: 1.25rem;
  margin-bottom: 1rem;
}}
.card h3 {{ margin: 0 0 .35rem; font-size: 1.05rem; }}
.card a {{ color: var(--accent); text-decoration: none; }}
.tech span {{
  display: inline-block;
  font-size: .78rem;
  color: var(--muted);
  border: 1px solid rgba(127, 127, 127, .25);
  border-radius: 999px;
  padding: .1rem .55rem;
  margin: .35rem .35rem 0 0;
}}
.grid {{ display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }}
.split .card {{ display: grid; gap: .75rem; grid-template-columns: 1fr 2fr; }}
footer {{ margin-top: 4rem; color: var(--muted); font-size: .85rem; }}
footer a {{ color: var(--muted); }}
@media (max-width: 560px) {{
  .split .card {{ grid-template-columns: 1fr; }}
  h1 {{ font-size: 2rem; }}
}}
"""


def render_main_js() -> str:
    """The only script the site ships: a year stamp in the footer."""
    return (
        "document.addEventListener('DOMContentLoaded', function () {\n"
        "  var y = document.getElementById('year');\n"
        "  if (y) { y.textContent = String(new Date().getFullYear()); }\n"
        "});\n"
    )


def render_index_html(pack: SitePack, *, inline_css: bool = False) -> str:
    """The whole page.

    ``inline_css`` inlines the stylesheet so the result stands alone inside a
    sandboxed preview iframe. Everything below <body> is identical either way,
    because both come from this one function -- the preview cannot drift from
    the download.
    """
    palette = resolve_palette(pack.theme.palette)
    layout = resolve_layout(pack.theme.layout)
    head_css = (
        f"<style>\n{render_style_css(palette)}</style>"
        if inline_css
        else '<link rel="stylesheet" href="style.css">'
    )
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_e(pack.name)}</title>",
        head_css,
        "</head>",
        "<body>",
        '<main class="wrap">',
        f"<h1>{_e(pack.name)}</h1>",
    ]
    if pack.title:
        parts.append(f'<p class="title">{_e(pack.title)}</p>')
    if pack.tagline:
        parts.append(f'<p class="tagline">{_e(pack.tagline)}</p>')
    if links := _links(pack):
        anchors = " ".join(
            f'<a href="{_e(href)}" rel="me noopener">{_e(label)}</a>'
            for label, href in links
        )
        parts.append(f'<p class="links">{anchors}</p>')
    if pack.about:
        parts.append("<h2>About</h2>")
        parts += [f"<p>{_e(paragraph)}</p>" for paragraph in pack.about]
    if pack.projects:
        parts += ["<h2>Projects</h2>", f'<div class="{_e(layout.value)}">']
        for project in pack.projects:
            parts += _card(project.title, project.repo_url, project.blurb)
            if project.highlights:
                parts.append("<ul>")
                parts += [f"<li>{_e(item)}</li>" for item in project.highlights]
                parts.append("</ul>")
            if project.tech:
                chips = "".join(f"<span>{_e(item)}</span>" for item in project.tech)
                parts.append(f'<p class="tech">{chips}</p>')
            parts.append("</article>")
        parts.append("</div>")
    if pack.evidence:
        parts.append("<h2>Recognition</h2>")
        for item in pack.evidence:
            meta = " - ".join(x for x in (item.criterion, item.date) if x)
            parts += _card(item.title, item.url, item.blurb, meta=meta)
            parts.append("</article>")
    parts += [
        "<footer>",
        f'<p>&copy; <span id="year"></span> {_e(pack.name)} - '
        '<a href="https://meritai.me" rel="noopener">Built with Merit</a></p>',
        "</footer>",
        "</main>",
        '<script src="main.js"></script>',
        "</body>",
        "</html>",
        "",
    ]
    return "\n".join(parts)


def render_site_readme(pack: SitePack) -> str:
    """The README shipped in the zip: how to publish, and what that means."""
    slug = site_slug(pack.name)
    return f"""# {pack.name} - portfolio site

Generated by Merit (https://meritai.me).

## Publish it

GitHub Pages serves a user site from a repo named `<your-username>.github.io`
on the default branch.

```bash
cd {slug}
git init && git add . && git commit -m "Add portfolio site"
git remote add origin https://github.com/<your-username>/<your-username>.github.io.git
git push -u origin main
```

The site is live at `https://<your-username>.github.io` within a minute or two.

## Before you push

Everything in this folder becomes world-readable and permanent in git history.
Anything included from your Merit evidence is published the moment you push.
Read `index.html` first, delete any section you did not mean to make public,
and note that removing it in a later commit does not remove it from history.

## Editing

`index.html` is plain HTML and `style.css` is plain CSS. No build step, no
dependencies, no framework. Edit either directly.
"""


def build_site_zip(pack: SitePack) -> bytes:
    """Bundle the rendered site into a single downloadable zip."""
    palette = resolve_palette(pack.theme.palette)
    root = site_slug(pack.name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{root}/index.html", render_index_html(pack))
        zf.writestr(f"{root}/style.css", render_style_css(palette))
        zf.writestr(f"{root}/main.js", render_main_js())
        zf.writestr(f"{root}/README.md", render_site_readme(pack))
    return buf.getvalue()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_render.py -v`
Expected: PASS, all tests including the three hostile-input parametrisations

- [ ] **Step 5: Commit**

```bash
git add paperpilot/site_render.py tests/test_site_render.py
git commit -m "feat(publish): pure renderer from SitePack to a static site zip"
```

---

### Task 4: Site extraction LLM call

**Files:**
- Create: `paperpilot/site_extract.py`
- Test: `tests/test_site_extract.py`

**Interfaces:**
- Consumes: `SitePack` from Task 1.
- Produces: `SYSTEM_PROMPT`, `build_prompt(profile: dict[str, str], repos: list[tuple[str, str]], evidence: list[dict[str, str]]) -> str`, `build_pack(*, profile: dict[str, str], repos: list[tuple[str, str]], evidence: list[dict[str, str]], session_id: str) -> SitePack`.

`repos` is a list of `(repo_label, bundle_text)`. Routes to the model exactly as `skill_extract.extract_plugin` does: `DEFAULTS["ingest"]` through `gateway.get_client`, wrapped in `trace.step`, with the same JSON-recovery fallback.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_site_extract.py
import json
from unittest.mock import MagicMock, patch

from paperpilot.site_extract import build_pack, build_prompt


def _completion(payload: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=payload), finish_reason="stop")]
    completion.usage = None
    return completion


def test_prompt_carries_profile_repos_and_evidence():
    prompt = build_prompt(
        {"name": "Andre", "title": "AI Engineer", "about": "Builder"},
        [("AndreChuabio/mediguard", "README: a DLP layer")],
        [{"criterion": "awards", "title": "Hackathon winner", "description": "First"}],
    )
    assert "Andre" in prompt
    assert "AndreChuabio/mediguard" in prompt
    assert "Hackathon winner" in prompt


def test_build_pack_parses_a_clean_json_answer():
    payload = json.dumps(
        {
            "name": "Andre Chuabio",
            "title": "AI Engineer",
            "projects": [{"title": "MediGuard", "repo_url": "https://github.com/x/y"}],
            "theme": {"palette": "ember", "layout": "grid"},
        }
    )
    with patch("paperpilot.site_extract.get_client") as client:
        client.return_value.chat.completions.create.return_value = _completion(payload)
        pack = build_pack(profile={"name": "Andre Chuabio"}, repos=[], evidence=[], session_id="s1")
    assert pack.name == "Andre Chuabio"
    assert pack.projects[0].title == "MediGuard"
    assert pack.theme.palette == "ember"


def test_build_pack_recovers_json_wrapped_in_prose():
    payload = 'Sure, here you go:\n{"name": "Andre"}\nHope that helps.'
    with patch("paperpilot.site_extract.get_client") as client:
        client.return_value.chat.completions.create.return_value = _completion(payload)
        pack = build_pack(profile={"name": "Andre"}, repos=[], evidence=[], session_id="s1")
    assert pack.name == "Andre"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'paperpilot.site_extract'`

- [ ] **Step 3: Write the implementation**

```python
# paperpilot/site_extract.py
"""One Gateway LLM call turning a profile, repo bundles and chosen evidence
into a structured SitePack.

The model writes prose and picks a palette and a layout. It never writes
markup: site_render.py owns every tag on the page, and everything this call
returns is escaped before it gets there.
"""

from __future__ import annotations

import json
import re
from typing import Any

from paperpilot import trace
from paperpilot.gateway import DEFAULTS, get_client
from paperpilot.site_models import Layout, Palette, SitePack

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

_PALETTES = ", ".join(p.value for p in Palette)
_LAYOUTS = ", ".join(layout.value for layout in Layout)

SYSTEM_PROMPT = f"""You are a senior engineer writing the copy for a developer's personal portfolio site.

You will receive a profile, zero or more repository bundles, and zero or more pieces of recognition the person has explicitly chosen to publish. Write the site's prose.

Rules:

- Write in the person's stated voice and tone when one is given.
- One project entry per repository bundle. The blurb says what the project does and why it is interesting, in one or two sentences, grounded in the code you were shown. Do not invent features the bundle does not evidence.
- `tech` lists the real technologies visible in the bundle. `highlights` are at most three short factual bullets.
- Keep `about` to two or three short paragraphs.
- Recognition entries are rewritten for a public audience: no case numbers, no immigration or petition wording, no personal contact details.
- You are writing text, never HTML. Do not emit tags, markdown, or scripts. Anything that looks like markup is escaped and shown to the reader literally.

Pick a theme that suits the person. `palette` must be one of: {_PALETTES}. `layout` must be one of: {_LAYOUTS}. Anything else falls back to a default.

Output a JSON object matching this schema EXACTLY:

{{
  "name": "Full Name",
  "title": "Their role, short",
  "tagline": "One line under the title.",
  "about": ["paragraph", "paragraph"],
  "projects": [
    {{"title": "Name", "repo_url": "https://github.com/owner/name", "blurb": "...", "tech": ["Python"], "highlights": ["..."]}}
  ],
  "evidence": [
    {{"criterion": "awards", "title": "...", "blurb": "...", "url": "https://...", "date": "2026-03-01"}}
  ],
  "links": {{"github": "", "linkedin": "", "scholar": "", "site": ""}},
  "theme": {{"palette": "slate", "layout": "stack"}}
}}

Return only the JSON object."""


def build_prompt(
    profile: dict[str, str],
    repos: list[tuple[str, str]],
    evidence: list[dict[str, str]],
) -> str:
    """Assemble the user-side message. Pure, so it tests without a client."""
    blocks = ["## Profile", json.dumps(profile, indent=2)]
    if repos:
        blocks.append("## Repositories")
        for label, bundle in repos:
            blocks.append(f"### {label}\n{bundle}")
    if evidence:
        blocks.append("## Recognition the person chose to publish")
        blocks.append(json.dumps(evidence, indent=2))
    return "\n\n".join(blocks)


def build_pack(
    *,
    profile: dict[str, str],
    repos: list[tuple[str, str]],
    evidence: list[dict[str, str]],
    session_id: str,
) -> SitePack:
    """Single LLM call to a structured SitePack. Traced through trace.step."""
    model = DEFAULTS["ingest"]
    with trace.step(
        session_id,
        "site.extract",
        repos=len(repos),
        evidence=len(evidence),
        model=model,
    ) as ctx:
        client = get_client()
        completion = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_prompt(profile, repos, evidence)},
            ],
            max_tokens=8000,
            temperature=0.4,
        )
        raw = completion.choices[0].message.content or "{}"
        ctx["finish_reason"] = completion.choices[0].finish_reason
        if completion.usage:
            ctx["tokens_in"] = completion.usage.prompt_tokens
            ctx["tokens_out"] = completion.usage.completion_tokens
        try:
            parsed: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            match = _JSON_BLOCK_RE.search(raw)
            if match is None:
                ctx["error"] = "json_extract_failed"
                ctx["raw_preview"] = raw[:400]
                raise
            parsed = json.loads(match.group(0))
            ctx["json_recovered"] = True
        pack = SitePack.model_validate(parsed)
        ctx["projects"] = len(pack.projects)
    return pack
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_extract.py -v`
Expected: PASS, 3 tests

- [ ] **Step 5: Commit**

```bash
git add paperpilot/site_extract.py tests/test_site_extract.py
git commit -m "feat(publish): one Gateway call from profile, repos and evidence to a SitePack"
```

---

### Task 5: Site service

**Files:**
- Create: `backend/services/site_service.py`
- Test: `tests/backend/test_site_service.py`

**Interfaces:**
- Consumes: `site_extract.build_pack`, `site_render.build_site_zip`, `site_render.render_index_html`, `site_models.site_slug`, `plugin_service.fetch_repo_bundle`, `plugin_service._load_bundle`, `plugin_service._check_session_ownership`, `market_service.get_profile`, `evidence_service.list_evidence`.
- Produces: `SiteResult` (frozen dataclass with `site_name: str`, `theme: dict`, `html_preview: str`, `zip_bytes: bytes`, `skipped: list[dict]`) and `build_site(*, user_id: str, repo_urls: list[str], evidence_ids: list[str], session_id: str | None = None) -> SiteResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/backend/test_site_service.py
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from backend.services import site_service
from paperpilot.site_models import SitePack


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_site_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.site_service'`

- [ ] **Step 3: Write the implementation**

```python
# backend/services/site_service.py
"""Portfolio site build service.

Orchestrates profile + repo bundles + explicitly chosen evidence into a
rendered static site zip, and persists it to session_artifacts.

The governing privacy rule lives here: the build includes exactly the
evidence_ids in the request and never widens that set. Nothing reads a stored
publish flag to decide inclusion, so a flag left over from an earlier build can
never republish an item the user later thought better of. Every requested id is
checked against the caller before it is read, because otherwise guessing a uuid
would publish another user's case material.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, status

from backend.services.evidence_service import list_evidence
from backend.services.market_service import get_profile
from backend.services.plugin_service import (
    _check_session_ownership,
    _load_bundle,
    fetch_repo_bundle,
)
from paperpilot import supabase_client
from paperpilot.github_ingest import _parse_repo_url
from paperpilot.site_extract import build_pack
from paperpilot.site_models import site_slug
from paperpilot.site_render import build_site_zip, render_index_html

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SiteResult:
    """One built site: name, resolved theme, preview, zip, and what was dropped."""

    site_name: str
    theme: dict
    html_preview: str
    zip_bytes: bytes
    skipped: list[dict]


def _profile_dict(user_id: str) -> dict[str, str]:
    """The caller's profile as plain strings for the prompt."""
    profile = get_profile(user_id)
    return {
        "name": profile.name,
        "title": profile.title,
        "about": profile.about,
        "voice_tone": profile.voice_tone,
        "github_url": profile.github_url,
        "linkedin_url": profile.linkedin_url,
        "scholar_url": profile.scholar_url,
        "site_url": profile.site_url,
    }


def _selected_evidence(user_id: str, evidence_ids: list[str]) -> list[dict[str, str]]:
    """The requested evidence rows, once every one is proved to be the caller's.

    Rejects rather than silently dropping: a caller who asked to publish an id
    they do not own has either a bug or bad intent, and quietly building a site
    without it would tell them neither.
    """
    if not evidence_ids:
        return []
    owned = {str(item.id): item for item in list_evidence(user_id)}
    missing = [eid for eid in evidence_ids if eid not in owned]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="one or more evidence_ids do not belong to the caller",
        )
    selected = []
    for eid in evidence_ids:
        item = owned[eid]
        selected.append(
            {
                "criterion": item.criterion,
                "title": item.title,
                "description": item.description,
                "url": item.evidence_url,
                "date": item.evidence_date.isoformat() if item.evidence_date else "",
            }
        )
    return selected


def _bundles(
    repo_urls: list[str], *, session_id: str, user_id: str, reuse: bool
) -> tuple[list[tuple[str, str]], list[dict]]:
    """Fetch every repo bundle, collecting the ones that could not be fetched.

    A repo that fails costs its own card and nothing else. Failing the whole
    build over one unreachable repo would throw away the work already done on
    every other one.

    ``reuse`` reads the cached repo_bundle artifact a prior /ingest on this
    session already paid for, exactly as plugin_service._load_bundle does. It
    applies only to a single-repo build: that artifact is keyed by session and
    not by repo, so on a multi-repo site it would hand every project the same
    bundle. The caller decides rather than this function guessing.
    """
    repos: list[tuple[str, str]] = []
    skipped: list[dict] = []
    for repo_url in repo_urls:
        url = repo_url.strip()
        if not url:
            continue
        try:
            owner, name = _parse_repo_url(url)
            bundle = (
                _load_bundle(session_id=session_id, user_id=user_id, repo_url=url)
                if reuse
                else fetch_repo_bundle(url)
            )
            repos.append((f"{owner}/{name}", bundle))
        except Exception as exc:  # noqa: BLE001 -- one repo must not fail the build
            logger.warning("site build skipped repo %s: %s", url, exc)
            skipped.append({"repo_url": url, "reason": str(exc)[:200]})
    return repos, skipped


def build_site(
    *,
    user_id: str,
    repo_urls: list[str],
    evidence_ids: list[str],
    session_id: str | None = None,
) -> SiteResult:
    """Build one portfolio site zip for the caller.

    Raises:
        HTTPException(403): session_id belongs to another user, or an
            evidence_id does not belong to the caller.
    """
    supplied = session_id is not None
    if supplied:
        _check_session_ownership(session_id, user_id)
    session_id = session_id or str(uuid.uuid4())

    profile = _profile_dict(user_id)
    evidence = _selected_evidence(user_id, evidence_ids)
    repos, skipped = _bundles(
        repo_urls,
        session_id=session_id,
        user_id=user_id,
        reuse=supplied and len(repo_urls) == 1,
    )

    pack = build_pack(
        profile=profile, repos=repos, evidence=evidence, session_id=session_id
    )
    if not pack.name:
        pack.name = profile.get("name") or "portfolio"

    zip_bytes = build_site_zip(pack)
    preview = render_index_html(pack, inline_css=True)
    site_name = site_slug(pack.name)

    try:
        supabase_client.insert_artifact(
            session_id,
            user_id,
            "portfolio_site",
            f"{site_name}.zip",
            base64.b64encode(zip_bytes).decode("ascii"),
            metadata={
                "encoding": "base64",
                "projects": len(pack.projects),
                "evidence": len(pack.evidence),
                "skipped": len(skipped),
                "theme": pack.theme.model_dump(),
            },
            content_hash=hashlib.sha256(zip_bytes).hexdigest(),
        )
    except Exception:  # noqa: BLE001 -- persistence must not block the download
        logger.exception("failed to persist portfolio site for user=%s", user_id)

    return SiteResult(
        site_name=site_name,
        theme=pack.theme.model_dump(),
        html_preview=preview,
        zip_bytes=zip_bytes,
        skipped=skipped,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/backend/test_site_service.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add backend/services/site_service.py tests/backend/test_site_service.py
git commit -m "feat(publish): site build service with per-request evidence authorization"
```

---

### Task 6: Publish router

**Files:**
- Create: `backend/routers/site.py`
- Modify: `backend/main.py` (the `from backend.routers import (...)` block and the `app.include_router` block)
- Test: `tests/backend/test_site_route.py`

**Interfaces:**
- Consumes: `site_service.build_site`, `site_service.SiteResult`, `quotas.SITE`, `entitlements.PORTFOLIO`.
- Produces: `POST /publish/site` accepting `{repo_urls, evidence_ids, session_id?}` and returning `{site_name, theme, html_preview, zip_base64, skipped}`.

- [ ] **Step 1: Write the failing test**

There is no `conftest.py` in this repo. `tests/backend/test_api.py` builds a
`TestClient` inline and satisfies auth through `app.dependency_overrides`, so do
the same here rather than introducing fixtures the suite does not use.

```python
# tests/backend/test_site_route.py
"""Route tests for POST /publish/site.

Auth and the BYOK key dependency are overridden so wiring and response shapes
can be asserted without a live Supabase or a real model key, matching the
posture of tests/backend/test_api.py.
"""

from contextlib import contextmanager
from unittest.mock import patch

from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from backend.auth import AuthUser, get_current_user
from backend.byok import require_llm_key
from backend.main import app
from backend.services.site_service import SiteResult

USER_ID = "00000000-0000-0000-0000-000000000001"


def _result() -> SiteResult:
    return SiteResult(
        site_name="andre-chuabio",
        theme={"palette": "slate", "layout": "stack"},
        html_preview="<!doctype html><html></html>",
        zip_bytes=b"PK\x03\x04zip",
        skipped=[],
    )


@contextmanager
def _authed():
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        id=USER_ID, email="clown@example.com"
    )
    app.dependency_overrides[require_llm_key] = lambda: None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_publish_site_returns_base64_zip():
    with _authed() as client, patch(
        "backend.routers.site.build_site", return_value=_result()
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["site_name"] == "andre-chuabio"
    assert body["zip_base64"]
    assert body["theme"]["palette"] == "slate"


def test_publish_site_requires_auth():
    with TestClient(app) as client:
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 401


def test_too_many_repos_is_rejected():
    with _authed() as client:
        response = client.post(
            "/publish/site",
            json={
                "repo_urls": [f"https://github.com/x/r{i}" for i in range(9)],
                "evidence_ids": [],
            },
        )
    assert response.status_code == 400


def test_quota_exhaustion_returns_429():
    def _over_limit(user_id, quota):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="quota spent"
        )

    with _authed() as client, patch(
        "backend.routers.site.quotas.enforce", side_effect=_over_limit
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": []}
        )
    assert response.status_code == 429


def test_evidence_ownership_403_is_not_masked_as_502():
    def _forbidden(**kwargs):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="not the caller's"
        )

    with _authed() as client, patch(
        "backend.routers.site.build_site", side_effect=_forbidden
    ):
        response = client.post(
            "/publish/site", json={"repo_urls": [], "evidence_ids": ["someone-else"]}
        )
    assert response.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/backend/test_site_route.py -v`
Expected: FAIL with a 404 on `/publish/site`, or a `ModuleNotFoundError` for `backend.routers.site`

- [ ] **Step 3: Write `backend/routers/site.py`**

```python
"""Publish router.

Exposes POST /publish/site: build a static portfolio site from the caller's
profile, the repos they picked, and the evidence they explicitly chose to
publish. Returns the site zip base64-encoded for download.

Gating is wired from day one but ships dark: has_entitlement returns True while
STRIPE_PRICE_PORTFOLIO is unset, so switching the paywall on later is an env var
rather than a code change.
"""

from __future__ import annotations

import base64

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from backend import quotas
from backend.auth import AuthUser, CurrentUser
from backend.byok import RequireLLMKey
from backend.entitlements import PORTFOLIO, has_entitlement
from backend.services.site_service import build_site

router = APIRouter(tags=["publish"])

# A build costs one LLM call plus one GitHub fetch per repo. The cap is here so
# a client cannot turn one request into forty fetches.
MAX_REPOS = 8


class BuildSiteRequest(BaseModel):
    """Request body for a portfolio site build."""

    repo_urls: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    session_id: str | None = None


class SkippedRepo(BaseModel):
    """One repo that could not be fetched, and why."""

    repo_url: str
    reason: str


class BuildSiteResponse(BaseModel):
    """The built site: name, resolved theme, preview HTML, and the zip."""

    site_name: str
    theme: dict
    html_preview: str
    zip_base64: str
    skipped: list[SkippedRepo]


@router.post("/publish/site", response_model=BuildSiteResponse)
def build_site_endpoint(
    req: BuildSiteRequest,
    user: AuthUser = CurrentUser,
    _: None = RequireLLMKey,
) -> BuildSiteResponse:
    """Build a portfolio site and return it zipped."""
    if len(req.repo_urls) > MAX_REPOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"at most {MAX_REPOS} repositories per site",
        )
    if not has_entitlement(user.id, PORTFOLIO):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Publish requires a purchase on this account",
        )
    quotas.enforce(user.id, quotas.SITE)

    try:
        result = build_site(
            user_id=user.id,
            repo_urls=req.repo_urls,
            evidence_ids=req.evidence_ids,
            session_id=req.session_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except HTTPException:
        # Raised deliberately downstream (403 on session or evidence ownership).
        # Let it through rather than masking it as a generic 502 below.
        raise
    except Exception as exc:  # noqa: BLE001 -- surface pipeline errors as 502
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Site build failed: {exc}",
        ) from exc

    return BuildSiteResponse(
        site_name=result.site_name,
        theme=result.theme,
        html_preview=result.html_preview,
        zip_base64=base64.b64encode(result.zip_bytes).decode("ascii"),
        skipped=[SkippedRepo(**item) for item in result.skipped],
    )
```

- [ ] **Step 4: Register the router in `backend/main.py`**

Add `site` to the import block, keeping alphabetical order after `plugin`:

```python
from backend.routers import (
    account,
    assist,
    billing,
    cfp,
    draft,
    evidence,
    export,
    ingest,
    market,
    plugin,
    site,
)
```

Add the include beside the others:

```python
app.include_router(site.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/backend/test_site_route.py tests/backend/test_api.py -v`
Expected: PASS, and no regression in the existing API tests

- [ ] **Step 6: Commit**

```bash
git add backend/routers/site.py backend/main.py tests/backend/test_site_route.py
git commit -m "feat(publish): POST /publish/site with quota, gating and repo cap"
```

---

### Task 7: Publish wizard and navigation

**Files:**
- Modify: `web/lib/types.ts` (append the Publish types)
- Modify: `web/lib/api.ts` (add a `publish` section to the exported `api` object)
- Create: `web/app/(app)/publish/page.tsx`
- Create: `web/app/(app)/publish/PublishWizard.tsx`
- Modify: `web/components/AppShell.tsx:16-21` (the `NAV_LINKS` array)
- Test: `web/e2e/publish.spec.ts`

**Interfaces:**
- Consumes: `POST /publish/site` from Task 6, plus the existing `api.evidence.list()` which returns an `EvidenceLedger` of `criteria[].items[]`.
- Produces: `api.publish.buildSite(repoUrls: string[], evidenceIds: string[]): Promise<BuildSiteResponse>`, the `/publish` route, and its nav entry.

All network access goes through the existing `requestJson` helper in
`web/lib/api.ts`, which already resolves `API_BASE_URL` and attaches the
Supabase bearer token. Do not thread a token through props or call `fetch`
directly — that would be a second convention for the same job.

- [ ] **Step 1: Add the nav entry**

In `web/components/AppShell.tsx`, add to `NAV_LINKS` between Market and Call for Papers:

```tsx
  { href: "/publish", label: "Publish" },
```

- [ ] **Step 2: Add the types**

Append to `web/lib/types.ts`:

```ts
/* ----- Publish: portfolio site ----- */

export interface SkippedRepo {
  repo_url: string;
  reason: string;
}

export interface SiteTheme {
  palette: string;
  layout: string;
}

export interface BuildSiteResponse {
  site_name: string;
  theme: SiteTheme;
  html_preview: string;
  zip_base64: string;
  skipped: SkippedRepo[];
}
```

- [ ] **Step 3: Add the API method**

Add `BuildSiteResponse` to the type import block at the top of `web/lib/api.ts`,
then add this section to the exported `api` object beside `evidence`:

```ts
  publish: {
    /** Build a portfolio site from the caller's profile, repos, and chosen evidence. */
    async buildSite(
      repoUrls: string[],
      evidenceIds: string[],
    ): Promise<BuildSiteResponse> {
      return requestJson<BuildSiteResponse>("/publish/site", {
        method: "POST",
        body: { repo_urls: repoUrls, evidence_ids: evidenceIds },
      });
    },
  },
```

- [ ] **Step 4: Write the wizard**

```tsx
// web/app/(app)/publish/PublishWizard.tsx
"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { BuildSiteResponse, EvidenceItem } from "@/lib/types";

interface EvidenceOption {
  id: string;
  criterion: string;
  title: string;
}

export function PublishWizard() {
  const [options, setOptions] = useState<EvidenceOption[]>([]);
  const [repoText, setRepoText] = useState("");
  const [chosen, setChosen] = useState<string[]>([]);
  const [result, setResult] = useState<BuildSiteResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api.evidence
      .list()
      .then((ledger) => {
        if (!live) return;
        const flat: EvidenceOption[] = ledger.criteria.flatMap((criterion) =>
          criterion.items.map((item: EvidenceItem) => ({
            id: item.id,
            criterion: item.criterion,
            title: item.title,
          })),
        );
        setOptions(flat);
      })
      .catch(() => {
        if (live) setOptions([]);
      });
    return () => {
      live = false;
    };
  }, []);

  function toggle(id: string): void {
    setChosen((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function build(): Promise<void> {
    setBusy(true);
    setError("");
    try {
      const repoUrls = repoText
        .split("\n")
        .map((s) => s.trim())
        .filter(Boolean);
      setResult(await api.publish.buildSite(repoUrls, chosen));
    } catch (err) {
      setError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "Build failed",
      );
    } finally {
      setBusy(false);
    }
  }

  function download(): void {
    if (!result) return;
    const bytes = Uint8Array.from(atob(result.zip_base64), (c) =>
      c.charCodeAt(0),
    );
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${result.site_name}.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-8">
      <section>
        <h2 className="font-semibold">Step 1: Your repositories</h2>
        <p className="text-sm text-slate-600">
          One GitHub URL per line, up to eight.
        </p>
        <textarea
          aria-label="Repository URLs"
          className="mt-2 h-32 w-full rounded-lg border p-3 font-mono text-sm"
          value={repoText}
          onChange={(e) => setRepoText(e.target.value)}
          placeholder="https://github.com/you/project"
        />
      </section>

      <section>
        <h2 className="font-semibold">Step 2: What becomes public</h2>
        <p className="text-sm text-slate-600">
          Nothing from Track is published unless you tick it here. Anything you
          tick is world-readable and permanent in git history once you push.
        </p>
        <ul className="mt-2 space-y-2">
          {options.map((item) => (
            <li key={item.id} className="flex items-start gap-2">
              <input
                type="checkbox"
                id={`ev-${item.id}`}
                checked={chosen.includes(item.id)}
                onChange={() => toggle(item.id)}
              />
              <label htmlFor={`ev-${item.id}`} className="text-sm">
                <span className="font-medium">{item.title}</span>
                <span className="text-slate-500"> — {item.criterion}</span>
              </label>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <button
          type="button"
          onClick={build}
          disabled={busy}
          className="rounded-full bg-indigo-600 px-5 py-2 text-white disabled:opacity-50"
        >
          {busy ? "Building..." : "Generate site"}
        </button>
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
      </section>

      {result && (
        <section>
          <h2 className="font-semibold">Step 3: Preview</h2>
          {result.skipped.length > 0 && (
            <ul className="mb-2 text-sm text-amber-700">
              {result.skipped.map((s) => (
                <li key={s.repo_url}>
                  Skipped {s.repo_url}: {s.reason}
                </li>
              ))}
            </ul>
          )}
          <iframe
            title="Site preview"
            sandbox=""
            srcDoc={result.html_preview}
            className="h-[32rem] w-full rounded-lg border"
          />
          <h2 className="mt-6 font-semibold">Step 4: Download and push</h2>
          <button
            type="button"
            onClick={download}
            className="mt-2 rounded-full border px-5 py-2"
          >
            Download {result.site_name}.zip
          </button>
          <p className="mt-2 text-sm text-slate-600">
            Unzip it and follow the README: two git commands puts it live on
            GitHub Pages.
          </p>
        </section>
      )}
    </div>
  );
}
```

Note: `sandbox=""` disables scripts, which is why the preview is safe to render inline.

- [ ] **Step 5: Write the page**

The wizard loads its own evidence through `api.evidence.list()`, so the page is
a thin server component with no data fetching and no token handling.

```tsx
// web/app/(app)/publish/page.tsx
import { PublishWizard } from "./PublishWizard";

export default function PublishPage() {
  return (
    <main className="mx-auto max-w-3xl px-5 py-10">
      <p className="text-sm font-semibold uppercase text-indigo-600">Publish</p>
      <h1 className="mt-1 text-3xl font-bold">Ship a portfolio site</h1>
      <p className="mt-2 text-slate-600">
        Merit writes the site from your profile, the repos you pick, and only
        the recognition you tick. You push it to your own GitHub Pages repo.
      </p>
      <div className="mt-8">
        <PublishWizard />
      </div>
    </main>
  );
}
```

- [ ] **Step 6: Write the e2e test**

```ts
// web/e2e/publish.spec.ts
import { expect, test } from "@playwright/test";

test("publish page renders both wizard steps", async ({ page }) => {
  await page.goto("/publish");
  await expect(page.getByRole("heading", { name: "Ship a portfolio site" })).toBeVisible();
  await expect(page.getByLabel("Repository URLs")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate site" })).toBeVisible();
});
```

If `web/e2e` requires an authenticated storage state, follow the pattern in the existing specs there.

- [ ] **Step 7: Run the checks**

Run: `cd web && npm run lint && npx tsc --noEmit`
Expected: no errors, no `any`

- [ ] **Step 8: Commit**

```bash
git add web/app/\(app\)/publish web/components/AppShell.tsx web/lib/api.ts web/lib/types.ts web/e2e/publish.spec.ts
git commit -m "feat(publish): four-step wizard, sandboxed preview, and nav entry"
```

---

## Verification

1. `pytest` from the repo root, all green.
2. `cd web && npm run lint && npx tsc --noEmit`, clean.
3. Start the backend and `POST /publish/site` with one real repo and one owned evidence id; confirm the zip holds four files and the evidence appears.
4. Repeat with an evidence id belonging to another user; confirm 403.
5. Unzip, open `index.html` in a browser, confirm it renders with no network calls.
6. Push the unzipped folder to a scratch `<user>.github.io` repo; confirm Pages serves it.
