from copy import deepcopy
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from second_life_mcp.reference import Catalog
from second_life_mcp.update import fetch_source, compare_catalogs, build_candidate

URL = "https://raw.githubusercontent.com/secondlife/lsl-definitions/main/lsl_definitions.yaml"


class Response(BytesIO):
    headers = {"ETag": '"one"'}


def test_conditional_cache_and_304(tmp_path):
    body = b"source"
    assert fetch_source(URL, tmp_path, opener=lambda *a, **k: Response(body)) == body
    def unchanged(request, **kwargs):
        assert request.get_header("If-none-match") == '"one"'
        raise HTTPError(URL, 304, "unchanged", {}, None)
    assert fetch_source(URL, tmp_path, opener=unchanged) == body


def test_corrupt_cache_is_not_used(tmp_path):
    fetch_source(URL, tmp_path, opener=lambda *a, **k: Response(b"first"))
    next(tmp_path.glob("*.bin")).write_bytes(b"corrupted")
    def broken(request, **kwargs):
        assert request.get_header("If-none-match") is None
        raise HTTPError(URL, 304, "unchanged", {}, None)
    with pytest.raises(ValueError, match="valid cached"):
        fetch_source(URL, tmp_path, opener=broken)


def test_retry_after_is_bounded():
    calls, delays = [], []
    def request(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise HTTPError(URL, 429, "retry", {"Retry-After": "999"}, None)
        return Response(b"done")
    assert fetch_source(URL, opener=request, sleep=delays.append) == b"done"
    assert delays == [30, 30]


def test_source_allowlist():
    with pytest.raises(ValueError):
        fetch_source("https://example.invalid/definitions")


def test_semantic_diff_ignores_import_metadata():
    baseline = {lang: Catalog(lang).snapshot.model_dump() for lang in ("lsl", "slua")}
    candidate = deepcopy(baseline)
    for document in candidate.values():
        for row in document["symbols"]:
            row["imported_on"] = "2026-11-06"
            row["source_sha256"] = "f" * 64
    assert all(not delta["changed"] for delta in compare_catalogs(baseline, candidate).values())
    candidate["lsl"]["symbols"][0]["summary"] = "Updated semantics"
    assert len(compare_catalogs(baseline, candidate)["lsl"]["changed"]) == 1


def test_partial_download_does_not_create_candidate_or_change_baseline(tmp_path):
    target = tmp_path / "candidate"
    calls = []
    baseline = {lang: Catalog(lang).snapshot.model_dump() for lang in ("lsl", "slua")}
    original = deepcopy(baseline)
    def fetch(*args):
        calls.append(1)
        if len(calls) == 2:
            raise URLError("offline")
        return b"incomplete"
    with pytest.raises(URLError):
        build_candidate("a" * 40, target, baseline=baseline, fetch=fetch)
    assert not target.exists()
    assert baseline == original


def test_existing_candidate_is_never_overwritten(tmp_path):
    target = tmp_path / "candidate"
    target.mkdir()
    (target / "review").write_text("keep")
    with pytest.raises(FileExistsError):
        build_candidate("a" * 40, target)
    assert (target / "review").read_text() == "keep"


def test_semantic_diff_normalizes_omitted_schema_defaults():
    baseline = {lang: Catalog(lang).snapshot.model_dump() for lang in ("lsl", "slua")}
    candidate = deepcopy(baseline)
    for document in candidate.values():
        for row in document["symbols"]:
            if not row["overloads"]:
                del row["overloads"]
    assert all(not delta["changed"] for delta in compare_catalogs(baseline, candidate).values())


def test_failed_atomic_write_preserves_existing_file(tmp_path, monkeypatch):
    import second_life_mcp.update as module
    target = tmp_path / "baseline"
    target.write_bytes(b"last-good")
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(module.os, "replace", fail)
    with pytest.raises(OSError):
        module.atomic_write(target, b"candidate")
    assert target.read_bytes() == b"last-good"
    assert list(tmp_path.iterdir()) == [target]
