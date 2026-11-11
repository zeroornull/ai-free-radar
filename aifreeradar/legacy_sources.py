"""Recover source quotations from saved tool results without fetching any URLs."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from .models import Category, MessageSource, Resource

# These describe modalities, not particular providers or the current resource list.
_CATEGORY = {
    Category.TEXT: re.compile(
        r"\b(?:text(?: generation)?|chat|llm|language models?)\b|文本|语言模型|对话", re.IGNORECASE
    ),
    Category.IMAGE: re.compile(
        r"\b(?:images?|text.to.image|stable.diffusion)\b|图像|生图|图片", re.IGNORECASE
    ),
    Category.VIDEO: re.compile(r"\b(?:videos?|text.to.video)\b|视频", re.IGNORECASE),
    Category.SPEECH: re.compile(
        r"\b(?:speech|audio|voice|tts|stt|transcription)\b|语音|音频", re.IGNORECASE
    ),
    Category.EMBEDDING: re.compile(
        r"\b(?:embeddings?|embed|vectoriz\w*)\b|嵌入|向量", re.IGNORECASE
    ),
    Category.RERANK: re.compile(r"\b(?:rerank\w*|re.rank\w*)\b|重排|重排序", re.IGNORECASE),
}
_FREE = re.compile(r"\bfree\b|\bno charge\b|\bno cost\b|免费|赠送|赠额|零费用|零支付", re.IGNORECASE)
_GENERIC = {
    "api", "apis", "ai", "free", "plan", "tier", "trial", "evaluation", "key",
    "credits", "credit", "signup", "text", "image", "video", "speech", "models",
    "model", "embedding", "embeddings", "rerank", "service", "starter", "unknown",
}


def safe_source(source: MessageSource) -> bool:
    """Reuse the public URL boundary; validation itself performs no network I/O."""
    # research imports storage, so load its transport validator only on use.
    from .research import PublicPageFetcher, ResearchError

    try:
        PublicPageFetcher.validate_url(source.url)
    except (ResearchError, ValueError, UnicodeError):
        return False
    return True


def cached_sources(data_dir: Path) -> list[MessageSource]:
    """Read only the two JSON shapes emitted by search and page-fetch tools.

    Plain-text research notes are deliberately excluded: their prose is not a
    quotation from the linked page. Symlinked roots, runs and files are excluded.
    """
    root = data_dir / "tool-output"
    if root.is_symlink() or not root.is_dir():
        return []
    boundary = data_dir.resolve()
    if not root.resolve().is_relative_to(boundary):
        return []
    sources: list[MessageSource] = []
    seen: set[tuple[str, str, str]] = set()
    for run_dir in sorted(root.iterdir()):
        if run_dir.is_symlink() or not run_dir.is_dir():
            continue
        for path in sorted(run_dir.iterdir()):
            if path.is_symlink() or not path.is_file():
                continue
            if not path.resolve().is_relative_to(boundary):
                continue
            try:
                if path.stat().st_size > 4_000_000:
                    continue
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValueError):
                continue
            rows: list[tuple[str, str, str, Literal["page", "snippet"]]]
            if isinstance(value, list):
                rows = [
                    (row["url"], row["title"], row["snippet"], "snippet")
                    for row in value
                    if isinstance(row, dict)
                    and all(isinstance(row.get(key), str) for key in ("url", "title", "snippet"))
                ]
            elif (
                isinstance(value, dict)
                and all(isinstance(value.get(key), str) for key in ("url", "checked_at", "text"))
            ):
                try:
                    datetime.fromisoformat(value["checked_at"])
                except ValueError:
                    continue
                rows = [(value["url"], "", value["text"], "page")]
            else:
                continue
            for url, title, excerpt, access in rows:
                try:
                    source = MessageSource(url=url, title=title, excerpt=excerpt, access=access)
                except ValueError:
                    continue
                if not safe_source(source):
                    continue
                key = (source.url, source.excerpt, source.access)
                if key not in seen:
                    seen.add(key)
                    sources.append(source)
    return sources


def _contains(text: str, value: str) -> bool:
    words = re.findall(r"[^\W_]+", value.casefold())
    if not words:
        return False
    pattern = r"[^\w]*".join(re.escape(word) for word in words)
    return bool(re.search(r"(?<!\w)" + pattern + r"(?!\w)", text.casefold()))


def _specific(value: str) -> bool:
    return any(
        word not in _GENERIC and len(word) > 2
        for word in re.findall(r"[^\W_]+", value.casefold())
    )


def _names(resource: Resource) -> list[str]:
    return [resource.service, resource.service_key, *resource.aliases, *resource.models]


def matching_sources(
    resource: Resource, resources: list[Resource], sources: list[MessageSource]
) -> list[MessageSource]:
    """Require service context beside the free claim, never just a provider hit.

    Shared pricing pages may support several categories only when each selected
    quotation names that category or an unambiguous service/model. Navigation,
    documentation indexes and a free claim elsewhere on the page cannot supply
    that relationship.
    """
    peers = [
        item
        for item in resources
        if item.id != resource.id and item.provider_domain == resource.provider_domain
    ]
    unique_names = [
        name for name in _names(resource)
        if _specific(name)
        and name.casefold() != resource.provider.casefold()
        and not any(
            _contains(name, peer.provider) and _contains(peer.provider, name)
            or any(_contains(other, name) for other in _names(peer))
            for peer in peers
        )
    ]
    result: list[MessageSource] = []
    for source in sources:
        parsed = urlsplit(source.url)
        path = unquote(parsed.path).casefold()
        if (
            path.endswith(("/llms.txt", "/llms-full.txt"))
            or re.search(r"/(?:search|index)(?:[/.]|$)", path)
        ):
            continue
        host = (parsed.hostname or "").casefold()
        own_host = bool(
            resource.provider_domain
            and (host == resource.provider_domain or host.endswith("." + resource.provider_domain))
        )
        context = f"{source.title}\n{unquote(source.url)}\n{source.excerpt}"
        provider_match = _specific(resource.provider) and _contains(context, resource.provider)
        name_match = any(_contains(context, name) for name in unique_names)
        if not (own_host or provider_match or name_match):
            continue
        # External lists need a provider/service anchor in the actual selected
        # passage; a provider name in another row cannot identify this offer.
        title_context = f"{source.title}\n{path}"
        title_categories = {
            category
            for category, pattern in _CATEGORY.items()
            if pattern.search(title_context)
        }
        # A page may price several modalities. A section keeps the free claim
        # beside the heading that names its modality; bare lines lose that scope.
        parts = re.split(r"(?m)^(#{2,6}\s+.+)$", source.excerpt)
        candidates: list[str] = []
        if len(parts) > 1:
            if parts[0].strip():
                candidates.append(parts[0].strip())
            for index in range(1, len(parts), 2):
                section = f"{parts[index]}\n{parts[index + 1] if index + 1 < len(parts) else ''}"
                if section.strip() and len(section) <= 2500:
                    candidates.append(section.strip())
        segments = re.split(r"\n\s*\n|\n|(?<=[.!?。；;])\s+|,\s+(?=[A-Za-z])", source.excerpt)
        candidates.extend(segment.strip() for segment in segments if segment.strip())
        # Short opening API declarations often precede their first modality
        # heading (for example a Classic API's free declaration then Images).
        opening = source.excerpt[:900]
        if source.excerpt.lstrip().startswith("#") and len(segments) > 1:
            next_heading = re.search(r"\n##\s+", opening)
            if next_heading:
                end = re.search(r"\n##\s+", opening[next_heading.end():])
                stop = next_heading.end() + end.start() if end else len(opening)
                candidates.append(opening[:stop])
        for excerpt in candidates:
            if not _FREE.search(excerpt):
                continue
            # Markdown directory rows are references, not statements about an
            # offer; their link labels must not be promoted into policy quotes.
            if re.match(r"^\s*[-*]\s+\[", excerpt):
                continue
            local_identity = own_host or any(
                _contains(excerpt, name)
                for name in [resource.provider, *unique_names]
                if _specific(name)
            ) or (_specific(resource.provider) and _contains(source.title, resource.provider))
            if not local_identity:
                continue
            categories = {
                category for category, pattern in _CATEGORY.items() if pattern.search(excerpt)
            }
            specific = any(_contains(excerpt, name) for name in unique_names)
            relevant = (
                resource.category in categories or resource.category in title_categories
                or specific or not peers
            )
            if not relevant:
                continue
            # A shared product alias cannot borrow the free status of a
            # different modality. Explicit model/service names may disambiguate.
            if not specific and (
                (categories and resource.category not in categories)
                or (title_categories and resource.category not in title_categories)
            ):
                continue
            selected = source.model_copy(update={"excerpt": excerpt})
            result.append(selected)
            break
    return result
