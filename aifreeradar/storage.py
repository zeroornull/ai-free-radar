"""SQLite business records; research memory is deliberately not an identity database."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from .models import (
    UNKNOWN,
    Category,
    Change,
    CheckStatus,
    ChinaPolicy,
    Evidence,
    FreeType,
    LeadDiscovery,
    Policy,
    ResearchBatch,
    Resource,
    ResourceReview,
    ResourceStatus,
    ReviewAction,
    ReviewState,
    Run,
    UserAction,
    aware_utc,
    eligible_recommendation,
    normalize_domain,
    utc_now,
)

# These are facts, rather than presentation, identity labels, or observation times.
IMPORTANT_FIELDS = (
    "category",
    "models",
    "free_type",
    "quota",
    "quota_unit",
    "refresh_cycle",
    "rate_limit",
    "claim_conditions",
    "payment_required",
    "payment_method_required",
    "expires_at",
    "expiry_notes",
    "region_restrictions",
    "china_policy",
    "status",
)


def _known(value: str) -> bool:
    return bool(value.strip()) and value.strip() not in {UNKNOWN, "未核实", "未知", "unknown"}


def _token(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def _service_tokens(policy: Policy) -> set[str]:
    # Entry URLs are often shared across different APIs. They never identify a service.
    return {
        _token(value)
        for value in [policy.service_key, policy.service, *policy.aliases]
        if value and "://" not in value and _token(value)
    }


def _same_service(left: Policy, right: Policy) -> bool:
    if left.service_key and right.service_key:
        if left.service_key == right.service_key:
            return True
        # Distinct stable keys do not merge merely because both display names
        # happen to be "API". A rename must explicitly carry an old alias.
        left_aliases = {_token(value) for value in left.aliases if "://" not in value}
        right_aliases = {_token(value) for value in right.aliases if "://" not in value}
        key_alias = (
            _token(right.service_key) in left_aliases or _token(left.service_key) in right_aliases
        )
        renamed_alias = _token(left.service) != _token(right.service) and (
            _token(right.service) in left_aliases or _token(left.service) in right_aliases
        )
        return key_alias or renamed_alias
    return bool(_service_tokens(left) & _service_tokens(right))


def _official(evidence: Evidence, domain: str, now: datetime) -> bool:
    if evidence.source_type != "official" or not domain or not evidence.quote.strip():
        return False
    try:
        parsed = urlsplit(evidence.url)
        host = normalize_domain(parsed.hostname or "")
        declared = normalize_domain(evidence.official_domain or domain)
        return (
            parsed.scheme in {"http", "https"}
            and not parsed.username
            and not parsed.password
            and bool(host)
            and (host == domain or host.endswith(f".{domain}"))
            and (declared == domain or declared.endswith(f".{domain}"))
            and (host == declared or host.endswith(f".{declared}"))
            and evidence.checked_at <= now
        )
    except (ValueError, UnicodeError):
        return False


def validate_policy(policy: Policy, now: datetime) -> Policy:
    """Enforce official, field-specific policy evidence independently of model judgment.

    Retrieval/quotation provenance is checked by the research adapter. This boundary
    also checks URL ownership, so a self-declared official_domain cannot bless an
    unrelated community URL.
    """
    now = aware_utc(now)
    result = policy.model_copy(deep=True)
    result.evidence = [
        item
        for item in result.evidence
        if item.source_type == "community" or _official(item, result.provider_domain, now)
    ]
    official_fields = {
        item.field.strip()
        for item in result.evidence
        if _official(item, result.provider_domain, now)
    }
    problems: list[str] = []
    if not result.provider_domain:
        problems.append("缺少提供商官方域名")
    if result.china_policy != ChinaPolicy.UNKNOWN and not (
        {"china_policy", "region_restrictions"} & official_fields
    ):
        result.china_policy = ChinaPolicy.UNKNOWN
        problems.append("中国大陆政策缺少官方地区依据")

    # Only a confirmed expiry or explicit official shutdown can establish expiry.
    confirmed_expiry = (
        result.expires_at is not None
        and "expires_at" in official_fields
        and result.expires_at <= now
    )
    confirmed_shutdown = result.status == ResourceStatus.EXPIRED and "status" in official_fields
    if confirmed_expiry or confirmed_shutdown:
        result.status = ResourceStatus.EXPIRED
        result.failure_reason = "; ".join(filter(None, [result.failure_reason, *problems]))
        return result

    if result.status == ResourceStatus.EXPIRED:
        problems.append("失效结论缺少官方依据或已确认到期事实")
    required = {
        "free_type",
        "quota",
        "quota_unit",
        "claim_conditions",
        "payment_required",
        "payment_method_required",
    }
    if not ({"api_url", "docs_url"} & official_fields) or not any(
        _known(value) and _valid_http(value) for value in [result.api_url, result.docs_url]
    ):
        problems.append("缺少可接入 API 的官方入口或文档依据")
    if result.free_type == FreeType.ONGOING:
        required.add("refresh_cycle")
        if not _known(result.refresh_cycle):
            problems.append("刷新周期未说明")
    elif result.free_type == FreeType.LIMITED:
        absolute_expiry = result.expires_at is not None and "expires_at" in official_fields
        stated_expiry = _known(result.expiry_notes) and "expiry_notes" in official_fields
        if not (absolute_expiry or stated_expiry):
            problems.append("限时免费有效期未明确核实")
    else:
        problems.append("免费形式未核实")
    for field in ("quota", "quota_unit", "claim_conditions"):
        if not _known(getattr(result, field)):
            problems.append(f"{field} 未说明")
    for field in ("payment_required", "payment_method_required"):
        if getattr(result, field) is not False:
            problems.append(f"{field} 为必须或未核实，未达到零支付门槛")
    if result.models:
        required.add("models")
    if _known(result.rate_limit):
        required.add("rate_limit")
    if _known(result.region_restrictions):
        required.add("region_restrictions")
    if result.expires_at is not None:
        required.add("expires_at")
    if _known(result.expiry_notes):
        required.add("expiry_notes")
    missing = sorted(required - official_fields)
    if missing:
        problems.append("缺少字段对应官方依据：" + "、".join(missing))
    if result.failure_reason.strip():
        problems.insert(0, result.failure_reason.strip())
    result.failure_reason = "; ".join(dict.fromkeys(problems))
    result.status = ResourceStatus.PENDING if problems else ResourceStatus.ACTIVE
    return result


def _valid_http(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (
            url.scheme in {"http", "https"}
            and bool(url.hostname)
            and not url.username
            and not url.password
        )
    except ValueError:
        return False


def _facts(resource: Policy) -> dict:
    data = resource.model_dump(mode="json")
    return {
        key: sorted(set(data[key])) if key == "models" else data[key] for key in IMPORTANT_FIELDS
    }


def _snapshot(resource: Resource) -> dict:
    return resource.model_dump(mode="json")


MIGRATIONS = (
    """
    CREATE TABLE IF NOT EXISTS resources (
        id TEXT PRIMARY KEY,
        provider_domain TEXT NOT NULL,
        service_key TEXT NOT NULL,
        category TEXT NOT NULL,
        status TEXT NOT NULL,
        china_policy TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS resources_identity
        ON resources(provider_domain, service_key);
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        started_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS changes (
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL REFERENCES resources(id),
        task_id TEXT NOT NULL,
        discovered_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS changes_resource ON changes(resource_id, discovered_at);
    CREATE INDEX IF NOT EXISTS changes_task ON changes(task_id, discovered_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS resource_reviews (
        resource_id TEXT PRIMARY KEY REFERENCES resources(id),
        state TEXT NOT NULL,
        favorite INTEGER NOT NULL,
        note TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS user_actions (
        id TEXT PRIMARY KEY,
        resource_id TEXT NOT NULL,
        action TEXT NOT NULL,
        payload TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS user_actions_resource
        ON user_actions(resource_id, created_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings_secrets (
        name TEXT PRIMARY KEY,
        ciphertext TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    INSERT OR IGNORE INTO settings_meta(key, value) VALUES ('config_version', '0');
    """,
    """
    CREATE TABLE IF NOT EXISTS lead_discoveries (
        run_id TEXT NOT NULL,
        category TEXT NOT NULL,
        url TEXT NOT NULL,
        source_class TEXT NOT NULL,
        origin TEXT NOT NULL,
        provider TEXT,
        query TEXT,
        discovered_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS lead_discoveries_dedupe
        ON lead_discoveries(run_id, category, url);
    CREATE INDEX IF NOT EXISTS lead_discoveries_run
        ON lead_discoveries(run_id, discovered_at);
    """,
)

# Each action updates only what it names; state and favorites are independent.
REVIEW_STATES = {
    "confirm": ReviewState.CONFIRMED,
    "reject": ReviewState.REJECTED,
    "ignore": ReviewState.IGNORED,
    "reopen": ReviewState.OPEN,
}
REVIEW_FAVORITES = {"favorite": True, "unfavorite": False}


class UnknownResource(LookupError):
    """Raised when a review action names a resource that was never stored."""


class SettingsVersionConflict(Exception):
    """Raised when settings were written against a stale configuration version."""


def _review_from_row(row: sqlite3.Row) -> ResourceReview:
    return ResourceReview(
        resource_id=row["resource_id"],
        state=row["state"],
        favorite=bool(row["favorite"]),
        note=row["note"],
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _migrate(connection: sqlite3.Connection) -> None:
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    for step, script in enumerate(MIGRATIONS, start=1):
        if version >= step:
            continue
        connection.executescript(script)
    if version < len(MIGRATIONS):
        # PRAGMA statements cannot be parameterized; the value is a local constant.
        connection.execute(f"PRAGMA user_version = {len(MIGRATIONS)}")


class Repository:
    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "radar.sqlite3"
        with self._connect() as connection:
            _migrate(connection)
            connection.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def settings_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings_meta WHERE key = 'config_version'"
            ).fetchone()
        return int(row[0]) if row else 0

    def settings_overrides(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def settings_secret_rows(self) -> dict[str, str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name, ciphertext FROM settings_secrets ORDER BY name"
            ).fetchall()
        return {row["name"]: row["ciphertext"] for row in rows}

    def save_settings(
        self,
        overrides: Mapping[str, str | None],
        secrets: Mapping[str, str | None],
        expected_version: int,
    ) -> int:
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT value FROM settings_meta WHERE key = 'config_version'"
            ).fetchone()
            current = int(row[0]) if row else 0
            if current != expected_version:
                raise SettingsVersionConflict(
                    f"settings version {current} does not match {expected_version}"
                )
            for key, value in overrides.items():
                if value is None:
                    connection.execute("DELETE FROM settings WHERE key = ?", (key,))
                else:
                    connection.execute(
                        "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                        "updated_at = excluded.updated_at",
                        (key, value, now),
                    )
            for name, ciphertext in secrets.items():
                if ciphertext is None:
                    connection.execute("DELETE FROM settings_secrets WHERE name = ?", (name,))
                else:
                    connection.execute(
                        "INSERT INTO settings_secrets(name, ciphertext, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(name) DO UPDATE SET ciphertext = excluded.ciphertext, "
                        "updated_at = excluded.updated_at",
                        (name, ciphertext, now),
                    )
            version = current + 1
            connection.execute(
                "UPDATE settings_meta SET value = ? WHERE key = 'config_version'",
                (str(version),),
            )
        return version

    def list_resources(self, category=None, china_policy=None, status=None) -> list[Resource]:
        conditions: list[str] = []
        arguments: list[str] = []
        for name, value in (
            ("category", category),
            ("china_policy", china_policy),
            ("status", status),
        ):
            if value is not None:
                conditions.append(f"{name} = ?")
                arguments.append(str(value))
        sql = "SELECT payload FROM resources"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY rowid"
        with self._connect() as connection:
            return [
                Resource.model_validate_json(row[0]) for row in connection.execute(sql, arguments)
            ]

    def get_resource(self, id: str) -> Resource | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM resources WHERE id = ?", (id,)).fetchone()
            return Resource.model_validate_json(row[0]) if row else None

    def history(self, resource_id: str) -> list[Change]:
        return self._changes("resource_id", resource_id)

    def get_changes(self, task_id: str) -> list[Change]:
        return self._changes("task_id", task_id)

    def _changes(self, field: str, value: str) -> list[Change]:
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload FROM changes WHERE {field} = ? ORDER BY discovered_at, rowid",
                (value,),
            )
            return [Change.model_validate_json(row[0]) for row in rows]

    def list_runs(self) -> list[Run]:
        with self._connect() as connection:
            return [
                Run.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM runs ORDER BY started_at DESC, rowid DESC"
                )
            ]

    def get_run(self, id: str) -> Run | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM runs WHERE id = ?", (id,)).fetchone()
            return Run.model_validate_json(row[0]) if row else None

    def save_run(self, run: Run) -> None:
        with self._connect() as connection:
            self._save_run(connection, run)

    @staticmethod
    def _save_run(connection: sqlite3.Connection, run: Run) -> None:
        connection.execute(
            "INSERT INTO runs(id, started_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET started_at=excluded.started_at, payload=excluded.payload",
            (run.id, run.started_at.isoformat(), run.model_dump_json()),
        )

    def record_discoveries(self, run_id: str, discoveries: Iterable[LeadDiscovery]) -> int:
        """Persist leads for a run, skipping any already stored for the same key."""

        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for lead in discoveries:
                cursor = connection.execute(
                    "INSERT INTO lead_discoveries("
                    "run_id, category, url, source_class, origin, provider, query, discovered_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(run_id, category, url) DO NOTHING",
                    (
                        run_id,
                        lead.category,
                        lead.url,
                        lead.source_class,
                        lead.origin,
                        lead.provider,
                        lead.query,
                        lead.discovered_at.isoformat(),
                    ),
                )
                count = cursor.rowcount
                if count == -1:
                    count = connection.execute("SELECT changes()").fetchone()[0]
                inserted += count
        return inserted

    def discoveries_for_run(self, run_id: str) -> list[LeadDiscovery]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT category, url, source_class, origin, provider, query, discovered_at "
                "FROM lead_discoveries WHERE run_id = ? "
                "ORDER BY discovered_at, rowid",
                (run_id,),
            ).fetchall()
        return [
            LeadDiscovery.model_validate(
                {
                    "category": Category(row["category"]),
                    "url": row["url"],
                    "source_class": row["source_class"],
                    "origin": row["origin"],
                    "provider": row["provider"],
                    "query": row["query"],
                    "discovered_at": row["discovered_at"],
                }
            )
            for row in rows
        ]

    @staticmethod
    def _save_resource(connection: sqlite3.Connection, resource: Resource) -> None:
        connection.execute(
            "INSERT INTO resources(id,provider_domain,service_key,category,status,china_policy,payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "provider_domain=excluded.provider_domain,service_key=excluded.service_key,"
            "category=excluded.category,status=excluded.status,china_policy=excluded.china_policy,"
            "payload=excluded.payload",
            (
                resource.id,
                resource.provider_domain,
                resource.service_key,
                resource.category,
                resource.status,
                resource.china_policy,
                resource.model_dump_json(),
            ),
        )

    @staticmethod
    def _match(policy: Policy, resources: list[Resource]) -> Resource | None:
        if policy.resource_id:
            found = next((item for item in resources if item.id == policy.resource_id), None)
            if found is None:
                raise ValueError("显式资源标识不存在")
            if not policy.provider_domain or found.provider_domain != policy.provider_domain:
                raise ValueError("显式资源标识与提供商不匹配")
            if not _same_service(found, policy):
                raise ValueError("显式资源标识与具体 API 服务不匹配")
            return found
        same_provider = [
            item
            for item in resources
            if policy.provider_domain and item.provider_domain == policy.provider_domain
        ]
        exact = [
            item
            for item in same_provider
            if policy.service_key and item.service_key == policy.service_key
        ]
        if len(exact) == 1:
            return exact[0]
        matches = [item for item in same_provider if _same_service(item, policy)]
        if len(matches) > 1 or len(exact) > 1:
            raise ValueError("服务别名对应多个资源，无法安全判定身份")
        if matches:
            return matches[0]
        # Domainless discovery leads may be deduplicated by exact names only. They
        # cannot acquire official status or match a verified provider's records.
        if not policy.provider_domain:
            leads = [
                item
                for item in resources
                if not item.provider_domain
                and item.provider.casefold() == policy.provider.casefold()
                and item.service.casefold() == policy.service.casefold()
            ]
            if len(leads) == 1:
                return leads[0]
        return None

    @staticmethod
    def _stored_review(
        connection: sqlite3.Connection, resource_id: str, default_time: datetime
    ) -> ResourceReview:
        row = connection.execute(
            "SELECT resource_id, state, favorite, note, updated_at "
            "FROM resource_reviews WHERE resource_id = ?",
            (resource_id,),
        ).fetchone()
        if row is None:
            return ResourceReview(resource_id=resource_id, updated_at=default_time)
        return _review_from_row(row)

    def review(self, resource_id: str) -> ResourceReview:
        with self._connect() as connection:
            return self._stored_review(connection, resource_id, utc_now())

    def reviews(self) -> dict[str, ResourceReview]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT resource_id, state, favorite, note, updated_at "
                "FROM resource_reviews ORDER BY rowid"
            ).fetchall()
        return {row["resource_id"]: _review_from_row(row) for row in rows}

    def ignored_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT resource_id FROM resource_reviews WHERE state = ?",
                (ReviewState.IGNORED,),
            ).fetchall()
        return {row["resource_id"] for row in rows}

    def actions(self, resource_id: str) -> list[UserAction]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM user_actions WHERE resource_id = ? "
                "ORDER BY created_at, rowid",
                (resource_id,),
            ).fetchall()
        return [UserAction.model_validate_json(row[0]) for row in rows]

    def apply_review(
        self,
        resource_id: str,
        action: ReviewAction,
        note: str = "",
        now: datetime | None = None,
    ) -> tuple[ResourceReview, UserAction | None]:
        moment = aware_utc(now) if now is not None else utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM resources WHERE id = ?", (resource_id,)
            ).fetchone()
            if exists is None:
                raise UnknownResource(resource_id)
            current = self._stored_review(connection, resource_id, moment)
            updated = current.model_copy(deep=True)
            if action in REVIEW_STATES:
                updated.state = REVIEW_STATES[action]
            elif action in REVIEW_FAVORITES:
                updated.favorite = REVIEW_FAVORITES[action]
            elif action == "note":
                updated.note = note
            else:
                raise ValueError(f"未知审核动作：{action}")
            if (updated.state, updated.favorite, updated.note) == (
                current.state,
                current.favorite,
                current.note,
            ):
                return current, None
            updated.updated_at = moment
            connection.execute(
                "INSERT INTO resource_reviews(resource_id,state,favorite,note,updated_at) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(resource_id) DO UPDATE SET "
                "state=excluded.state, favorite=excluded.favorite, note=excluded.note, "
                "updated_at=excluded.updated_at",
                (
                    resource_id,
                    str(updated.state),
                    int(updated.favorite),
                    updated.note,
                    moment.isoformat(),
                ),
            )
            record = UserAction(
                resource_id=resource_id,
                action=action,
                before=current.model_dump(mode="json"),
                after=updated.model_dump(mode="json"),
                created_at=moment,
            )
            connection.execute(
                "INSERT INTO user_actions(id,resource_id,action,payload,created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    record.id,
                    resource_id,
                    action,
                    record.model_dump_json(),
                    moment.isoformat(),
                ),
            )
            return updated, record

    def apply_batch(self, batch: ResearchBatch, run: Run, now: datetime) -> list[Change]:
        now = aware_utc(now)
        changes: list[Change] = []
        with self._connect() as connection:
            # Take the writer lock before reading identities; a second process
            # cannot make a stale identity decision in the middle of this batch.
            connection.execute("BEGIN IMMEDIATE")
            resources = [
                Resource.model_validate_json(row[0])
                for row in connection.execute("SELECT payload FROM resources ORDER BY rowid")
            ]
            for incoming in batch.resources:
                if not run.scope.includes(incoming):
                    batch.failures.append(f"{incoming.service}：结果超出本次类别范围，未写入")
                    continue
                try:
                    previous = self._match(incoming, resources)
                except ValueError as error:
                    batch.failures.append(f"{incoming.service}：{error}")
                    continue
                if previous is not None and not run.scope.includes(previous):
                    batch.failures.append(f"{incoming.service}：匹配到范围外资源，未写入")
                    continue
                if incoming.check_status != CheckStatus.SUCCESS:
                    reason = incoming.failure_reason or "本次核查未完成，结论未获本次更新"
                    if previous:
                        current = previous.model_copy(
                            deep=True,
                            update={
                                "check_status": incoming.check_status,
                                "failure_reason": reason,
                                "last_checked_at": now,
                                "last_task_id": run.id,
                            },
                        )
                    else:
                        current = Resource(
                            provider=incoming.provider,
                            service=incoming.service,
                            category=incoming.category,
                            provider_domain=incoming.provider_domain,
                            service_key=incoming.service_key or _token(incoming.service),
                            aliases=incoming.aliases,
                            check_status=incoming.check_status,
                            failure_reason=reason,
                            first_seen_at=now,
                            last_checked_at=now,
                            last_task_id=run.id,
                        )
                    self._save_resource(connection, current)
                    resources = [item for item in resources if item.id != current.id] + [current]
                    continue

                checked = validate_policy(incoming, now)
                policy_data = checked.model_dump()
                policy_data["resource_id"] = None
                policy_data["service_key"] = (
                    previous.service_key
                    if previous
                    else checked.service_key or _token(checked.service)
                )
                if previous:
                    policy_data["aliases"] = list(
                        dict.fromkeys(
                            [
                                *previous.aliases,
                                previous.service,
                                previous.service_key,
                                *checked.aliases,
                                checked.service_key,
                            ]
                        )
                    )
                    policy_data["aliases"] = [value for value in policy_data["aliases"] if value]
                current = Resource(
                    **policy_data,
                    id=previous.id if previous else uuid4().hex,
                    first_seen_at=previous.first_seen_at if previous else now,
                    last_checked_at=now,
                    last_success_at=now,
                    last_task_id=run.id,
                    recommended_at=previous.recommended_at if previous else None,
                )
                kind = None
                if previous is None:
                    kind = "expired" if current.status == ResourceStatus.EXPIRED else "new"
                elif _facts(previous) != _facts(current):
                    if (
                        current.status == ResourceStatus.EXPIRED
                        and previous.status != ResourceStatus.EXPIRED
                    ):
                        kind = "expired"
                    elif (
                        previous.status == ResourceStatus.EXPIRED
                        and current.status == ResourceStatus.ACTIVE
                    ):
                        kind = "restored"
                    else:
                        kind = "changed"
                if kind and kind != "expired" and eligible_recommendation(current, run.scope):
                    current.recommended_at = now
                self._save_resource(connection, current)
                resources = [item for item in resources if item.id != current.id] + [current]
                if kind:
                    change = Change(
                        resource_id=current.id,
                        task_id=run.id,
                        kind=kind,
                        before=_snapshot(previous) if previous else {},
                        after=_snapshot(current),
                        evidence=current.evidence,
                        discovered_at=now,
                    )
                    connection.execute(
                        "INSERT INTO changes(id,resource_id,task_id,discovered_at,payload) VALUES (?,?,?,?,?)",
                        (
                            change.id,
                            change.resource_id,
                            change.task_id,
                            now.isoformat(),
                            change.model_dump_json(),
                        ),
                    )
                    changes.append(change)
        return changes

    def mark_interrupted(self) -> None:
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT payload FROM runs").fetchall()
            for row in rows:
                run = Run.model_validate_json(row[0])
                if run.status == "running":
                    run.status = "failed"
                    run.finished_at = now
                    run.error = "上次进程退出时任务尚未完成；结论未自动更新"
                    self._save_run(connection, run)

    def schedule_completed(self, day: str) -> bool:
        return any(
            run.schedule_day == day
            and run.trigger in {"scheduled", "catchup"}
            and run.finished_at is not None
            and run.status != "running"
            for run in self.list_runs()
        )

    def latest_schedule_day(self) -> str | None:
        days = [
            run.schedule_day
            for run in self.list_runs()
            if run.schedule_day
            and run.trigger in {"scheduled", "catchup"}
            and run.finished_at is not None
            and run.status != "running"
        ]
        return max(days) if days else None
