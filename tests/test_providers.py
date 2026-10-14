"""Publication is explicit, additive and atomic; exports round-trip without secrets."""

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest

from openmcp.product.config import Provider
from openmcp.providers import load_catalog, main, publish
from tests import test_product_api_call as api_tests

postgres_url = api_tests.postgres_url
store = api_tests.store


def definition(**changes):
    return api_tests.provider_for(api_tests.api_service()).model_copy(update=changes)


def test_validate_never_opens_database_or_calls_vendor(monkeypatch, capsys):
    monkeypatch.setenv("TAVILY_API_KEY", "private-placeholder")
    monkeypatch.setattr("openmcp.providers.open_store", Mock(side_effect=AssertionError))
    main(["validate", "tavily"])
    result = json.loads(capsys.readouterr().out)
    assert result["credential_configured"] is True and result["vendor_called"] is False
    assert "private-placeholder" not in json.dumps(result)


def test_import_errors_and_duplicates_never_publish(tmp_path, store):
    publish(store, [definition()], "test", enable=True)
    path = tmp_path / "catalog.json"
    for contents in (None, "{", "{}", json.dumps([definition().model_dump()] * 2)):
        if contents is not None:
            path.write_text(contents)
        with pytest.raises((ValueError, OSError)):
            publish(store, load_catalog(path), "test")
        assert store.service_count("test") == 1
    with pytest.raises(ValueError, match="unique"):
        publish(store, [definition(), definition()], "test")
    with pytest.raises(ValueError, match="mode"):
        publish(store, [definition()], "live")
    assert store.service_count("test") == 1


def test_disabled_default_export_and_enable_lifecycle(store, tmp_path):
    original = definition()
    publish(store, [original], "test")
    assert original.queries[0].enabled  # Publication does not mutate its input.
    assert store.service_count("test") == 0
    endpoint = original.queries[0].endpoint_id
    store.set_service_enabled(endpoint, True, "test")
    assert store.service_count("test") == 1
    store.disable_service(endpoint, "Operator review")
    exported = store.catalog()
    assert exported[0]["queries"][0]["enabled"] is False
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(exported))
    assert load_catalog(path)[0].secret_ref == api_tests.REF
    publish(store, load_catalog(path), "test")
    assert store.service_count("test") == 0
    store.set_service_enabled(endpoint, True, "test")
    assert store.disabled_endpoints() == set()
    assert store.service_count("test") == 1


def test_conflicting_endpoint_rolls_back_entire_publication(store):
    publish(store, [definition()], "test", enable=True)
    conflict = definition(provider_id="other")
    with pytest.raises(ValueError, match="owns"):
        publish(store, [conflict], "test", enable=True)
    assert [p["provider_id"] for p in store.catalog()] == [definition().provider_id]


def test_concurrent_providers_cannot_take_each_others_endpoint(store):
    def attempt(identifier):
        try:
            publish(store, [definition(provider_id=identifier)], "test", enable=True)
            return identifier
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["first", "second"]))
    (winner,) = [result for result in results if result]
    assert [p["provider_id"] for p in store.catalog()] == [winner]
    assert Provider.model_validate(store.catalog()[0]).queries[0].enabled


@pytest.mark.parametrize(
    "name",
    [
        "api2pdf",
        "builtwith",
        "companies_house",
        "dataforseo",
        "deepgram",
        "exa",
        "firecrawl",
        "nansen",
        "openweather",
        "tavily",
    ],
)
def test_builtin_publication_is_repeatable_and_preserves_existing(store, name):
    from openmcp.integrations.registry import provider

    publish(store, [definition()], "test", enable=True)
    for _ in range(2):
        publish(store, [provider(name, "test")], "test")
    assert len(store.catalog()) == 2
    assert store.service_count("test") == 1
    assert store.service(definition().queries[0].endpoint_id, "test") is not None
