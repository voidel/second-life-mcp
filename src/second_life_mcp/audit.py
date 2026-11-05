"""Explicit maintainer command; never called by an MCP tool."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.resources import files
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_BYTES = 2 * 1024 * 1024


def audit_source(source, opener=urlopen, sleep=time.sleep):
    # The URL comes only from the bundled manifest, not tool/client input.
    request = Request(source["url"], headers={"User-Agent": "second-life-mcp/0.1 source-audit"})
    for attempt in range(3):
        try:
            with opener(request, timeout=10) as response:
                body = response.read(MAX_BYTES + 1)
                if len(body) > MAX_BYTES:
                    raise ValueError("Official source exceeds the 2 MiB audit limit")
            # Git's blob identity is stable across checkout and API transports.
            digest = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
            return {**source, "current_git_blob_sha": digest,
                    "changed": digest != source["git_blob_sha"],
                    "checked_at": datetime.now(timezone.utc).isoformat()}
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        sleep(2 ** attempt)
    raise RuntimeError("Unreachable audit retry state")


def main():
    argparse.ArgumentParser(description="Check pinned official API source fingerprints; never rewrite reference data.").parse_args()
    manifest = json.loads(files("second_life_mcp").joinpath("data/source_manifest.json").read_text("utf-8"))
    try:
        results = [audit_source(source) for source in manifest]
    except (OSError, ValueError) as error:
        print(f"Source audit failed: {type(error).__name__}. Baselines were not changed.", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"sources": results, "note": "A changed source requires manual review; this is not semantic verification."}, indent=2))
    raise SystemExit(2 if any(row["changed"] for row in results) else 0)


if __name__ == "__main__":
    main()
