"""Maintainer-only source refresh: cached downloads and atomic candidate bundles."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .importer import SOURCE_FILES, SOURCE_PATHS, REPOSITORY, MAX_SOURCE_BYTES, import_catalogs
from .reference import Catalog, Symbol


def atomic_write(path, body):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def fetch_source(url, cache_dir=None, opener=urlopen, sleep=time.sleep):
    allowed = (r"https://raw\.githubusercontent\.com/secondlife/lsl-definitions/[A-Za-z0-9._/-]+",
               r"https://api\.github\.com/repos/secondlife/lsl-definitions/commits/main")
    if not any(re.fullmatch(pattern, url) for pattern in allowed):
        raise ValueError("Source URL is outside the official definition repository")
    headers = {"User-Agent": "second-life-mcp-source-update"}
    cached = None
    key = hashlib.sha256(url.encode()).hexdigest()
    directory = Path(cache_dir) if cache_dir else None
    if directory:
        try:
            meta = json.loads((directory / (key + ".json")).read_text("utf-8"))
            body = (directory / (key + ".bin")).read_bytes()
            if len(body) <= MAX_SOURCE_BYTES and hashlib.sha256(body).hexdigest() == meta["sha256"]:
                cached = body
                if meta.get("etag"):
                    headers["If-None-Match"] = meta["etag"]
                if meta.get("last_modified"):
                    headers["If-Modified-Since"] = meta["last_modified"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    for attempt in range(3):
        delay = 2 ** attempt
        try:
            with opener(Request(url, headers=headers), timeout=15) as response:
                body = response.read(MAX_SOURCE_BYTES + 1)
                if len(body) > MAX_SOURCE_BYTES:
                    raise ValueError("Official source exceeds the download limit")
                response_headers = response.headers
            if directory:
                meta = {"url": url, "sha256": hashlib.sha256(body).hexdigest(),
                        "etag": response_headers.get("ETag"), "last_modified": response_headers.get("Last-Modified")}
                atomic_write(directory / (key + ".bin"), body)
                atomic_write(directory / (key + ".json"), json.dumps(meta).encode())
            return body
        except HTTPError as error:
            if error.code == 304:
                if cached is None:
                    raise ValueError("Server returned 304 without a valid cached source") from error
                return cached
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            retry = error.headers.get("Retry-After", "") if error.headers else ""
            if retry.isdigit():
                delay = min(int(retry), 30)
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        sleep(delay)
    raise RuntimeError("Unreachable retry state")


def semantic_record(record):
    return {key: value for key, value in Symbol.model_validate(record).model_dump().items()
            if key not in ("source_url", "source_revision", "source_sha256", "imported_on", "reviewed_on")}


def compare_catalogs(before, after):
    result = {}
    for language in ("lsl", "slua"):
        old = {(r["kind"], r["name"]): semantic_record(r) for r in before[language]["symbols"]}
        new = {(r["kind"], r["name"]): semantic_record(r) for r in after[language]["symbols"]}
        label = lambda key: {"kind": key[0], "name": key[1]}
        result[language] = {
            "added": [label(key) for key in sorted(new.keys() - old.keys())],
            "removed": [label(key) for key in sorted(old.keys() - new.keys())],
            "changed": [label(key) for key in sorted(new.keys() & old.keys()) if new[key] != old[key]],
            "before_count": len(old), "after_count": len(new),
        }
    return result


def build_candidate(revision, output_dir, cache_dir=None, baseline=None, fetch=fetch_source):
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError("Candidate directory already exists; choose a new output directory")
    if revision is None:
        identity = json.loads(fetch(f"https://api.github.com/repos/{REPOSITORY}/commits/main", cache_dir))
        revision = identity["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected an immutable official commit revision")
    bodies = {name: fetch(f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{SOURCE_PATHS[name]}", cache_dir)
              for name in SOURCE_FILES}
    catalogs, manifest = import_catalogs(bodies, revision)
    if baseline is None:
        baseline = {lang: Catalog(lang).snapshot.model_dump() for lang in ("lsl", "slua")}
    else:
        for lang in ("lsl", "slua"):
            Catalog(lang, document=baseline[lang])
    changes = compare_catalogs(baseline, catalogs)
    report = {
        "revision": revision, "created_at": datetime.now(timezone.utc).isoformat(),
        "baseline_sha256": {lang: hashlib.sha256(json.dumps(baseline[lang], sort_keys=True).encode()).hexdigest()
                            for lang in ("lsl", "slua")},
        "changes": changes,
        "review_required": True,
        "warnings": [f"{lang}: inventory entries were removed; inspect the candidate before use."
                     for lang, delta in changes.items() if delta["removed"]],
        "note": "Candidate only. No bundled snapshot, review date or source baseline was updated.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix=".candidate-") as temporary:
        staging = Path(temporary).resolve()
        if staging.parent != output.parent:
            raise ValueError("Candidate staging path escaped its output parent")
        (staging / "secondlife.d.luau").write_bytes(bodies["secondlife.d.luau"])
        for name, document in {**catalogs, "source_manifest": manifest, "changes": report}.items():
            (staging / (name + ".json")).write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # All files are complete and validated before this same-filesystem directory rename.
        os.replace(staging, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", help="Immutable official commit; default resolves main once before downloading")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--baseline-dir", type=Path)
    args = parser.parse_args()
    baseline = None
    if args.baseline_dir:
        baseline = {lang: json.loads((args.baseline_dir / (lang + ".json")).read_text("utf-8")) for lang in ("lsl", "slua")}
    report = build_candidate(args.revision, args.output_dir, args.cache_dir, baseline)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
