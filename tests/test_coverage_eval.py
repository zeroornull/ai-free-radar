"""Coverage benchmark tests: seed validation, matching, report rendering, dry run."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit

import pytest

from aifreeradar import coverage_eval, research
from aifreeradar.coverage_eval import (
    SEED_PATH,
    load_seed_targets,
    main,
    match_targets,
    render_report,
)
from aifreeradar.models import (
    CATEGORY_LABELS,
    Category,
    CollectedMessage,
    LeadDiscovery,
    MessageSource,
    Policy,
    ResearchBatch,
)


def _target(category: Category, url: str = "https://example.com/pricing") -> dict:
    return {
        "provider": "Example",
        "service": "Example Service",
        "category": category,
        "official_url": url,
    }


def test_seed_targets_four_per_category_and_https() -> None:
    targets = load_seed_targets(SEED_PATH)

    assert len(targets) == 24
    counts = Counter(target["category"] for target in targets)
    assert set(counts) == set(Category)
    assert all(count == 4 for count in counts.values())
    for target in targets:
        assert set(target) == {"provider", "service", "category", "official_url"}
        assert isinstance(target["category"], Category)
        parsed = urlsplit(target["official_url"])
        assert parsed.scheme == "https"
        assert parsed.hostname


def test_seed_validation_rejects_bad_entries(tmp_path: Path) -> None:
    path = tmp_path / "seed.json"
    path.write_text(
        '{"targets": [{"provider": "P", "service": "S", "category": "text",'
        ' "official_url": "http://example.com"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_seed_targets(path)

    path.write_text(
        '{"targets": [{"provider": "P", "service": "S", "category": "audio",'
        ' "official_url": "https://example.com"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_seed_targets(path)


def test_match_targets_uses_normalized_domain_and_category() -> None:
    targets = [
        _target(Category.IMAGE, "https://www.Example.com/pricing"),
        _target(Category.TEXT, "https://example.com/pricing"),
    ]
    policies = [
        Policy(
            provider="Example",
            service="Example Service",
            category=Category.IMAGE,
            provider_domain="https://EXAMPLE.com.",
        )
    ]

    rows = match_targets(targets, policies)

    assert rows[0]["covered"] is True
    assert rows[0]["service_matched"] is True
    # Same domain but the policy category does not match the text target.
    assert rows[1]["covered"] is False
    assert rows[1]["service_matched"] is False


def test_match_targets_reports_alias_service_match() -> None:
    targets = [_target(Category.RERANK)]
    policies = [
        Policy(
            provider="Example",
            service="Brand New Name",
            category=Category.RERANK,
            provider_domain="example.com",
            aliases=["example service"],
        )
    ]

    rows = match_targets(targets, policies)

    assert rows[0]["covered"] is True
    assert rows[0]["service_matched"] is True


def test_match_targets_matches_subdomains_in_both_directions() -> None:
    policies = [
        Policy(
            provider="OpenAI",
            service="OpenAI API",
            category=Category.TEXT,
            provider_domain="openai.com",
        ),
        Policy(
            provider="Claude",
            service="Claude API",
            category=Category.TEXT,
            provider_domain="docs.claude.com",
        ),
    ]
    targets = [
        _target(Category.TEXT, "https://platform.openai.com/pricing"),
        _target(Category.TEXT, "https://claude.com/pricing"),
    ]

    rows = match_targets(targets, policies)

    assert [row["covered"] for row in rows] == [True, True]


def test_match_targets_rejects_unrelated_domains() -> None:
    policies = [
        Policy(
            provider="OpenAI",
            service="OpenAI API",
            category=Category.TEXT,
            provider_domain="openai.com",
        )
    ]
    targets = [
        _target(Category.TEXT, "https://example.com/pricing"),
        _target(Category.TEXT, "https://notopenai.com/pricing"),
    ]

    rows = match_targets(targets, policies)

    assert [row["covered"] for row in rows] == [False, False]


def test_render_report_lists_all_categories_without_attribution() -> None:
    report = render_report(load_seed_targets(SEED_PATH), [], [], {})

    for label in CATEGORY_LABELS.values():
        assert label in report
    assert "## 来源归因" not in report
    assert "## 缺失目标" in report


def test_render_report_includes_attribution_counts() -> None:
    discoveries = [
        LeadDiscovery(
            url="https://new.example.org/image",
            category=Category.IMAGE,
            source_class="official-verifiable",
            origin="search",
        ),
        LeadDiscovery(
            url="https://new.example.org/image",
            category=Category.IMAGE,
            source_class="official-verifiable",
            origin="search",
        ),
        LeadDiscovery(
            url="https://other.example.net/tts",
            category=Category.SPEECH,
            source_class="discovery-only",
            origin="link",
        ),
    ]

    report = render_report([_target(Category.IMAGE)], [], discoveries, {})

    assert "## 来源归因" in report
    assert "| search | official-verifiable | 2 |" in report
    assert "| link | discovery-only | 1 |" in report
    assert "https://other.example.net/tts" in report


def test_main_dry_run_needs_no_network_or_model(tmp_path: Path, monkeypatch) -> None:
    class ExplodingResearcher:
        def __init__(self, *args, **kwargs):
            raise AssertionError("dry run must not construct the researcher")

    monkeypatch.setattr(research, "HarnessResearcher", ExplodingResearcher)

    config = tmp_path / "config.toml"
    config.write_text(
        'data_dir = "data"\nmodel = "openai:gpt-4.1-mini"\n'
        '[default_scope]\ncategories = ["text"]\nregion = "global"\n',
        encoding="utf-8",
    )
    out = tmp_path / "report.md"

    code = main(["--dry-run", "--config", str(config), "--out", str(out)])

    assert code == 0
    assert not out.exists()


def test_main_reports_collection_coverage_without_official_verification(
    tmp_path: Path, monkeypatch
) -> None:
    target = _target(Category.TEXT, "https://example.test/pricing")
    monkeypatch.setattr(coverage_eval, "load_seed_targets", lambda path: [target])

    class CollectionResearcher:
        last_discoveries: ClassVar[list] = []

        def __init__(self, *args, **kwargs):
            pass

        async def research(self, scope, existing):
            return ResearchBatch(
                messages=[
                    CollectedMessage(
                        policy=Policy(
                            provider="Example",
                            service="Example API",
                            category=Category.TEXT,
                            provider_domain="example.test",
                        ),
                        offer_key="example-free",
                        title="Example free API",
                        summary="Free API credits reported by the source.",
                        sources=[
                            MessageSource(
                                url="https://example.test/pricing",
                                excerpt="Free API credits are available.",
                            )
                        ],
                    )
                ]
            )

    monkeypatch.setattr(research, "HarnessResearcher", CollectionResearcher)
    config = tmp_path / "config.toml"
    config.write_text(
        'data_dir = "data"\nmodel = "openai:gpt-4.1-mini"\n'
        '[default_scope]\ncategories = ["text"]\nregion = "global"\n',
        encoding="utf-8",
    )
    out = tmp_path / "report.md"

    assert main(["--config", str(config), "--out", str(out)]) == 0

    report = out.read_text(encoding="utf-8")
    assert "- 研究产出记录: 1" in report
    assert "- 其中收集消息（未核验）: 1" in report
    assert "不代表官方政策核验通过" in report
    assert f"| {CATEGORY_LABELS[Category.TEXT]} (text) | 1 | 0 | 1 |" in report