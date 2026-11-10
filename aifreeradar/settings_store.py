"""Runtime settings: three authoritative layers (code < TOML < database overrides).

Secrets live only in the database, encrypted with AES-256-GCM under a master key
read from ``AIFREERADAR_SECRET_KEY``. Plaintext keys never leave this module.
"""

from __future__ import annotations

import base64
import json
import os
import threading
from collections.abc import Mapping

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .config import ConfigurationError, Settings
from .storage import Repository, SettingsVersionConflict

_AAD_PREFIX = "aifreeradar.settings."
_SECRET_ENV = "AIFREERADAR_SECRET_KEY"

# Presentation order for describe().
_FIELD_ORDER = (
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
)
_SECRET_FIELDS = ("model_api_key", "search_api_key")
_READ_ONLY = ("host", "port", "data_dir")
_EDITABLE_NON_SECRET = (
    "model",
    "model_base_url",
    "model_api_key_env",
    "search_provider",
    "search_api_key_env",
    "schedule_enabled",
    "schedule_time",
    "default_scope",
)


class SettingsConflictError(Exception):
    """The caller edited a stale settings version."""


class SettingsWriteError(ValueError):
    """The requested settings change is not permitted."""


class SettingsSecretUnavailableError(RuntimeError):
    """Secrets cannot be encrypted because the master key is missing or invalid."""


def _aad(name: str) -> bytes:
    return f"{_AAD_PREFIX}{name}.v1".encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class SettingsStore:
    """Merge TOML settings, database overrides, and encrypted database secrets."""

    def __init__(
        self,
        repository: Repository,
        settings: Settings,
        document: dict[str, object],
    ) -> None:
        self._repository = repository
        self._base = settings
        self._document = document
        self._lock = threading.Lock()
        self._version = -1
        self._effective_cache: Settings | None = None
        self._describe_cache: tuple[int, dict[str, dict[str, object]]] | None = None
        secret_rows = self._repository.settings_secret_rows()
        if secret_rows:
            if self._master_key() is None:
                raise ConfigurationError(
                    "Stored settings secrets require AIFREERADAR_SECRET_KEY to be a "
                    "32-byte urlsafe base64 key"
                )
            try:
                for name, token in secret_rows.items():
                    self._decrypt(name, token)
            except Exception as error:
                raise ConfigurationError(
                    "Stored settings secrets cannot be decrypted with AIFREERADAR_SECRET_KEY"
                ) from error

    # -- public API ---------------------------------------------------------

    @property
    def version(self) -> int:
        return self._repository.settings_version()

    def effective(self) -> Settings:
        with self._lock:
            self._refresh()
            if self._effective_cache is None:
                self._effective_cache = self._build_effective()
            return self._effective_cache.model_copy(deep=True)

    def describe(self) -> tuple[int, dict[str, dict[str, object]]]:
        with self._lock:
            self._refresh()
            if self._describe_cache is None:
                merged = self._merged_base()
                overrides = self._repository.settings_overrides()
                rows = self._repository.settings_secret_rows()
                fields = {
                    name: self._describe_field(name, merged, overrides, rows)
                    for name in _FIELD_ORDER
                }
                self._describe_cache = (self._version, fields)
            return self._describe_cache

    def update(
        self,
        values: dict[str, object],
        secrets: dict[str, str | None],
        version: int,
    ) -> Settings:
        with self._lock:
            self._refresh()
            self._require_version(version)
            self._validate_keys(values, secrets)

            overrides = self._json_overrides()
            base_values = self._base.model_dump(mode="json")
            merged = self._merged_base()
            for name, value in values.items():
                # null means "delete the override": validate the fallback value.
                merged[name] = base_values[name] if value is None else value

            # Validate the post-write configuration before persisting anything.
            candidate = dict(merged)
            candidate["data_dir"] = self._base.data_dir
            Settings.model_validate(candidate)

            new_overrides: dict[str, str | None] = {
                name: json.dumps(value, ensure_ascii=False)
                for name, value in overrides.items()
            }
            for name, value in values.items():
                if value is None:
                    new_overrides[name] = None
                else:
                    new_overrides[name] = json.dumps(value, ensure_ascii=False)

            secret_writes: dict[str, str | None] = {}
            for name in _SECRET_FIELDS:
                if name not in secrets:
                    continue
                env_name = self._env_name(merged, name)
                raw = secrets[name]
                if raw is None:
                    secret_writes[env_name] = None
                    continue
                if not isinstance(raw, str) or not raw.strip():
                    raise SettingsWriteError(f"{name} must be a non-empty string or null")
                if not env_name:
                    raise SettingsWriteError(
                        f"{name} cannot be stored while {name}_env names no environment variable"
                    )
                secret_writes[env_name] = self._encrypt(env_name, raw)

            self._persist(new_overrides, secret_writes, version)
            return self._build_effective()

    def reset(self, keys: list[str], version: int) -> Settings:
        with self._lock:
            self._refresh()
            self._require_version(version)
            unknown = [
                key
                for key in keys
                if key not in _EDITABLE_NON_SECRET and key not in _SECRET_FIELDS
            ]
            if unknown:
                raise SettingsWriteError(f"cannot reset non-editable settings: {sorted(unknown)}")

            delete_overrides = {key: None for key in keys if key in _EDITABLE_NON_SECRET}
            merged = self._merged_base()
            delete_secrets: dict[str, str | None] = {
                self._env_name(merged, key): None for key in keys if key in _SECRET_FIELDS
            }

            self._persist(delete_overrides, delete_secrets, version)
            return self._build_effective()

    # -- persistence --------------------------------------------------------

    def _persist(
        self,
        overrides: Mapping[str, str | None],
        secrets: Mapping[str, str | None],
        version: int,
    ) -> None:
        try:
            new_version = self._repository.save_settings(overrides, secrets, version)
        except SettingsVersionConflict as error:
            raise SettingsConflictError(
                "settings changed concurrently; reload and retry"
            ) from error
        self._version = new_version
        self._effective_cache = None
        self._describe_cache = None

    def _require_version(self, version: int) -> None:
        if version != self._version:
            raise SettingsConflictError("stale settings version; reload and retry")

    def _refresh(self) -> None:
        version = self._repository.settings_version()
        if version != self._version:
            self._version = version
            self._effective_cache = None
            self._describe_cache = None

    # -- merge helpers ------------------------------------------------------

    def _json_overrides(self) -> dict[str, object]:
        return {
            key: json.loads(value)
            for key, value in self._repository.settings_overrides().items()
        }

    def _merged_base(self) -> dict[str, object]:
        merged: dict[str, object] = self._base.model_dump(mode="json")
        merged.update(self._json_overrides())
        merged["data_dir"] = self._base.data_dir
        return merged

    def _env_name(self, merged: Mapping[str, object], secret_field: str) -> str:
        return str(merged.get(f"{secret_field}_env") or "")

    def _build_effective(self) -> Settings:
        merged = self._merged_base()
        rows = self._repository.settings_secret_rows()
        for name in _SECRET_FIELDS:
            env_name = self._env_name(merged, name)
            ciphertext = rows.get(env_name)
            if ciphertext is not None:
                merged[name] = self._decrypt(env_name, ciphertext)
        return Settings.model_validate(merged)

    def _validate_keys(
        self, values: Mapping[str, object], secrets: Mapping[str, str | None]
    ) -> None:
        unknown = [key for key in values if key not in _EDITABLE_NON_SECRET]
        if unknown:
            raise SettingsWriteError(
                f"settings are not editable via values: {sorted(unknown)}"
            )
        unknown_secrets = [key for key in secrets if key not in _SECRET_FIELDS]
        if unknown_secrets:
            raise SettingsWriteError(f"unknown secret fields: {sorted(unknown_secrets)}")

    def _describe_field(
        self,
        name: str,
        merged: Mapping[str, object],
        overrides: Mapping[str, str],
        rows: Mapping[str, str],
    ) -> dict[str, object]:
        if name in _READ_ONLY:
            return {"value": self._base.model_dump(mode="json").get(name), "source": "read_only"}
        if name in _SECRET_FIELDS:
            env_name = self._env_name(merged, name)
            if env_name and rows.get(env_name) is not None:
                source = "db"
            elif str(getattr(self._base, name)).strip():
                source = "toml"
            elif env_name and os.environ.get(env_name, "").strip():
                source = "env"
            else:
                source = "missing"
            return {"value": None, "configured": source != "missing", "source": source}
        if name in overrides:
            source = "db"
        elif name in self._document:
            source = "toml"
        else:
            source = "default"
        return {"value": merged.get(name), "source": source}

    # -- secret key handling ------------------------------------------------

    @staticmethod
    def _master_key() -> bytes | None:
        raw = os.environ.get(_SECRET_ENV, "").strip()
        if not raw:
            return None
        try:
            key = _unb64(raw)
        except (ValueError, TypeError):
            return None
        return key if len(key) == 32 else None

    def _encrypt(self, name: str, plaintext: str) -> str:
        key = self._master_key()
        if key is None:
            raise SettingsSecretUnavailableError(
                "AIFREERADAR_SECRET_KEY must be a 32-byte urlsafe base64 key to store secrets"
            )
        nonce = os.urandom(12)
        encryptor = Cipher(
            algorithms.AES(key), modes.GCM(nonce), backend=default_backend()
        ).encryptor()
        encryptor.authenticate_additional_data(_aad(name))
        ciphertext = encryptor.update(plaintext.encode("utf-8")) + encryptor.finalize()
        return f"v1:{_b64(nonce + ciphertext + encryptor.tag)}"

    def _decrypt(self, name: str, token: str) -> str:
        key = self._master_key()
        if key is None:
            raise SettingsSecretUnavailableError(
                "AIFREERADAR_SECRET_KEY must be a 32-byte urlsafe base64 key to read secrets"
            )
        try:
            version, payload = token.split(":", 1)
            if version != "v1":
                raise ValueError("unsupported secret version")
            blob = _unb64(payload)
            nonce, body = blob[:12], blob[12:]
            ciphertext, tag = body[:-16], body[-16:]
            decryptor = Cipher(
                algorithms.AES(key), modes.GCM(nonce, tag), backend=default_backend()
            ).decryptor()
            decryptor.authenticate_additional_data(_aad(name))
            return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")
        except Exception as error:
            raise ValueError(f"stored settings secret for {name} could not be decrypted") from error


__all__ = [
    "SettingsConflictError",
    "SettingsSecretUnavailableError",
    "SettingsStore",
    "SettingsWriteError",
]