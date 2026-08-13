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
    """The README shipped in the zip: how to publish, and what that means.

    The name is flattened rather than HTML-escaped: this file is markdown, and
    escaping would put literal entities in front of the reader. Collapsing
    whitespace stops a multi-line name breaking out of the heading, and
    dropping angle brackets stops inline HTML rendering when the repo README is
    viewed on github.com.
    """
    slug = site_slug(pack.name)
    name = " ".join(str(pack.name).split()).replace("<", "").replace(">", "")
    return f"""# {name} - portfolio site

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
