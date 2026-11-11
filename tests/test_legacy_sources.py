"""Behavioral coverage for offline legacy source recovery and historical imports."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from domain_fixtures import BASE_TIME, completed_run

from aifreeradar.models import Category, CollectedMessage, MessageSource, Policy, Resource
from aifreeradar.storage import Repository


def legacy(**updates):
    values = {
        "provider": "Nimbus",
        "service": "Nimbus Image API",
        "category": "image",
        "provider_domain": "nimbus.example",
        "service_key": "nimbus-images",
        "first_seen_at": BASE_TIME - timedelta(days=30),
        "last_checked_at": BASE_TIME,
        "last_success_at": BASE_TIME - timedelta(days=1),
        "last_task_id": "legacy-run",
        "failure_reason": "Official account conditions remain unknown",
        "failure_reason_zh": "官方账户条件尚不明确",
    }
    values.update(updates)
    return Resource(**values)


def store(repository, *resources):
    with repository._connect() as connection:
        for resource in resources:
            repository._save_resource(connection, resource)


def cache(repository, value, name="result.0"):
    directory = repository.data_dir / "tool-output" / "old-run"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def report(resource, *, excerpt="Free image API, account conditions unspecified.", url=None):
    policy = Policy.model_validate(resource.model_dump(include=set(Policy.model_fields)))
    policy.resource_id = resource.id
    return CollectedMessage(
        policy=policy,
        title=resource.service,
        summary="Historical free API report",
        sources=[MessageSource(url=url or "https://nimbus.example/pricing", excerpt=excerpt)],
    )


def test_cached_free_api_recovers_unknown_terms_once_without_changing_policy(tmp_path):
    repository = Repository(tmp_path / "data")
    resource = legacy()
    store(repository, resource)
    repository.apply_review(resource.id, "favorite")
    repository.apply_review(resource.id, "note", "Keep my assessment")
    review = repository.review(resource.id)
    cache(repository, [{
        "url": "https://nimbus.example/image-api",
        "title": "Nimbus image API",
        "snippet": "Free image API. Quota and payment method conditions are not stated.",
    }])

    assert repository.recover_legacy_messages() == 1
    restored = repository.get_resource(resource.id)
    assert restored is not None
    assert restored.model_dump(exclude={"messages"}) == resource.model_dump(exclude={"messages"})
    assert repository.review(resource.id) == review
    (event,) = repository.list_messages()
    assert event.discovered_at == resource.first_seen_at
    assert event.first_seen_at == resource.first_seen_at
    assert event.sources[0].access == "snippet"
    assert event.sources[0].published_at is None
    assert restored.messages[0].policy.payment_required is None
    assert repository.recover_legacy_messages() == 0
    assert len(Repository(repository.data_dir).list_messages()) == 1


def test_cached_pages_keep_page_access_and_ignored_resources_are_skipped(tmp_path):
    repository = Repository(tmp_path / "data")
    resource = legacy()
    ignored = legacy(service="Nimbus Text API", category="text", service_key="nimbus-text")
    store(repository, resource, ignored)
    repository.apply_review(ignored.id, "ignore")
    cache(repository, {
        "url": "https://nimbus.example/pricing",
        "checked_at": BASE_TIME.isoformat(),
        "text": "Free image API for Nimbus.\nFree text API for Nimbus.",
    })

    assert repository.recover_legacy_messages() == 1
    (event,) = repository.list_messages(include_ended=True)
    assert event.resource_id == resource.id
    assert event.sources[0].access == "page"
    ignored_resource = repository.get_resource(ignored.id)
    assert ignored_resource is not None
    assert ignored_resource.messages == []


def test_shared_provider_pricing_does_not_transfer_text_free_offer_to_images(tmp_path):
    repository = Repository(tmp_path / "data")
    text = legacy(
        service="Nimbus Text API",
        category="text",
        service_key="nimbus-text",
        aliases=["Nimbus Platform"],
    )
    image = legacy(aliases=["Nimbus Platform"])
    store(repository, text, image)
    cache(repository, [{
        "url": "https://nimbus.example/pricing",
        "title": "Nimbus API pricing",
        "snippet": "Text API is free.\nImage API requires payment.",
    }])

    assert repository.recover_legacy_messages() == 1
    text_resource = repository.get_resource(text.id)
    image_resource = repository.get_resource(image.id)
    assert text_resource is not None and text_resource.messages
    assert image_resource is not None and image_resource.messages == []


def test_empty_corrupt_notes_directories_and_unrelated_results_do_not_invent_sources(tmp_path):
    repository = Repository(tmp_path / "data")
    resource = legacy()
    store(repository, resource)
    cache(repository, [], "empty")
    cache(repository, [{
        "url": "https://other.example/image-api",
        "title": "Other image API",
        "snippet": "Free API.",
    }], "unrelated")
    cache(repository, {
        "url": "https://nimbus.example/llms.txt", "checked_at": BASE_TIME.isoformat(),
        "text": "# Nimbus documentation\n- [Free image API](https://nimbus.example/images)",
    }, "directory")
    cache(repository, [{
        "url": "https://nimbus.example/docs", "title": "Nimbus documentation",
        "snippet": "- [Free image API](https://nimbus.example/images)",
    }], "linked-directory")
    cache(repository, None, "corrupt").write_text("{broken", encoding="utf-8")
    cache(repository, None, "notes").write_text(
        "Nimbus has a free image API: https://nimbus.example/images", encoding="utf-8"
    )

    assert repository.recover_legacy_messages() == 0
    assert repository.list_messages(include_ended=True) == []


@pytest.mark.parametrize("url", [
    "http://localhost/docs", "http://127.0.0.1/docs", "http://10.0.0.2/docs",
    "http://[::1]/docs", "http://nimbus.internal/docs",
])
def test_unsafe_cached_and_imported_urls_are_rejected(tmp_path, url):
    repository = Repository(tmp_path / "data")
    resource = legacy()
    store(repository, resource)
    cache(repository, [{"url": url, "title": "Nimbus image API", "snippet": "Free image API."}])
    assert repository.recover_legacy_messages() == 0
    imported = repository.import_legacy_messages(
        [report(resource, url=url)], completed_run("backfill")
    )
    assert imported == []


def test_import_only_fills_explicit_existing_ids_and_preserves_history(tmp_path):
    repository = Repository(tmp_path / "data")
    resource = legacy(status="active", payment_required=False)
    store(repository, resource)
    run = completed_run("backfill")
    incoming = report(resource)
    missing = report(legacy())
    no_id = incoming.model_copy(deep=True)
    no_id.policy.resource_id = None
    wrong_category = incoming.model_copy(deep=True)
    wrong_category.policy.category = Category.TEXT

    events = repository.import_legacy_messages([missing, no_id, wrong_category, incoming], run)
    assert len(events) == 1
    assert events[0].task_id == run.id
    assert events[0].first_seen_at == resource.first_seen_at
    assert events[0].discovered_at == resource.first_seen_at
    stored = repository.get_resource(resource.id)
    assert stored is not None
    assert stored.model_dump(exclude={"messages"}) == resource.model_dump(exclude={"messages"})
    assert repository.import_legacy_messages([incoming], run) == []
    assert len(repository.list_resources()) == 1


def test_symbolic_linked_tool_material_cannot_escape_data_directory(tmp_path):
    repository = Repository(tmp_path / "data")
    resource = legacy()
    store(repository, resource)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "result").write_text(json.dumps([{
        "url": "https://nimbus.example/image-api",
        "title": "Nimbus image API",
        "snippet": "Free image API.",
    }]), encoding="utf-8")
    directory = repository.data_dir / "tool-output"
    directory.mkdir()
    try:
        (directory / "linked-run").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is unavailable for this account")
    assert repository.recover_legacy_messages() == 0
