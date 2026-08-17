"""Lead pages resolve to real addresses, and page titles never become names.

The bug these cover: web search returns pages, so a search hit's title is a
headline and its snippet carries no email. Copying the title into the
recipient name produced outreach addressed to a paper, with an empty To field.
"""

from backend.services import market_service
from paperpilot import nimble_client


USER = "11111111-1111-1111-1111-111111111111"


def _hit(title: str, url: str, snippet: str = "") -> nimble_client.SearchHit:
    return nimble_client.SearchHit(title=title, url=url, snippet=snippet)


def test_search_hit_title_never_becomes_a_recipient_name(monkeypatch):
    """A page title lands in `title`, and `name` stays empty."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(
        nimble_client,
        "search",
        lambda *a, **k: [
            _hit(
                "Collaboration between researchers and practitioners: how and why",
                "https://example.org/paper",
                "Why and how does organisational collaboration enable implementation?",
            )
        ],
    )
    result = market_service.suggest_people(USER, "NETWORK", "collaboration")
    lead = result["people"][0]
    assert lead["name"] == ""
    assert lead["title"].startswith("Collaboration between")
    assert lead["url"] == "https://example.org/paper"


def test_resolve_contact_pulls_corresponding_author_off_the_page(monkeypatch):
    """The address in the page body is found and ranked first."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    page = {
        "data": {
            "content": (
                "Editorial office: editorial@journal.org. "
                "Corresponding author: j.smith@ox.ac.uk"
            )
        }
    }
    monkeypatch.setattr(nimble_client, "extract", lambda *a, **k: page)
    out = market_service.resolve_contact(USER, "https://example.org/paper")
    assert out["found"] is True
    assert out["email"] == "j.smith@ox.ac.uk"
    assert "editorial@journal.org" in out["emails"]
    assert out["name"] == "J Smith"


def test_resolve_contact_prefers_a_person_over_a_role_desk(monkeypatch):
    """With no corresponding-author marker, a named address still wins."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(
        nimble_client,
        "extract",
        lambda *a, **k: {"data": {"content": "info@lab.edu and ada.lovelace@lab.edu"}},
    )
    out = market_service.resolve_contact(USER, "https://lab.edu/people")
    assert out["email"] == "ada.lovelace@lab.edu"


def test_resolve_contact_skips_junk_that_matches_the_email_regex(monkeypatch):
    """Bounce mailboxes, placeholders, and image filenames are not contacts."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(
        nimble_client,
        "extract",
        lambda *a, **k: {
            "data": {
                "content": (
                    "noreply@journal.org sprite@2x.png someone@example.com "
                    "real.person@uni.ac.uk"
                )
            }
        },
    )
    out = market_service.resolve_contact(USER, "https://journal.org/x")
    assert out["emails"] == ["real.person@uni.ac.uk"]


def test_resolve_contact_deobfuscates_at_and_dot(monkeypatch):
    """`name [at] domain [dot] edu` is a real address, written defensively."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(
        nimble_client,
        "extract",
        lambda *a, **k: {"data": {"content": "grace.hopper[at]navy[dot]mil"}},
    )
    out = market_service.resolve_contact(USER, "https://navy.mil/people")
    assert out["email"] == "grace.hopper@navy.mil"


def test_resolve_contact_without_an_email_explains_the_next_step(monkeypatch):
    """A page with no address returns guidance, never a silent empty field."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(
        nimble_client, "extract", lambda *a, **k: {"data": {"content": "no contacts"}}
    )
    out = market_service.resolve_contact(USER, "https://example.org/paper")
    assert out["found"] is False
    assert out["email"] == ""
    assert "open it" in out["reason"].lower()


def test_resolve_contact_when_the_page_cannot_be_opened(monkeypatch):
    """A failed extract degrades to guidance rather than raising."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    monkeypatch.setattr(nimble_client, "extract", lambda *a, **k: None)
    out = market_service.resolve_contact(USER, "https://example.org/paper")
    assert out["found"] is False
    assert "could not open" in out["reason"].lower()


def test_resolve_contact_without_nimble_is_not_an_error(monkeypatch):
    """No key yields an explained miss, matching the people-search contract."""
    monkeypatch.delenv("NIMBLE_API_KEY", raising=False)
    out = market_service.resolve_contact(USER, "https://example.org/paper")
    assert out["found"] is False
    assert "not configured" in out["reason"].lower()


def test_resolve_contact_rejects_a_non_http_url(monkeypatch):
    """A lead with no usable page never reaches the vendor."""
    monkeypatch.setenv("NIMBLE_API_KEY", "test-key")
    called: list[str] = []
    monkeypatch.setattr(
        nimble_client, "extract", lambda *a, **k: called.append("hit") or None
    )
    out = market_service.resolve_contact(USER, "javascript:alert(1)")
    assert out["found"] is False
    assert called == []
