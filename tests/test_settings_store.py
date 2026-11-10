"""Behavioral tests for the three-layer settings store and its SQLite persistence."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from aifreeradar.config import ConfigurationError, Settings
from aifreeradar.models import Category, Scope
from aifreeradar.settings_store import (
    SettingsConflictError,
    SettingsSecretUnavailableError,
    SettingsStore,
    SettingsWriteError,
)
from aifreeradar.storage import Repository

MASTER_ENV = "AIFREERADAR_SECRET_KEY"
MODEL_ENV = "OPENAI_API_KEY"
SPARE_ENV = "SPARE_API_KEY"

DOCUMENT: dict[str, object] = {
    "model": "openai:gpt-4.1-mini",
    "schedule_time": "08:30",
}
FIELDS = [
    "model",
    "model_base_url",
    "model_api_key_env",
    "model_api_key",
    "search_provider",
    "search_api_key_env",
    "search_api_key",
    "schedule_enabled",
    "schedule_time",
    "default_scope",
    "host",
    "port",
    "data_dir",
]


def master_key(seed: int = 7) -> str:
    """A deterministic 32-byte urlsafe base64 master key."""
    return base64.urlsafe_b64encode(bytes([seed]) * 32).decode("ascii")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove every credential variable the store reads so tests never see the developer env."""
    for name in (MASTER_ENV, MODEL_ENV, SPARE_ENV, "NEW_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def make_settings(data_dir: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "data_dir": data_dir,
        "model": "openai:gpt-4.1-mini",
        "model_api_key_env": MODEL_ENV,
        "schedule_time": "08:30",
        "default_scope": Scope(categories=[Category.TEXT], region="global"),
    }
    values.update(overrides)
    return Settings.model_validate(values)


def make_store(
    tmp_path: Path, **overrides: object
) -> tuple[Repository, SettingsStore, Settings, dict[str, object]]:
    data_dir = tmp_path / "data"
    repository = Repository(data_dir)
    settings = make_settings(data_dir, **overrides)
    document = dict(DOCUMENT)
    return repository, SettingsStore(repository, settings, document), settings, document


def test_describe_sources_shapes_and_read_only_fields(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    repository, store, settings, _ = make_store(tmp_path)

    version, fields = store.describe()

    assert version == 0
    assert version == store.version
    assert list(fields) == FIELDS
    # Present in the TOML document.
    assert fields["model"] == {"value": "openai:gpt-4.1-mini", "source": "toml"}
    assert fields["schedule_time"] == {"value": "08:30", "source": "toml"}
    # Absent everywhere: code default.
    assert fields["schedule_enabled"] == {"value": True, "source": "default"}
    assert fields["model_base_url"] == {"value": None, "source": "default"}
    assert fields["model_api_key_env"] == {"value": MODEL_ENV, "source": "default"}
    assert fields["default_scope"] == {
        "value": {"categories": ["text"], "region": "global", "resource_ids": []},
        "source": "default",
    }
    # Read-only fields expose the startup value and never a changeable source.
    assert fields["host"] == {"value": "127.0.0.1", "source": "read_only"}
    assert fields["port"] == {"value": 8765, "source": "read_only"}
    assert fields["data_dir"] == {"value": str(settings.data_dir), "source": "read_only"}
    # Secrets are never described by value.
    assert fields["model_api_key"] == {
        "value": None,
        "configured": False,
        "source": "missing",
    }
    assert fields["search_api_key"] == {
        "value": None,
        "configured": False,
        "source": "missing",
    }
    assert repository.settings_overrides() == {}


def test_db_override_changes_source_and_default_scope_is_json(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    _, store, _, _ = make_store(tmp_path)

    updated = store.update(
        {
            "schedule_time": "10:30",
            "default_scope": {
                "categories": ["image"],
                "region": "china",
                "resource_ids": ["res-1"],
            },
        },
        {},
        0,
    )

    assert updated.schedule_time == "10:30"
    assert updated.default_scope.region == "china"
    fields = store.describe()[1]
    assert fields["schedule_time"] == {"value": "10:30", "source": "db"}
    assert fields["default_scope"] == {
        "value": {"categories": ["image"], "region": "china", "resource_ids": ["res-1"]},
        "source": "db",
    }
    # Untouched TOML-backed fields keep their own source.
    assert fields["model"]["source"] == "toml"


def test_non_secret_override_persists_and_null_restores_toml(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    repository, store, settings, document = make_store(tmp_path)
    assert store.version == 0

    store.update({"schedule_time": "10:30"}, {}, 0)

    assert store.version == 1
    assert store.effective().schedule_time == "10:30"
    assert store.describe()[0] == 1

    reopened = SettingsStore(repository, settings, document)
    assert reopened.version == 1
    assert reopened.effective().schedule_time == "10:30"
    assert reopened.describe()[1]["schedule_time"] == {
        "value": "10:30",
        "source": "db",
    }

    # A null value deletes the override instead of storing null.
    reopened.update({"schedule_time": None}, {}, 1)

    assert reopened.version == 2
    assert repository.settings_overrides() == {}
    assert reopened.effective().schedule_time == "08:30"
    assert reopened.describe()[1]["schedule_time"] == {
        "value": "08:30",
        "source": "toml",
    }


def test_stale_update_and_reset_raise_without_writing(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    repository, store, _, _ = make_store(tmp_path)
    store.update({"schedule_time": "10:30"}, {}, 0)
    before_overrides = repository.settings_overrides()
    before_secrets = repository.settings_secret_rows()

    with pytest.raises(SettingsConflictError):
        store.update({"schedule_time": "11:00"}, {}, 0)
    with pytest.raises(SettingsConflictError):
        store.reset(["schedule_time"], 0)

    assert repository.settings_overrides() == before_overrides
    assert repository.settings_secret_rows() == before_secrets
    assert repository.settings_version() == 1

    # A concurrent writer through the repository bumps the version behind the store's back.
    repository.save_settings({"schedule_time": json.dumps("12:00")}, {}, 1)

    with pytest.raises(SettingsConflictError):
        store.update({"schedule_time": "13:00"}, {}, 1)
    assert repository.settings_overrides()["schedule_time"] == json.dumps("12:00")


@pytest.mark.parametrize(
    ("values", "secrets"),
    [
        ({"nope": 1}, {}),
        ({"host": "127.0.0.1"}, {}),
        ({"port": 9000}, {}),
        ({"data_dir": "elsewhere"}, {}),
        ({"model_api_key": "leak"}, {}),
        ({"model": "openai:gpt-4.1", "unknown": True}, {}),
        ({}, {"nope": "leak"}),
    ],
)
def test_unsupported_writes_are_rejected(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
    values: dict[str, object],
    secrets: dict[str, str | None],
) -> None:
    repository, store, _, _ = make_store(tmp_path)

    with pytest.raises(SettingsWriteError):
        store.update(values, secrets, 0)

    assert repository.settings_overrides() == {}
    assert repository.settings_secret_rows() == {}
    assert repository.settings_version() == 0


def test_secret_is_encrypted_at_rest_and_round_trips(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    repository, store, settings, document = make_store(tmp_path)

    store.update({}, {"model_api_key": "sk-db-secret"}, 0)

    rows = repository.settings_secret_rows()
    token = rows[MODEL_ENV]
    assert token.startswith("v1:")
    assert all("sk-db-secret" not in value for value in rows.values())

    assert store.effective().model_api_key == "sk-db-secret"
    version, fields = store.describe()
    assert version == 1
    assert fields["model_api_key"] == {
        "value": None,
        "configured": True,
        "source": "db",
    }
    assert "sk-db-secret" not in json.dumps(fields)

    reopened = SettingsStore(repository, settings, document)
    assert reopened.effective().model_api_key == "sk-db-secret"
    assert reopened.describe()[1]["model_api_key"] == {
        "value": None,
        "configured": True,
        "source": "db",
    }


def test_renamed_env_name_does_not_reuse_previous_secret(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    repository, store, settings, _ = make_store(tmp_path)
    assert settings.model_api_key_env == MODEL_ENV

    store.update({}, {"model_api_key": "old-secret"}, 0)
    assert store.effective().model_api_key == "old-secret"

    store.update({"model_api_key_env": "NEW_API_KEY"}, {}, 1)

    # The old ciphertext still exists, but it is stored under the old env name.
    assert repository.settings_secret_rows().keys() == {MODEL_ENV}
    assert store.effective().model_api_key == ""
    assert store.describe()[1]["model_api_key"] == {
        "value": None,
        "configured": False,
        "source": "missing",
    }

    store.update({}, {"model_api_key": "new-secret"}, 2)
    assert set(repository.settings_secret_rows()) == {MODEL_ENV, "NEW_API_KEY"}
    assert store.effective().model_api_key == "new-secret"
    assert store.describe()[1]["model_api_key"]["source"] == "db"


def test_clearing_secret_falls_back_to_toml_then_env(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    clean_env.setenv(MODEL_ENV, "env-key")
    repository, store, _, _ = make_store(tmp_path, model_api_key="toml-key")

    store.update({}, {"model_api_key": "db-key"}, 0)
    assert store.effective().model_api_key == "db-key"

    store.update({}, {"model_api_key": None}, 1)

    assert repository.settings_secret_rows() == {}
    assert store.effective().model_api_key == "toml-key"
    assert store.describe()[1]["model_api_key"] == {
        "value": None,
        "configured": True,
        "source": "toml",
    }

    # Without a TOML literal the named environment variable becomes the fallback.
    other_repository = Repository(tmp_path / "other")
    other_settings = make_settings(tmp_path / "other")
    other = SettingsStore(other_repository, other_settings, dict(DOCUMENT))

    other.update({}, {"model_api_key": "db-key"}, 0)
    other.update({}, {"model_api_key": None}, 1)

    assert other.effective().model_api_key == ""
    assert other.effective().model_credential() == "env-key"
    assert other.describe()[1]["model_api_key"] == {
        "value": None,
        "configured": True,
        "source": "env",
    }


def test_precedence_db_secret_beats_toml_literal_beats_env(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    clean_env.setenv(MODEL_ENV, "env-key")
    repository, store, settings, _ = make_store(tmp_path, model_api_key="toml-key")

    # TOML literal beats the environment variable even before any DB write.
    assert settings.model_credential() == "toml-key"

    store.update({}, {"model_api_key": "db-key"}, 0)
    assert store.effective().model_credential() == "db-key"

    store.update({}, {"model_api_key": None}, 1)
    assert store.effective().model_credential() == "toml-key"
    assert repository.settings_secret_rows() == {}


@pytest.mark.parametrize("raw", ["", "   "])
def test_empty_secret_is_rejected(
    tmp_path: Path, clean_env: pytest.MonkeyPatch, raw: str
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    repository, store, _, _ = make_store(tmp_path)

    with pytest.raises(SettingsWriteError):
        store.update({}, {"model_api_key": raw}, 0)

    assert repository.settings_overrides() == {}
    assert repository.settings_secret_rows() == {}


def test_secret_without_env_name_is_rejected(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    repository, store, _, _ = make_store(tmp_path)

    with pytest.raises(SettingsWriteError):
        store.update({"model_api_key_env": ""}, {"model_api_key": "db-key"}, 0)

    assert repository.settings_overrides() == {}
    assert repository.settings_secret_rows() == {}


def test_secret_write_without_master_key_is_unavailable(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    repository, store, _, _ = make_store(tmp_path)

    with pytest.raises(SettingsSecretUnavailableError):
        store.update({}, {"model_api_key": "db-key"}, 0)

    assert repository.settings_overrides() == {}
    assert repository.settings_secret_rows() == {}


def test_startup_requires_master_key_when_secret_rows_exist(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    repository, store, settings, document = make_store(tmp_path)
    store.update({}, {"model_api_key": "db-key"}, 0)

    clean_env.delenv(MASTER_ENV)
    with pytest.raises(ConfigurationError):
        SettingsStore(repository, settings, document)

    clean_env.setenv(MASTER_ENV, master_key(seed=8))
    with pytest.raises(ConfigurationError):
        SettingsStore(repository, settings, document)

    clean_env.setenv(MASTER_ENV, master_key())
    assert SettingsStore(repository, settings, document).effective().model_api_key == "db-key"


def test_startup_without_secret_rows_needs_no_master_key(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    repository, _, settings, document = make_store(tmp_path)

    store = SettingsStore(repository, settings, document)

    assert store.effective().model == "openai:gpt-4.1-mini"
    assert store.describe()[1]["model_api_key"]["source"] == "missing"


def test_reset_removes_override_and_secret_and_restores_toml(
    tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    clean_env.setenv(MASTER_ENV, master_key())
    clean_env.setenv(MODEL_ENV, "env-key")
    repository, store, _, _ = make_store(tmp_path, model_api_key="toml-key")

    store.update({"model": "openai:gpt-4.1"}, {"model_api_key": "db-key"}, 0)
    assert store.describe()[1]["model"]["source"] == "db"
    assert store.describe()[1]["model_api_key"]["source"] == "db"

    store.reset(["model", "model_api_key"], 1)

    assert store.version == 2
    assert repository.settings_overrides() == {}
    assert repository.settings_secret_rows() == {}
    fields = store.describe()[1]
    assert fields["model"] == {"value": "openai:gpt-4.1-mini", "source": "toml"}
    assert fields["model_api_key"] == {
        "value": None,
        "configured": True,
        "source": "toml",
    }
    assert store.effective().model == "openai:gpt-4.1-mini"
    assert store.effective().model_api_key == "toml-key"
