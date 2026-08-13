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
