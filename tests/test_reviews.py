"""Durable human review state, audit trail, and legacy-database upgrades."""

from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest
from domain_fixtures import BASE_TIME, completed_run, official_policy

from aifreeradar.models import ResearchBatch, Resource
from aifreeradar.storage import MIGRATIONS, Repository, UnknownResource

LEGACY_DDL = """
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
"""


@pytest.fixture
def repository(tmp_path):
    return Repository(tmp_path / "data")


def store(repository, *policies):
    policies = policies or (official_policy(),)
    run = completed_run("review-fixture", now=BASE_TIME)
    repository.save_run(run)
    repository.apply_batch(ResearchBatch(resources=list(policies)), run, BASE_TIME)
    return repository.list_resources()


def user_version(data_dir):
    connection = sqlite3.connect(data_dir / "radar.sqlite3")
    try:
        return connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()


def names(data_dir, kind):
    connection = sqlite3.connect(data_dir / "radar.sqlite3")
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = ?", (kind,)
        ).fetchall()
    finally:
        connection.close()
    return {row[0] for row in rows}


def legacy_database(tmp_path):
    data_dir = tmp_path / "legacy"
    data_dir.mkdir()
    policy = official_policy()
    resource = Resource(
        **policy.model_dump(),
        id="legacy-resource",
        first_seen_at=BASE_TIME,
        last_checked_at=BASE_TIME,
        last_task_id="legacy-task",
    )
    connection = sqlite3.connect(data_dir / "radar.sqlite3")
    try:
        connection.executescript(LEGACY_DDL)
        connection.execute(
            "INSERT INTO resources(id,provider_domain,service_key,category,status,"
            "china_policy,payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                resource.id,
                resource.provider_domain,
                resource.service_key,
                str(resource.category),
                str(resource.status),
                str(resource.china_policy),
                resource.model_dump_json(),
            ),
        )
        connection.commit()
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        connection.close()
    return data_dir, resource


def test_legacy_database_upgrades_in_place_and_second_open_is_a_noop(tmp_path):
    data_dir, resource = legacy_database(tmp_path)

    upgraded = Repository(data_dir)

    upgraded_resource = upgraded.get_resource(resource.id)
    assert upgraded_resource is not None
    assert upgraded_resource.model_dump(exclude={"messages"}) == resource.model_dump(
        exclude={"messages"}
    )
    (report,) = upgraded_resource.messages
    assert report.sources[0].url == resource.evidence[0].url
    assert report.sources[0].excerpt == resource.evidence[0].quote
    assert upgraded.reviews() == {}
    assert user_version(data_dir) == len(MIGRATIONS)
    assert {"resource_reviews", "user_actions"} <= names(data_dir, "table")
    assert "user_actions_resource" in names(data_dir, "index")

    reopened = Repository(data_dir)

    reopened_resource = reopened.get_resource(resource.id)
    assert reopened_resource is not None
    assert reopened_resource.model_dump() == upgraded_resource.model_dump()
    assert reopened.reviews() == {}
    assert user_version(data_dir) == len(MIGRATIONS)


def test_reopening_a_migrated_database_keeps_review_state_and_audit(tmp_path):
    data_dir = tmp_path / "data"
    repository = Repository(data_dir)
    (resource,) = store(repository)
    review, _ = repository.apply_review(resource.id, "confirm", now=BASE_TIME)
    actions = repository.actions(resource.id)
    del repository

    reopened = Repository(data_dir)

    assert reopened.review(resource.id) == review
    assert reopened.reviews() == {resource.id: review}
    assert reopened.actions(resource.id) == actions
    assert user_version(data_dir) == len(MIGRATIONS)


@pytest.mark.parametrize(
    ("action", "state"), [("confirm", "confirmed"), ("reject", "rejected"), ("ignore", "ignored")]
)
def test_state_transitions_are_persisted_with_one_audit_row(repository, action, state):
    (resource,) = store(repository)

    review, record = repository.apply_review(resource.id, action, now=BASE_TIME)

    assert review.resource_id == resource.id
    assert review.state == state
    assert review.favorite is False
    assert review.note == ""
    assert review.updated_at == BASE_TIME
    assert record is not None
    assert record.resource_id == resource.id
    assert record.action == action
    assert record.created_at == BASE_TIME
    assert record.before["state"] == "open"
    assert record.before["favorite"] is False
    assert record.after["state"] == state
    assert repository.review(resource.id) == review
    assert repository.actions(resource.id) == [record]


def test_reopen_returns_to_open_and_keeps_note_and_favorite(repository):
    (resource,) = store(repository)
    repository.apply_review(resource.id, "confirm", now=BASE_TIME)
    repository.apply_review(resource.id, "favorite", now=BASE_TIME + timedelta(minutes=1))
    repository.apply_review(
        resource.id, "note", note="值得关注", now=BASE_TIME + timedelta(minutes=2)
    )

    review, record = repository.apply_review(
        resource.id, "reopen", note="不应覆盖", now=BASE_TIME + timedelta(minutes=3)
    )

    assert review.state == "open"
    assert review.favorite is True
    assert review.note == "值得关注"
    assert record.before["state"] == "confirmed"
    assert record.before["favorite"] is True
    assert record.before["note"] == "值得关注"
    assert record.after["state"] == "open"
    assert len(repository.actions(resource.id)) == 4


def test_idempotent_repeat_writes_no_second_audit_row(repository):
    (resource,) = store(repository)
    first, record = repository.apply_review(resource.id, "confirm", now=BASE_TIME)

    again, none = repository.apply_review(
        resource.id, "confirm", now=BASE_TIME + timedelta(hours=1)
    )

    assert none is None
    assert again == first
    assert repository.actions(resource.id) == [record]
    assert repository.actions(resource.id)[0].before["state"] == "open"


def test_reopen_on_untouched_resource_writes_nothing(repository):
    (resource,) = store(repository)

    review, record = repository.apply_review(resource.id, "reopen", now=BASE_TIME)

    assert record is None
    assert review.state == "open"
    assert review.favorite is False
    assert review.note == ""
    assert repository.reviews() == {}
    assert repository.actions(resource.id) == []


def test_favorite_and_unfavorite_leave_state_and_note_alone(repository):
    (resource,) = store(repository)
    repository.apply_review(resource.id, "confirm", now=BASE_TIME)
    repository.apply_review(
        resource.id, "note", note="保留", now=BASE_TIME + timedelta(minutes=1)
    )

    favorite, record = repository.apply_review(
        resource.id, "favorite", now=BASE_TIME + timedelta(minutes=2)
    )

    assert favorite.favorite is True
    assert favorite.state == "confirmed"
    assert favorite.note == "保留"
    assert record.before["favorite"] is False
    assert record.after["favorite"] is True

    assert repository.apply_review(resource.id, "favorite")[1] is None

    unfavorite, record = repository.apply_review(
        resource.id, "unfavorite", now=BASE_TIME + timedelta(minutes=3)
    )

    assert unfavorite.favorite is False
    assert unfavorite.state == "confirmed"
    assert unfavorite.note == "保留"
    assert record.before["favorite"] is True
    assert record.after["favorite"] is False
    assert [item.action for item in repository.actions(resource.id)] == [
        "confirm",
        "note",
        "favorite",
        "unfavorite",
    ]


def test_note_is_trimmed_and_can_be_cleared(repository):
    (resource,) = store(repository)

    noted, record = repository.apply_review(
        resource.id, "note", note="  需要关注  ", now=BASE_TIME
    )

    assert noted.note == "需要关注"
    assert noted.state == "open"
    assert record.before["note"] == ""
    assert record.after["note"] == "需要关注"

    cleared, record = repository.apply_review(
        resource.id, "note", note="   ", now=BASE_TIME + timedelta(minutes=1)
    )

    assert cleared.note == ""
    assert record.before["note"] == "需要关注"
    assert record.after["note"] == ""
    assert repository.apply_review(resource.id, "note", note="")[1] is None
    assert len(repository.actions(resource.id)) == 2


def test_note_argument_is_ignored_for_state_actions(repository):
    (resource,) = store(repository)

    review, record = repository.apply_review(
        resource.id, "reject", note="不应记录", now=BASE_TIME
    )

    assert review.note == ""
    assert record.after["note"] == ""


def test_note_longer_than_limit_raises_without_writing(repository):
    (resource,) = store(repository)

    with pytest.raises(ValueError, match="2000"):
        repository.apply_review(resource.id, "note", note="字" * 2001)

    assert repository.reviews() == {}
    assert repository.actions(resource.id) == []


def test_unknown_resource_is_rejected(repository):
    with pytest.raises(UnknownResource):
        repository.apply_review("missing", "confirm", now=BASE_TIME)

    assert repository.reviews() == {}
    assert repository.actions("missing") == []


def test_untouched_resource_review_default_is_open_without_a_row(repository):
    (resource,) = store(repository)

    review = repository.review(resource.id)

    assert review.resource_id == resource.id
    assert review.state == "open"
    assert review.favorite is False
    assert review.note == ""
    assert repository.reviews() == {}


def test_reviews_and_ignored_ids_follow_persisted_state(repository):
    alpha, beta = store(
        repository,
        official_policy(service="Fixture Alpha", service_key="fixture-alpha"),
        official_policy(service="Fixture Beta", service_key="fixture-beta"),
    )
    repository.apply_review(alpha.id, "confirm", now=BASE_TIME)
    repository.apply_review(beta.id, "ignore", now=BASE_TIME)

    reviews = repository.reviews()

    assert set(reviews) == {alpha.id, beta.id}
    assert reviews[alpha.id].state == "confirmed"
    assert reviews[beta.id].state == "ignored"
    assert repository.ignored_ids() == {beta.id}

    repository.apply_review(alpha.id, "ignore", now=BASE_TIME + timedelta(minutes=1))
    assert repository.ignored_ids() == {alpha.id, beta.id}

    repository.apply_review(alpha.id, "reopen", now=BASE_TIME + timedelta(minutes=2))
    assert repository.ignored_ids() == {beta.id}
    assert repository.reviews()[alpha.id].state == "open"


def test_actions_are_ordered_by_creation_time(repository):
    (resource,) = store(repository)
    repository.apply_review(resource.id, "confirm", now=BASE_TIME + timedelta(minutes=5))
    repository.apply_review(resource.id, "favorite", now=BASE_TIME)
    repository.apply_review(
        resource.id, "note", note="顺序", now=BASE_TIME + timedelta(minutes=1)
    )

    actions = repository.actions(resource.id)

    assert [item.action for item in actions] == ["favorite", "note", "confirm"]
    assert [item.created_at for item in actions] == [
        BASE_TIME,
        BASE_TIME + timedelta(minutes=1),
        BASE_TIME + timedelta(minutes=5),
    ]