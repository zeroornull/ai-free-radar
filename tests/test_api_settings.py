"""HTTP acceptance tests for runtime settings, without network or real credentials."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from aifreeradar import api as api_module
from aifreeradar.config import Settings
from aifreeradar.models import Category, ResearchBatch
from aifreeradar.probes import SettingsProbeError
from aifreeradar.web import create_app

SETTINGS_FIELDS = {
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
}
PLAINTEXT_SECRET = "sk-db-plaintext-never-returned"
CHINA_SCOPE = {"categories": ["image"], "region": "china", "resource_ids": []}
DEFAULT_SCOPE = {
    "categories": [category.value for category in Category],
    "region": "global",
    "resource_ids": [],
}
ENV_SECRET = "sk-env-fallback-never-returned"
TOML_SECRET = "sk-toml-fallback-never-returned"


class IdleResearcher:
    async def research(self, scope, existing):
        return ResearchBatch()


@pytest.fixture(autouse=True)
def clean_credentials(monkeypatch):
    for name in (
        "AIFREERADAR_SECRET_KEY",
        "OPENAI_API_KEY",
        "AIFREE_TEST_MODEL_KEY",
        "AIFREE_TEST_SEARCH_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def set_master_key(monkeypatch):
    monkeypatch.setenv(
        "AIFREERADAR_SECRET_KEY", base64.urlsafe_b64encode(b"s" * 32).decode("ascii")
    )


def make_app(data_dir, *, schedule_enabled=False, schedule_time="07:30", model_api_key=""):
    settings = Settings(
        data_dir=data_dir,
        schedule_enabled=schedule_enabled,
        schedule_time=schedule_time,
        model_api_key=model_api_key,
    )
    document = {
        "model": settings.model,
        "schedule_enabled": schedule_enabled,
        "schedule_time": schedule_time,
    }
    return create_app(settings, researcher=IdleResearcher(), config_document=document)


def current_version(client):
    response = client.get("/api/settings")
    assert response.status_code == 200, response.text
    return response.json()["version"]


def test_get_settings_lists_all_fields_with_sources_and_no_secret_plaintext(tmp_path, monkeypatch):
    set_master_key(monkeypatch)
    with TestClient(make_app(tmp_path)) as client:
        body = client.get("/api/settings").json()
        fields = body["fields"]
        assert isinstance(body["version"], int)
        assert set(fields) == SETTINGS_FIELDS

        assert fields["model"]["value"] == "openai:gpt-4.1-mini"
        assert fields["model"]["source"] == "toml"
        assert fields["schedule_time"]["value"] == "07:30"
        assert fields["schedule_time"]["source"] == "toml"
        assert fields["schedule_enabled"]["value"] is False
        assert fields["schedule_enabled"]["source"] == "toml"
        assert fields["search_provider"]["value"] == "duckduckgo"
        assert fields["search_provider"]["source"] == "default"
        assert fields["default_scope"]["value"] == {
            "categories": [category.value for category in Category],
            "region": "global",
            "resource_ids": [],
        }
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
        for name in ("host", "port", "data_dir"):
            assert fields[name]["source"] == "read_only"

        version = body["version"]
        response = client.patch(
            "/api/settings",
            json={"version": version, "secrets": {"model_api_key": PLAINTEXT_SECRET}},
        )
        assert response.status_code == 200, response.text
        assert PLAINTEXT_SECRET not in response.text
        after = client.get("/api/settings")
        assert PLAINTEXT_SECRET not in after.text
        secret = after.json()["fields"]["model_api_key"]
        assert secret["value"] is None
        assert secret["configured"] is True
        assert secret["source"] == "db"


def test_patch_persists_across_app_instances_and_updates_app_view(tmp_path, monkeypatch):
    with TestClient(make_app(tmp_path)) as client:
        before = client.get("/api/settings").json()
        response = client.patch(
            "/api/settings",
            json={
                "version": before["version"],
                "values": {
                    "schedule_enabled": True,
                    "schedule_time": "06:15",
                    "default_scope": CHINA_SCOPE,
                },
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["version"] == before["version"] + 1
        fields = body["fields"]
        assert fields["schedule_enabled"]["value"] is True
        assert fields["schedule_enabled"]["source"] == "db"
        assert fields["schedule_time"]["value"] == "06:15"
        assert fields["schedule_time"]["source"] == "db"
        assert fields["default_scope"]["value"] == CHINA_SCOPE
        assert fields["default_scope"]["source"] == "db"

        app_view = client.get("/api/app").json()
        assert app_view["schedule_enabled"] is True
        assert app_view["schedule_time"] == "06:15"
        assert app_view["default_scope"] == CHINA_SCOPE

    # A second process reads the same data directory, not its own TOML document.
    with TestClient(make_app(tmp_path)) as client:
        body = client.get("/api/settings").json()
        assert body["version"] == before["version"] + 1
        fields = body["fields"]
        assert fields["schedule_enabled"]["value"] is True
        assert fields["schedule_enabled"]["source"] == "db"
        assert fields["schedule_time"]["value"] == "06:15"
        assert fields["default_scope"]["value"] == CHINA_SCOPE
        assert fields["default_scope"]["source"] == "db"

        app_view = client.get("/api/app").json()
        assert app_view["schedule_enabled"] is True
        assert app_view["schedule_time"] == "06:15"
        assert app_view["default_scope"] == CHINA_SCOPE

        rewritten = client.patch(
            "/api/settings",
            json={"version": body["version"], "values": {"schedule_time": "05:00"}},
        )
        assert rewritten.status_code == 200, rewritten.text
        assert rewritten.json()["version"] == body["version"] + 1
        assert rewritten.json()["fields"]["schedule_time"] == {
            "value": "05:00",
            "configured": False,
            "source": "db",
        }


def test_settings_conflicts_and_rejected_values_do_not_write(tmp_path, monkeypatch):
    with TestClient(make_app(tmp_path)) as client:
        stale = current_version(client)
        first = client.patch(
            "/api/settings",
            json={"version": stale, "values": {"schedule_time": "06:45"}},
        )
        assert first.status_code == 200, first.text
        assert first.json()["version"] == stale + 1
        assert first.json()["fields"]["schedule_time"]["value"] == "06:45"

        conflict = client.patch(
            "/api/settings",
            json={"version": stale, "values": {"schedule_time": "06:50"}},
        )
        remaining = client.get("/api/settings").json()
        assert conflict.status_code == 409, conflict.text
        assert remaining["version"] == stale + 1
        assert remaining["fields"]["schedule_time"]["value"] == "06:45"

        for values in (
            {"schedule_time": "25:00"},
            {"data_dir": str(tmp_path / "elsewhere")},
            {"unknown_field": "value"},
        ):
            rejected = client.patch(
                "/api/settings", json={"version": remaining["version"], "values": values}
            )
            assert rejected.status_code == 422, rejected.text
        assert current_version(client) == remaining["version"]
        assert client.get("/api/settings").json()["fields"]["schedule_time"]["value"] == "06:45"


def test_secret_write_requires_master_key_and_rejects_empty_value(tmp_path, monkeypatch):
    monkeypatch.delenv("AIFREERADAR_SECRET_KEY", raising=False)
    with TestClient(make_app(tmp_path)) as client:
        version = current_version(client)
        unavailable = client.patch(
            "/api/settings",
            json={"version": version, "secrets": {"model_api_key": PLAINTEXT_SECRET}},
        )
        assert unavailable.status_code == 503, unavailable.text
        assert PLAINTEXT_SECRET not in unavailable.text
        assert current_version(client) == version
        assert client.get("/api/settings").json()["fields"]["model_api_key"] == {
            "value": None,
            "configured": False,
            "source": "missing",
        }

        empty = client.patch(
            "/api/settings",
            json={"version": version, "secrets": {"model_api_key": ""}},
        )
        assert empty.status_code == 422, empty.text
        assert current_version(client) == version


def test_cleared_secret_falls_back_to_environment_then_toml(tmp_path, monkeypatch):
    set_master_key(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", ENV_SECRET)

    with TestClient(make_app(tmp_path / "env")) as client:
        version = current_version(client)
        stored = client.patch(
            "/api/settings",
            json={"version": version, "secrets": {"model_api_key": PLAINTEXT_SECRET}},
        )
        assert stored.status_code == 200, stored.text
        assert stored.json()["fields"]["model_api_key"] == {
            "value": None,
            "configured": True,
            "source": "db",
        }
        assert PLAINTEXT_SECRET not in stored.text

        cleared = client.patch(
            "/api/settings",
            json={"version": stored.json()["version"], "secrets": {"model_api_key": None}},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["version"] == stored.json()["version"] + 1
        # Without a TOML literal the named environment variable is the fallback.
        assert cleared.json()["fields"]["model_api_key"] == {
            "value": None,
            "configured": True,
            "source": "env",
        }
        assert PLAINTEXT_SECRET not in cleared.text
        assert ENV_SECRET not in cleared.text

    with TestClient(make_app(tmp_path / "toml", model_api_key=TOML_SECRET)) as client:
        version = current_version(client)
        stored = client.patch(
            "/api/settings",
            json={"version": version, "secrets": {"model_api_key": PLAINTEXT_SECRET}},
        )
        assert stored.status_code == 200, stored.text
        cleared = client.patch(
            "/api/settings",
            json={"version": stored.json()["version"], "secrets": {"model_api_key": None}},
        )
        assert cleared.status_code == 200, cleared.text
        # A TOML literal outranks the environment variable.
        assert cleared.json()["fields"]["model_api_key"] == {
            "value": None,
            "configured": True,
            "source": "toml",
        }
        assert PLAINTEXT_SECRET not in cleared.text
        assert TOML_SECRET not in cleared.text
        assert ENV_SECRET not in cleared.text


def test_reset_restores_toml_and_default_sources_and_removes_secret(tmp_path, monkeypatch):
    set_master_key(monkeypatch)
    with TestClient(make_app(tmp_path)) as client:
        version = current_version(client)
        written = client.patch(
            "/api/settings",
            json={
                "version": version,
                "values": {"schedule_time": "06:00", "default_scope": CHINA_SCOPE},
                "secrets": {"model_api_key": PLAINTEXT_SECRET},
            },
        )
        assert written.status_code == 200, written.text
        body = written.json()
        written_version = body["version"]
        assert body["fields"]["schedule_time"]["value"] == "06:00"
        assert body["fields"]["schedule_time"]["source"] == "db"
        assert body["fields"]["default_scope"]["value"] == CHINA_SCOPE
        assert body["fields"]["default_scope"]["source"] == "db"
        assert body["fields"]["model_api_key"]["source"] == "db"
        assert PLAINTEXT_SECRET not in written.text

        reset = client.post(
            "/api/settings/reset",
            json={
                "version": written_version,
                "keys": ["schedule_time", "default_scope", "model_api_key"],
            },
        )
        assert reset.status_code == 200, reset.text
        body = reset.json()
        assert body["version"] == written_version + 1
        fields = body["fields"]
        assert fields["schedule_time"]["value"] == "07:30"
        assert fields["schedule_time"]["source"] == "toml"
        assert fields["default_scope"]["value"] == DEFAULT_SCOPE
        assert fields["default_scope"]["source"] == "default"
        assert fields["model_api_key"] == {
            "value": None,
            "configured": False,
            "source": "missing",
        }
        assert PLAINTEXT_SECRET not in reset.text
        assert client.get("/api/settings").json() == body

    # Removing the master key proves the reset deleted the stored ciphertext:
    # a surviving secret row would refuse to initialize the store.
    monkeypatch.delenv("AIFREERADAR_SECRET_KEY")
    with TestClient(make_app(tmp_path)) as reopened:
        assert current_version(reopened) == body["version"]
        assert reopened.get("/api/settings").json()["fields"]["model_api_key"]["source"] == "missing"


def test_settings_probe_requires_valid_target_and_returns_detail(tmp_path, monkeypatch):
    async def fake_model(settings):
        assert settings.model_api_key_env == "OPENAI_API_KEY"
        return "模型服务可用（openai:gpt-4.1-mini）。"

    async def fake_search(settings):
        return "搜索服务可用，返回 3 条结果。"

    monkeypatch.setattr(api_module, "probe_model", fake_model)
    monkeypatch.setattr(api_module, "probe_search", fake_search)
    with TestClient(make_app(tmp_path)) as client:
        model = client.post("/api/settings/test", json={"target": "model"})
        assert model.status_code == 200, model.text
        assert model.json() == {
            "ok": True,
            "detail": "模型服务可用（openai:gpt-4.1-mini）。",
        }

        search = client.post("/api/settings/test", json={"target": "search"})
        assert search.status_code == 200, search.text
        assert search.json() == {
            "ok": True,
            "detail": "搜索服务可用，返回 3 条结果。",
        }

        invalid = client.post("/api/settings/test", json={"target": "image"})
        assert invalid.status_code == 422, invalid.text


def test_settings_probe_failure_is_502_without_key_material(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", PLAINTEXT_SECRET)

    async def failing_probe(settings):
        raise SettingsProbeError(
            f"模型端点返回 HTTP 401（{settings.model_api_key_env}={PLAINTEXT_SECRET}）"
        )

    monkeypatch.setattr(api_module, "probe_model", failing_probe)
    with TestClient(make_app(tmp_path)) as client:
        response = client.post("/api/settings/test", json={"target": "model"})
        assert response.status_code == 502, response.text
        assert response.json()["detail"] == (
            "模型端点返回 HTTP 401（OPENAI_API_KEY=[密钥已隐藏]）"
        )
        assert PLAINTEXT_SECRET not in response.text