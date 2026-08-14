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
