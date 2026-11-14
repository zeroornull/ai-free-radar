"""Deterministic, network-free parsing of managed source representations."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree

from bs4 import BeautifulSoup, Tag


@dataclass
class ParsedItem:
    external_id: str
    url: str
    title: str
    content: str
    raw_content: str
    published_at: datetime | None = None


@dataclass
class ParsedDocument:
    text: str
    links: list[str] = field(default_factory=list)
    items: list[ParsedItem] = field(default_factory=list)
    coverage_warning: str = ""


def public_link(base: str, value: str) -> str:
    """Keep inert public HTTP links; the shared transport validates DNS before use."""
    try:
        resolved = urljoin(base, value.strip())
        parsed = urlsplit(resolved)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in resolved)
            or parsed.port not in {None, 80 if parsed.scheme == "http" else 443}
        ):
            return ""
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return ""


def _unique_links(base: str, values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(link for value in values if (link := public_link(base, value))))


def _text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for element in soup.select("script,style,noscript,template,svg"):
        element.decompose()
    return "\n".join(
        line for part in soup.get_text("\n").splitlines() if (line := " ".join(part.split()))
    )


def _date(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        result = datetime.fromisoformat(value.strip())
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def parse_web(
    raw: str,
    url: str,
    *,
    content_type: str = "text/html",
    include_selectors: Sequence[str] = (),
    exclude_selectors: Sequence[str] = (),
    ignore_patterns: Sequence[str] = (),
    fallback_links: Sequence[str] = (),
) -> ParsedDocument:
    is_html = "html" in content_type.lower() or bool(
        re.search(r"<\s*(?:html|body|article|div)\b", raw, re.IGNORECASE)
    )
    links: list[str] = []
    title = ""
    published_at: datetime | None = None
    if is_html:
        soup = BeautifulSoup(raw, "html.parser")
        title = " ".join(soup.title.get_text(" ", strip=True).split()) if soup.title else ""
        for meta in soup.find_all("meta"):
            key = str(meta.get("property") or meta.get("name") or "").lower()
            if key in {
                "article:published_time",
                "datepublished",
                "date",
                "pubdate",
            } and meta.get("content"):
                published_at = _date(str(meta.get("content")))
                if published_at is not None:
                    break
        if published_at is None:
            time_element = soup.find("time")
            if time_element is not None and time_element.get("datetime"):
                published_at = _date(str(time_element.get("datetime")))
        selected: list[Tag] = []
        for selector in include_selectors:
            matches = soup.select(selector)
            if not matches:
                raise ValueError(f"正文选择器未匹配: {selector}")
            selected.extend(matches)
        for element in soup.select("script,style,noscript,template,svg"):
            element.decompose()
        for selector in exclude_selectors:
            for element in soup.select(selector):
                element.decompose()
        roots: list[Tag] = selected if include_selectors else [soup]
        parts = []
        for root in roots:
            if root.name is None:
                continue
            parts.append(root.get_text("\n"))
            if root.name == "a" and root.get("href"):
                links.append(str(root.get("href")))
            links.extend(str(anchor.get("href")) for anchor in root.select("a[href]"))
        text = "\n".join(parts)
    else:
        if include_selectors:
            raise ValueError("纯文本响应无法应用正文选择器")
        text = raw
        links = list(fallback_links)
    for pattern in ignore_patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)
    text = "\n".join(line for part in text.splitlines() if (line := " ".join(part.split())))
    if not text:
        raise ValueError("正文为空或选择/降噪规则移除了全部正文")
    if not title:
        title = next((line for line in text.splitlines() if line), "")[:200]
    entry_url = public_link(url, url) or url
    return ParsedDocument(
        text=text,
        links=_unique_links(url, links),
        items=[ParsedItem(entry_url, entry_url, title, text, raw, published_at)],
    )



def _child(element: ElementTree.Element, names: set[str]) -> str:
    for child in element:
        if not isinstance(child.tag, str):
            continue
        if child.tag.rsplit("}", 1)[-1].lower() in names:
            return "".join(child.itertext()).strip()
    return ""


def parse_feed(raw: str, url: str, content_type: str = "") -> ParsedDocument:
    items: list[ParsedItem] = []
    if "json" in content_type.lower() or raw.lstrip().startswith("{"):
        document = json.loads(raw)
        if not isinstance(document, dict) or not isinstance(document.get("items"), list):
            raise ValueError("JSON Feed 缺少 items 数组")
        for record in document["items"]:
            if not isinstance(record, dict):
                raise ValueError("JSON Feed 条目必须是对象")  # noqa: TRY004
            native_id = str(record.get("id", "")).strip()
            link = public_link(url, str(record.get("url") or record.get("external_url") or ""))
            content = str(
                record.get("content_text")
                or record.get("content_html")
                or record.get("summary")
                or ""
            )
            title = str(record.get("title") or "")
            if not native_id and not link:
                raise ValueError("JSON Feed 条目缺少原始 ID 和链接")
            items.append(ParsedItem(
                native_id or link,
                link or url,
                title,
                _text(content),
                json.dumps(record, ensure_ascii=False, sort_keys=True),
                _date(str(record.get("date_published") or record.get("date_modified") or "")),
            ))
    else:
        if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
            raise ValueError("Feed 拒绝 DTD/entity 声明")
        root = ElementTree.fromstring(raw)
        if not isinstance(root.tag, str):
            raise ValueError("不支持的 Feed 根元素")
        root_name = root.tag.rsplit("}", 1)[-1].lower()
        if root_name not in {"rss", "feed", "rdf"}:
            raise ValueError("不支持的 Feed 根元素")
        for record in root.iter():
            if not isinstance(record.tag, str):
                continue
            name = record.tag.rsplit("}", 1)[-1].lower()
            if name not in {"item", "entry"}:
                continue
            native_id = _child(record, {"guid", "id"})
            link_value = _child(record, {"link"})
            for child in record:
                if not isinstance(child.tag, str):
                    continue
                if (
                    child.tag.rsplit("}", 1)[-1].lower() == "link"
                    and child.get("rel", "alternate") == "alternate"
                    and child.get("href")
                ):
                    link_value = child.get("href", "")
                    break
            link = public_link(url, link_value) if link_value else ""
            if not native_id and not link:
                raise ValueError("Feed 条目缺少原始 ID 和链接")
            content = _child(record, {"encoded", "content"}) or _child(
                record, {"description", "summary"}
            )
            items.append(ParsedItem(
                native_id or link,
                link or url,
                _child(record, {"title"}),
                _text(content),
                ElementTree.tostring(record, encoding="unicode"),
                _date(_child(record, {"pubdate", "published", "updated", "date"})),
            ))
    # A feed is a moving window, not a complete historical inventory.
    warning = "Feed 仅覆盖当前发布窗口；条目消失不表示政策失效"
    return ParsedDocument(
        text="\n\n".join(f"{item.title}\n{item.content}" for item in items),
        links=list(dict.fromkeys(item.url for item in items)),
        items=items,
        coverage_warning=warning,
    )


def parse_catalog(raw: str, url: str) -> ParsedDocument:
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ValueError("目录必须是 provider 对象映射")  # noqa: TRY004
    providers = document.get("providers", document)
    if not isinstance(providers, dict):
        raise ValueError("目录 providers 必须是对象映射")  # noqa: TRY004
    items: list[ParsedItem] = []
    for provider_id, provider in sorted(providers.items()):
        if not isinstance(provider, dict):
            continue
        models = provider.get("models", {})
        if not isinstance(models, dict):
            raise ValueError(f"目录 provider {provider_id} 的 models 必须为对象")  # noqa: TRY004
        metadata = {key: value for key, value in provider.items() if key != "models"}
        provider_raw = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        provider_url = public_link(
            url,
            str(provider.get("doc") or provider.get("api") or provider.get("url") or ""),
        ) or url
        provider_title = str(provider.get("name") or provider_id)
        items.append(ParsedItem(
            f"provider:{provider_id}",
            provider_url,
            provider_title,
            f"目录提供商线索（不证明免费）\nprovider_id={provider_id}\n{provider_raw}",
            provider_raw,
        ))
        for model_id, model in sorted(models.items()):
            if not isinstance(model, dict):
                raise ValueError(f"目录模型 {provider_id}/{model_id} 必须为对象")  # noqa: TRY004
            record = {"provider_id": provider_id, "model_id": model_id, "model": model}
            record_raw = json.dumps(record, ensure_ascii=False, sort_keys=True)
            link = public_link(
                provider_url, str(model.get("doc") or model.get("url") or "")
            ) or provider_url
            items.append(ParsedItem(
                f"model:{provider_id}:{model_id}",
                link,
                f"{provider_title} / {model.get('name') or model_id}",
                f"目录模型线索（价格为零也不证明免费）\n{record_raw}",
                record_raw,
            ))
    if not items:
        raise ValueError("目录没有可识别的 provider/model 记录")
    return ParsedDocument(
        text="\n\n".join(item.content for item in items),
        links=list(dict.fromkeys(item.url for item in items)),
        items=items,
        coverage_warning="第三方目录变化仅为线索；删除记录不表示政策失效，零价格不证明免费",
    )