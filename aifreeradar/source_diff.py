"""Deterministic text and link comparisons for versioned source snapshots."""

from __future__ import annotations

import difflib

DIFF_LINE_LIMIT = 400


def text_diff(before: str, after: str, *, max_lines: int = DIFF_LINE_LIMIT) -> str:
    """Unified diff of two normalized texts, capped with an explicit truncation marker."""
    lines = list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile="上一版",
            tofile="当前版",
            lineterm="",
            n=2,
        )
    )
    if len(lines) > max_lines:
        omitted = len(lines) - max_lines
        lines = [*lines[:max_lines], f"… 差异过长，已省略 {omitted} 行（原文完整保留）"]
    return "\n".join(lines)


def link_changes(before: list[str], after: list[str]) -> tuple[list[str], list[str]]:
    """Return added and removed public links preserving their observed order."""
    previous = set(before)
    current = set(after)
    added = [link for link in after if link not in previous]
    removed = [link for link in before if link not in current]
    return added, removed