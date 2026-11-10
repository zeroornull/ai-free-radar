"""Safe presentation helpers shared by JSON and transitional HTML pages."""

from __future__ import annotations

import os
import re
from html import escape
from typing import Any, Protocol, cast
from urllib.parse import urlsplit

from markdown_it import MarkdownIt
from pydantic import JsonValue

from .briefing import markdown_text
from .config import Settings


def safe_url(value: object) -> str | None:
    """Only explicit HTTP links can become navigation targets."""
    if not isinstance(value, str) or not value or any(ord(c) < 33 for c in value):
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\\" in value
        ):
            return None
        port = parsed.port
        if port is not None and not 0 <= port <= 65535:
            raise ValueError("malformed port")
    except ValueError:
        return None
    return value


class _RuleRenderer(Protocol):
    rules: dict[str, Any]


def _markdown_renderer() -> MarkdownIt:
    renderer = MarkdownIt("commonmark", {"html": False, "linkify": False})

    def link_open(tokens, idx, options, env):
        target = safe_url(tokens[idx].attrGet("href"))
        if target is None:
            return "<a>"
        return f'<a href="{escape(target, quote=True)}" rel="noreferrer noopener">'

    def image(tokens, idx, options, env):
        # Model-supplied images never fetch a remote resource when a report is opened.
        return escape(tokens[idx].content)

    rules = cast(_RuleRenderer, renderer.renderer).rules
    rules["link_open"] = link_open
    rules["image"] = image
    return renderer


_RENDERER = _markdown_renderer()


def render_markdown(value: str) -> str:
    return _RENDERER.render(value)


def redact_text(value: str, settings: Settings) -> str:
    secrets = {
        settings.model_api_key,
        settings.search_api_key,
        os.environ.get(settings.model_api_key_env, ""),
        os.environ.get(settings.search_api_key_env, ""),
    }
    # Stored briefings encode inline text before presentation redaction runs.
    # Match the writer's representation before Markdown restores its punctuation.
    representations = {
        representation
        for secret in secrets
        if secret
        for representation in (secret, markdown_text(secret))
        if representation
    }
    for secret in sorted(representations, key=len, reverse=True):
        value = value.replace(secret, "[密钥已隐藏]")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[密钥已隐藏]", value)


def redact_json(value: JsonValue, settings: Settings) -> JsonValue:
    if isinstance(value, str):
        return redact_text(value, settings)
    if isinstance(value, list):
        return [redact_json(item, settings) for item in value]
    if isinstance(value, dict):
        return {redact_text(key, settings): redact_json(item, settings) for key, item in value.items()}
    return value
