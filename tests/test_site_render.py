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


def test_readme_name_cannot_break_out_of_its_heading():
    """The README is markdown, so the name is flattened rather than escaped.

    Escaping would show literal entities to the reader; what matters here is
    that a multi-line name cannot break the heading and that inline HTML does
    not render when the repo README is viewed on github.com.
    """
    hostile = 'Andre <img src=x onerror=alert(1)>\n\n# Injected heading'
    readme = render_site_readme(SitePack(name=hostile))
    lines = readme.splitlines()

    # The name stays on one line, so it cannot open a heading of its own. The
    # injected text survives as literal words inside the title, which is inert.
    assert lines[0].startswith("# ")
    assert lines[0].endswith("- portfolio site")
    assert "# Injected heading" not in lines[1:]

    # Inline HTML is stripped, so it does not render on github.com.
    assert "<img" not in readme
    assert "<" not in lines[0]
