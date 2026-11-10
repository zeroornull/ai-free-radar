"""File-based configuration; credentials are read only from named environment variables."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import Category, Scope


class ConfigurationError(ValueError):
    """The configured research service cannot be used as requested."""


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Path("data")
    model: str = "openai:gpt-4.1-mini"
    model_base_url: str | None = None
    model_api_key_env: str = "OPENAI_API_KEY"
    model_api_key: str = ""
    search_provider: Literal["duckduckgo", "tavily", "brave", "exa"] = "duckduckgo"
    search_api_key_env: str = ""
    search_api_key: str = ""
    schedule_enabled: bool = True
    schedule_time: str = "09:00"
    default_scope: Scope = Field(default_factory=Scope)
    direct_sources: dict[str, list[str]] = Field(default_factory=dict)
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(default=8765, ge=1, le=65535)

    @field_validator("schedule_time")
    @classmethod
    def valid_schedule_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("schedule_time must be HH:MM in local time")
        return value

    @field_validator("model")
    @classmethod
    def supported_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model is required")
        provider, separator, name = value.partition(":")
        official = {"openai", "openai-chat", "openai-responses", "anthropic", "deepseek"}
        if separator and provider in official and not name.strip():
            raise ValueError("model name after the provider prefix is empty")
        if value.startswith("compatible:") and not value.removeprefix("compatible:").strip():
            raise ValueError("compatible: requires a model name after the prefix")
        return value

    @field_validator("model_base_url")
    @classmethod
    def valid_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.hostname:
            raise ValueError("model_base_url must be an explicit HTTP(S) service URL")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("model_base_url cannot contain credentials, query or fragment")
        return value

    @model_validator(mode="after")
    def compatible_endpoint_is_explicit(self) -> Self:
        if self.model_route()[0] == "compatible" and self.model_base_url is None:
            raise ValueError(
                "model_base_url is required unless model uses openai:, openai-chat:, "
                "openai-responses:, anthropic:, or deepseek:; an unprefixed name is not sent to OpenAI"
            )
        return self

    def model_route(self) -> tuple[str, str]:
        """Official prefixes select that client. Anything else is the compatible model id verbatim."""
        provider, separator, name = self.model.partition(":")
        official = {"openai", "openai-chat", "openai-responses", "anthropic", "deepseek"}
        if separator and provider in official:
            return provider, name
        if self.model.startswith("compatible:"):
            return "compatible", self.model.removeprefix("compatible:")
        return "compatible", self.model

    @field_validator("model_api_key_env", "search_api_key_env")
    @classmethod
    def valid_env_name(cls, value: str) -> str:
        if value and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
            raise ValueError("credential settings must name environment variables")
        return value

    @field_validator("direct_sources")
    @classmethod
    def valid_direct_sources(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        known = {category.value for category in Category}
        validated: dict[str, list[str]] = {}
        for category, urls in value.items():
            if category not in known:
                raise ValueError(
                    f"direct_sources key {category!r} must be one of "
                    f"{', '.join(sorted(known))}"
                )
            unique: list[str] = []
            for url in urls:
                if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in url):
                    raise ValueError(
                        f"direct_sources[{category}] URL contains control characters: {url!r}"
                    )
                try:
                    parsed = urlsplit(url)
                    hostname = parsed.hostname
                    port = parsed.port
                except ValueError as exc:
                    raise ValueError(
                        f"direct_sources[{category}] invalid URL: {url!r}"
                    ) from exc
                if parsed.scheme not in {"http", "https"} or not hostname:
                    raise ValueError(
                        f"direct_sources[{category}] must be an absolute HTTP(S) URL: {url!r}"
                    )
                if parsed.username or parsed.password:
                    raise ValueError(
                        f"direct_sources[{category}] URL cannot contain credentials: {url!r}"
                    )
                if port is not None:
                    default = 443 if parsed.scheme == "https" else 80
                    if port != default:
                        raise ValueError(
                            f"direct_sources[{category}] URL port must be {default}: {url!r}"
                        )
                if url not in unique:
                    unique.append(url)
            validated[category] = unique
        return validated

    def model_credential(self) -> str:
        key = self.model_api_key.strip() or os.environ.get(self.model_api_key_env, "").strip()
        if not key:
            where = f" or {self.model_api_key_env}" if self.model_api_key_env else ""
            raise ConfigurationError(f"Missing model credential: set model_api_key in config.toml{where}")
        return key

    def search_credential(self) -> str | None:
        if self.search_provider == "duckduckgo":
            return None
        key = self.search_api_key.strip() or os.environ.get(self.search_api_key_env, "").strip()
        if not key:
            where = f" or {self.search_api_key_env}" if self.search_api_key_env else ""
            raise ConfigurationError(
                f"Missing {self.search_provider} credential: set search_api_key in config.toml{where}"
            )
        return key

    def public_summary(self) -> dict:
        return {
            "model": self.model,
            "search_provider": self.search_provider,
            "schedule_enabled": self.schedule_enabled,
            "schedule_time": self.schedule_time,
            "default_scope": self.default_scope.model_dump(mode="json"),
            "host": self.host,
            "port": self.port,
        }


def load_config_document(
    path: Path | None = None,
) -> tuple[Path, dict[str, object], Settings]:
    """Load TOML plus the validated settings, returning the raw document unvalidated."""
    config_path = Path(path or os.environ.get("AIFREERADAR_CONFIG", "config.toml")).resolve()
    if (path is not None or os.environ.get("AIFREERADAR_CONFIG")) and not config_path.is_file():
        raise ConfigurationError(f"Configuration file not found: {config_path}")
    load_dotenv(config_path.parent / ".env", override=False)
    document = (
        tomllib.loads(config_path.read_text(encoding="utf-8")) if config_path.is_file() else {}
    )
    settings = Settings.model_validate(document)
    settings.data_dir = (config_path.parent / settings.data_dir).resolve()
    return config_path, document, settings


def load_settings(path: Path | None = None) -> Settings:
    _, _, settings = load_config_document(path)
    return settings
