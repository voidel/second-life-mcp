import hashlib
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from second_life_mcp.audit import audit_source, MAX_BYTES


def source_for(body):
    digest = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
    return {"url": "https://example.invalid/reference", "git_blob_sha": digest}


def test_audit_fingerprint_and_changed_status():
    body = b'{"version": 1}'
    assert audit_source(source_for(body), opener=lambda *a, **k: BytesIO(body))["changed"] is False
    assert audit_source(source_for(body), opener=lambda *a, **k: BytesIO(b"changed"))["changed"] is True


def test_audit_retries_transient_failures_with_bounds():
    attempts, delays = [], []
    body = b"reference"
    def opener(*args, **kwargs):
        attempts.append(kwargs["timeout"])
        if len(attempts) < 3:
            raise URLError("offline")
        return BytesIO(body)
    assert audit_source(source_for(body), opener=opener, sleep=delays.append)["changed"] is False
    assert attempts == [10, 10, 10]
    assert delays == [1, 2]


def test_audit_does_not_retry_permanent_http_failure():
    delays = []
    def opener(*args, **kwargs):
        raise HTTPError("https://example.invalid", 404, "missing", {}, None)
    with pytest.raises(HTTPError):
        audit_source(source_for(b""), opener=opener, sleep=delays.append)
    assert delays == []


def test_audit_rejects_oversized_source():
    with pytest.raises(ValueError):
        audit_source(source_for(b""), opener=lambda *a, **k: BytesIO(b"x" * (MAX_BYTES + 1)))
