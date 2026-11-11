"""Coverage evaluation against a curated seed target list.

Imports with no network access; real research runs are gated behind ``main``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .config import load_settings
from .models import CATEGORY_LABELS, Category, Policy, normalize_domain

SEED_PATH = Path(__file__).resolve().parent.parent / "benchmark" / "seed_targets.json"
SEED_KEYS = {"provider", "service", "category", "official_url"}
OUTPUT_PATTERN = "coverage-%Y%m%d-%H%M.md"


def load_seed_targets(path: Path | str) -> list[dict[str, Any]]:
    """Load and validate the seed target list.

    Exactly the four keys (``provider``, ``service``, ``category``,
    ``official_url``), a valid :class:`Category`, and an https URL are required.
    """
    targets_path = Path(path)
    try:
        document = json.loads(targets_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取种子目标文件 {targets_path}: {error}") from error

    raw = document.get("targets") if isinstance(document, dict) else document
    if not isinstance(raw, list):
        raise TypeError("种子目标文件缺少 targets 列表")

    targets: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise TypeError(f"种子目标 #{index} 不是对象")
        missing = SEED_KEYS - set(item)
        if missing:
            raise ValueError(f"种子目标 #{index} 缺少字段: {sorted(missing)}")
        extra = set(item) - SEED_KEYS
        if extra:
            raise ValueError(f"种子目标 #{index} 含未知字段: {sorted(extra)}")
        provider = str(item["provider"]).strip()
        service = str(item["service"]).strip()
        if not provider or not service:
            raise ValueError(f"种子目标 #{index} provider/service 不能为空")
        try:
            category = Category(str(item["category"]))
        except ValueError as error:
            raise ValueError(f"种子目标 #{index} 类别无效: {item['category']}") from error
        url = str(item["official_url"]).strip()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"种子目标 #{index} official_url 必须是 https 网址: {url}")
        targets.append(
            {
                "provider": provider,
                "service": service,
                "category": category,
                "official_url": url,
            }
        )
    return targets


def _target_host(target: dict[str, Any]) -> str:
    return normalize_domain(str(target["official_url"]))


def _domains_relate(seed: str, policy_domain: str) -> bool:
    """True when the two normalized domains share a dot-boundary suffix."""
    if not seed or not policy_domain:
        return seed == policy_domain
    return (
        policy_domain == seed
        or policy_domain.endswith("." + seed)
        or seed.endswith("." + policy_domain)
    )


def match_targets(
    targets: Sequence[dict[str, Any]], policies: Sequence[Policy]
) -> list[dict[str, Any]]:
    """Return one row per seed target with coverage and service-match flags.

    A target is covered when some policy shares its normalised provider
    domain (``normalize_domain(policy.provider_domain)``), compared by exact
    equality or a dot-boundary suffix in either direction, and its category.
    ``service_matched`` is true when a covering policy also matches the target
    service name case-insensitively (its ``service`` or any alias).
    """
    normalized = [
        (normalize_domain(policy.provider_domain), policy) for policy in policies
    ]

    rows: list[dict[str, Any]] = []
    for target in targets:
        domain = _target_host(target)
        candidates = [
            policy
            for policy_domain, policy in normalized
            if policy.category == target["category"]
            and _domains_relate(domain, policy_domain)
        ]

        covered = bool(candidates)
        want_service = str(target["service"]).casefold()
        service_matched = covered and any(
            policy.service.casefold() == want_service
            or want_service in (alias.casefold() for alias in policy.aliases)
            for policy in candidates
        )
        rows.append(
            {
                "provider": target["provider"],
                "service": target["service"],
                "category": target["category"],
                "official_url": target["official_url"],
                "covered": covered,
                "service_matched": service_matched,
            }
        )
    return rows


def _discovery_field(discovery: Any, name: str, default: Any = None) -> Any:
    if isinstance(discovery, dict):
        return discovery.get(name, default)
    return getattr(discovery, name, default)


def _discovery_rows(discoveries: Sequence[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for discovery in discoveries:
        rows.append(
            {
                "url": str(_discovery_field(discovery, "url", "")),
                "category": _discovery_field(discovery, "category", None),
                "provider": _discovery_field(discovery, "provider", None),
                "origin": str(_discovery_field(discovery, "origin", "")),
                "source_class": str(_discovery_field(discovery, "source_class", "")),
            }
        )
    return rows


def _unseeded(rows: list[dict[str, Any]], targeted: set[tuple[str, str]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        url = str(row["url"]).strip()
        if not url:
            continue
        category = str(row["category"])
        host = normalize_domain(url)
        marker = (category, host)
        if marker in targeted:
            continue
        unique.setdefault(marker, row)
    return [unique[key] for key in sorted(unique)]


def render_report(
    targets: Sequence[dict[str, Any]],
    policies: Sequence[Policy],
    discoveries: Sequence[Any],
    run_meta: dict[str, Any] | None = None,
) -> str:
    """Render a Markdown coverage report over seed targets and research output."""
    meta = run_meta or {}
    matched = match_targets(targets, policies)
    by_category: dict[str, list[dict[str, Any]]] = {
        str(category): [] for category in Category
    }
    for row in matched:
        by_category[str(row["category"])].append(row)

    targeted_domains: set[tuple[str, str]] = set()
    for row in matched:
        targeted_domains.add((str(row["category"]), _target_host(row)))

    discovery_rows = _discovery_rows(discoveries)
    unseeded = _unseeded(discovery_rows, targeted_domains)

    lines: list[str] = [
        "# AIFreeRadar 覆盖评测报告",
        "",
        (
            f"- 生成时间: "
            f"{meta.get('generated_at', datetime.now().astimezone().isoformat(timespec='seconds'))}"
        ),
    ]
    if meta.get("config"):
        lines.append(f"- 配置: {meta['config']}")
    if meta.get("model"):
        lines.append(f"- 模型: {meta['model']}")
    if meta.get("resource_count") is not None:
        lines.append(f"- 研究产出记录: {meta['resource_count']}")
    if meta.get("verified_count") is not None:
        lines.append(f"- 其中严格核验政策: {meta['verified_count']}")
    if meta.get("message_count") is not None:
        lines.append(f"- 其中收集消息（未核验）: {meta['message_count']}")
    if meta.get("message_count") and not meta.get("verified_count"):
        lines.append("- 覆盖仅表示来源记录已收集，不代表官方政策核验通过")
    lines.extend(["", "## 类别覆盖", ""])
    lines.extend(["| 类别 | 已覆盖 | 缺失 | 目标数 |", "|---|---|---|---|"])
    missing_rows: list[dict[str, Any]] = []
    for category in Category:
        rows = by_category[str(category)]
        covered = sum(1 for row in rows if row["covered"])
        missing = len(rows) - covered
        missing_rows.extend(row for row in rows if not row["covered"])
        label = CATEGORY_LABELS.get(str(category), str(category))
        lines.append(f"| {label} ({category}) | {covered} | {missing} | {len(rows)} |")

    lines.extend(["", "## 缺失目标", ""])
    if missing_rows:
        for row in missing_rows:
            name_match = "（服务名已匹配）" if row["service_matched"] else ""
            lines.append(
                f"- [{row['category']}] {row['provider']} — {row['service']}"
                f"{name_match} — {row['official_url']}"
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 未纳入种子的发现资源", ""])
    if unseeded:
        for row in unseeded:
            provider = f"{row['provider']} — " if row.get("provider") else ""
            lines.append(f"- [{row['category']}] {provider}{row['url']}")
    else:
        lines.append("未采集到种子之外的发现线索。")

    attribution = Counter(
        (row["origin"], row["source_class"]) for row in discovery_rows if row["origin"]
    )
    if attribution:
        lines.extend(["", "## 来源归因", "", "| 来源 | 类型 | 数量 |", "|---|---|---|"])
        for (origin, source_class), count in sorted(attribution.items()):
            lines.append(f"| {origin} | {source_class} | {count} |")

    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coverage-eval",
        description="对比研究产出与种子目标列表，输出 Markdown 覆盖报告。",
    )
    parser.add_argument("--config", type=str, default=None, help="TOML 配置文件路径")
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="报告输出路径（默认 data/tmp-stats/coverage-YYYYMMDD-HHMM.md）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只加载种子与配置，打印类别计数和 URL，不触碰网络或模型。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        targets = load_seed_targets(SEED_PATH)
    except ValueError as error:
        print(f"覆盖评测失败: {error}", file=sys.stderr)
        return 1

    try:
        settings = load_settings(Path(args.config) if args.config else None)
    except (OSError, ValueError) as error:
        print(f"覆盖评测配置失败: {error}", file=sys.stderr)
        return 1

    config_name = args.config or "config.toml"
    if args.dry_run:
        print(f"种子目标: {len(targets)} 个")
        for category in Category:
            rows = [t for t in targets if t["category"] == category]
            label = CATEGORY_LABELS.get(str(category), str(category))
            print(f"\n{label} ({category}): {len(rows)} 个")
            for row in rows:
                print(f"  - {row['provider']}: {row['service']} — {row['official_url']}")
        print(f"\n配置: {config_name}（未运行研究）")
        return 0

    try:
        from .research import HarnessResearcher

        work_dir = Path(tempfile.mkdtemp(prefix="coverage-eval-"))
        runtime = settings.model_copy(
            update={"data_dir": work_dir, "schedule_enabled": False}
        )
        researcher = HarnessResearcher(runtime)
        batch = asyncio.run(researcher.research(runtime.default_scope, []))
        discoveries = getattr(researcher, "last_discoveries", []) or []
        policies = [*batch.resources, *(message.policy for message in batch.messages)]
        run_meta: dict[str, Any] = {
            "config": config_name,
            "model": runtime.model,
            "resource_count": len(policies),
            "verified_count": len(batch.resources),
            "message_count": len(batch.messages),
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        if batch.failures:
            run_meta["note"] = "研究存在失败分段: " + "; ".join(batch.failures)
        report = render_report(targets, policies, discoveries, run_meta)

        if args.out is None:
            out_path = Path("data") / "tmp-stats" / datetime.now().strftime(OUTPUT_PATTERN)
        else:
            out_path = Path(args.out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")
        print(f"覆盖报告已写入 {out_path}")
        return 0
    except Exception as error:  # noqa: BLE001
        print(f"覆盖评测运行失败: {type(error).__name__}: {error}", file=sys.stderr)
        return 1