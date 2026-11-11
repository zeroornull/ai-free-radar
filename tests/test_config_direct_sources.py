"""Direct source configuration: TOML-only allowlisted entry pages per category."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from aifreeradar.config import load_config_document


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_direct_sources_are_parsed_per_category(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
[direct_sources]
text = [
  "https://platform.openai.com/docs/pricing",
  "https://platform.openai.com/docs/models",
]
image = ["https://platform.openai.com/docs/guides/image-generation"]
""",
    )

    _, document, settings = load_config_document(path)

    expected = {
        "text": [
            "https://platform.openai.com/docs/pricing",
            "https://platform.openai.com/docs/models",
        ],
        "image": ["https://platform.openai.com/docs/guides/image-generation"],
    }
    assert document["direct_sources"] == expected
    assert settings.direct_sources == expected
    assert list(settings.direct_sources) == ["text", "image"]


def test_absent_direct_sources_keeps_other_defaults(tmp_path: Path) -> None:
    path = write_config(tmp_path, 'model = "openai:gpt-4.1-mini"\n')

    _, document, settings = load_config_document(path)

    assert "direct_sources" not in document
    assert settings.direct_sources == {}
    assert settings.model == "openai:gpt-4.1-mini"
    assert settings.port == 18765


def test_unknown_category_key_is_rejected(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[direct_sources]\nmusic = ["https://platform.openai.com/docs/pricing"]\n',
    )

    with pytest.raises(ValidationError, match="music"):
        load_config_document(path)


def test_non_http_url_is_rejected(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[direct_sources]\ntext = ["ftp://platform.openai.com/docs/pricing"]\n',
    )

    with pytest.raises(ValidationError, match="absolute HTTP"):
        load_config_document(path)


def test_credential_url_is_rejected(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[direct_sources]\ntext = ["https://user:secret@platform.openai.com/docs"]\n',
    )

    with pytest.raises(ValidationError, match="credentials"):
        load_config_document(path)


def test_duplicate_urls_collapse_to_one(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
[direct_sources]
text = [
  "https://platform.openai.com/docs/pricing",
  "https://platform.openai.com/docs/pricing",
  "https://platform.openai.com/docs/models",
]
""",
    )

    _, _, settings = load_config_document(path)

    assert settings.direct_sources["text"] == [
        "https://platform.openai.com/docs/pricing",
        "https://platform.openai.com/docs/models",
    ]