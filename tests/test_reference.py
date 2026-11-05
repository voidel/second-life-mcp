from copy import deepcopy

import pytest
from pydantic import ValidationError

from second_life_mcp.reference import Catalog


@pytest.mark.parametrize("language,expected", [("lsl", 1640), ("slua", 1993)])
def test_snapshot_has_sources_and_explicit_coverage(language, expected):
    catalog = Catalog(language)
    assert len(catalog.records) == expected
    status = catalog.status()
    assert status["coverage"] == "official_snapshot"
    assert status["network_at_runtime"] is False
    for symbol in catalog.symbols.values():
        assert symbol.source_url.startswith("https://")
        assert symbol.imported_on == "2026-11-05"
        assert symbol.reviewed_on is None


@pytest.mark.parametrize("language,name,typo", [
    ("lsl", "llMessageLinked", "llmessagelinked"),
    ("slua", "LLTimers:every", "lltimers:every"),
])
def test_lookup_never_silently_corrects(language, name, typo):
    catalog = Catalog(language)
    assert catalog.lookup(name)["found"]
    result = catalog.lookup(typo)
    assert result["found"] is False
    assert name in result["suggestions"]
    assert catalog.lookup("not_in_snapshot")["coverage"] == "official_snapshot"


@pytest.mark.parametrize("query", ['"', "(", "%", "NEAR(foo)", "foo OR bar", "*", "æ—¥æœ¬èªž"])
def test_search_treats_query_as_literal_text(query):
    assert isinstance(Catalog().search(query)["results"], list)


def test_search_pagination_and_order():
    catalog = Catalog()
    first = catalog.search("memory", kind="function", limit=1)
    assert len(first["results"]) == 1
    second = catalog.search("memory", kind="function", limit=1, offset=first["next_offset"])
    assert first["results"][0]["name"] != second["results"][0]["name"]
    assert catalog.search("llGetTime")["results"][0]["name"] == "llGetTime"
    assert catalog.search("memory", offset=999)["results"] == []


@pytest.mark.parametrize("kwargs", [
    {"query": ""}, {"query": " "}, {"query": "x" * 257},
    {"query": "memory", "limit": 0}, {"query": "memory", "limit": -1},
    {"query": "memory", "limit": 26}, {"query": "memory", "offset": -1},
    {"query": "memory", "kind": "anything"}, {"query": "memory", "limit": True},
])
def test_search_bounds(kwargs):
    with pytest.raises(ValueError):
        Catalog().search(**kwargs)


@pytest.mark.parametrize("mutation", ["duplicate", "bad-url", "bad-date", "extra", "language", "bad-name", "version"])
def test_invalid_data_fails_closed(mutation):
    document = deepcopy(Catalog().snapshot.model_dump())
    if mutation == "duplicate":
        document["symbols"].append(document["symbols"][0])
    elif mutation == "bad-url":
        document["symbols"][0]["source_url"] = "https://wiki.secondlife.com.evil.example/wiki/X"
    elif mutation == "bad-date":
        document["symbols"][0]["reviewed_on"] = "yesterday"
    elif mutation == "extra":
        document["unexpected"] = True
    elif mutation == "language":
        document["language"] = "slua"
    elif mutation == "bad-name":
        document["symbols"][0]["name"] = "../../file"
    else:
        document["schema_version"] = 99
    with pytest.raises((ValueError, ValidationError)):
        Catalog(document=document)


def test_language_validation_precedes_file_access():
    with pytest.raises(ValueError, match="Unknown language"):
        Catalog("../../anything")
