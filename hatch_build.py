"""Hatch build hook: fail the wheel when the Vue frontend output is missing.

The Vue build writes its production bundle to ``aifreeradar/static/app``
(Vite ``build.outDir``). A wheel that cannot serve that output is unusable, so
this hook refuses to package it. The check runs only for the wheel target; the
sdist deliberately carries the raw frontend sources and build output (when
present) instead.

This hook runs no ``pnpm``/Node step and installs nothing: it only inspects
files already present in the tree. Building a wheel from a sdist that already
contains the assets therefore has no Node requirement.
"""

from __future__ import annotations

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import (  # pyright: ignore[reportMissingImports]
    BuildHookInterface,
)


class CustomBuildHook(BuildHookInterface):
    """Verify the packaged SPA entry and assets exist before building."""

    def initialize(self, version: str, build_data: dict) -> None:
        app = Path(self.root) / "aifreeradar" / "static" / "app"
        index = app / "index.html"
        assets = app / "assets"
        has_js = any(app.rglob("*.js"))
        has_css = any(app.rglob("*.css"))
        if not (index.is_file() and assets.is_dir() and has_js and has_css):
            raise RuntimeError("前端尚未构建，请先运行 pnpm --dir frontend build。")