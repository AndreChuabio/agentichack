"""Where a generated portfolio site goes when it is published.

One protocol, one adapter. The GitHub-push adapter planned for v3 implements
the same two verbs, so nothing in the generator changes when it lands.

The draft boundary lives in the database, not here: a row is written with
published = false, and the RLS policy on published_site only exposes rows where
published is true. A draft is therefore invisible to the anon client that serves
the public page, rather than merely unlinked.
"""

from __future__ import annotations

import os
from typing import Final, Protocol

from paperpilot import supabase_client
from paperpilot.site_models import site_slug

# Names that would shadow an app route if handed out as a site slug.
RESERVED_SLUGS: Final[frozenset[str]] = frozenset(
    {
        "api", "auth", "cfp", "login", "logout", "market", "privacy",
        "productize", "publish", "signup", "track", "u", "admin", "static",
    }
)

# How many times a colliding slug is suffixed before giving up.
_MAX_SLUG_ATTEMPTS: Final = 50

_DEFAULT_BASE: Final = "https://meritai.me"


class PublishTarget(Protocol):
    """Somewhere a rendered site can be put and taken down again."""

    def save_draft(self, user_id: str, slug: str, html: str) -> None: ...

    def publish(self, user_id: str) -> str: ...

    def unpublish(self, user_id: str) -> None: ...


class HostedTarget:
    """Serves the site from Merit at /u/<slug>, backed by published_site."""

    def public_url(self, slug: str) -> str:
        """The address a published site answers on."""
        base = os.environ.get("PUBLIC_SITE_BASE_URL", _DEFAULT_BASE).rstrip("/")
        return f"{base}/u/{slug}"

    def reserve_slug(self, user_id: str, name: str) -> str:
        """The slug this user's site lives at, minted once and then stable.

        Stable is the point: a rebuild updates the HTML behind the same URL, so
        a link the user already shared keeps working.

        The slug this user ALREADY holds therefore wins over anything derived
        from the name. Re-deriving on every build would migrate them off a URL
        they had already shared the moment the name drifted by a word -- and it
        drifts easily, because the name is model output produced at temperature
        0.4 and falls back to a profile field the user can edit at any time.
        A slug held by somebody else, or one that would shadow an app route, is
        suffixed until it is free.
        """
        conn = supabase_client.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug FROM published_site WHERE user_id = %s", (user_id,)
                )
                held = cur.fetchone()
                if held is not None and held[0]:
                    return str(held[0])

                base = site_slug(name)
                for attempt in range(1, _MAX_SLUG_ATTEMPTS + 1):
                    candidate = base if attempt == 1 else f"{base}-{attempt}"
                    if candidate in RESERVED_SLUGS:
                        continue
                    cur.execute(
                        "SELECT user_id FROM published_site WHERE slug = %s",
                        (candidate,),
                    )
                    row = cur.fetchone()
                    # No row means nobody holds it. A row with no owner means
                    # the same thing, so it is treated as free rather than as
                    # a collision that would push the user onto a new URL.
                    owner = None if row is None else row[0]
                    if owner is None or str(owner) == user_id:
                        return candidate
        finally:
            conn.close()
        raise ValueError(f"could not find a free slug for {name!r}")

    def save_draft(self, user_id: str, slug: str, html: str) -> None:
        """Write the site as a draft. Never changes what is being served.

        Only the `html` column moves. `live_html` -- what /u/<slug> actually
        serves -- and the `published` flag are both left alone, so rebuilding
        can neither publish new content nor take down a page somebody already
        has the link to. A user who ticks another piece of evidence and rebuilds
        to look at it has not published it by doing so.
        """
        conn = supabase_client.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO published_site (user_id, slug, html) "
                    "VALUES (%s, %s, %s) "
                    "ON CONFLICT (user_id) DO UPDATE SET "
                    "slug = EXCLUDED.slug, html = EXCLUDED.html, updated_at = now()",
                    (user_id, slug, html),
                )
            conn.commit()
        finally:
            conn.close()

    def publish(self, user_id: str) -> str:
        """Promote the current draft to live and return its public URL.

        Copying html into live_html here is the whole of the draft boundary:
        this is the only statement in the system that changes what a visitor
        sees, and it runs only when the user asks for it.
        """
        conn = supabase_client.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE published_site "
                    "SET live_html = html, published = true, updated_at = now() "
                    "WHERE user_id = %s RETURNING slug",
                    (user_id,),
                )
                row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()
        if row is None:
            raise ValueError("there is no built site to publish")
        return self.public_url(str(row[0]))

    def unpublish(self, user_id: str) -> None:
        """Take the site down by deleting the row, not by clearing a flag.

        Clearing a flag would leave the rendered HTML -- and any evidence the
        user chose to include in it -- sitting in the table after they asked
        for it to be gone.
        """
        conn = supabase_client.get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM published_site WHERE user_id = %s", (user_id,))
            conn.commit()
        finally:
            conn.close()
