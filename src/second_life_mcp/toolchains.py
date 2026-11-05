"""Fetch pinned compiler test dependencies; not used by the MCP server at runtime."""
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from urllib.request import Request, urlopen
from zipfile import ZipFile

ASSETS = {
    "win32": [
        ("compiler", "v0.732.17", "https://github.com/secondlife/slua/releases/download/v0.732.17/slua-v0.732.17-windows.zip",
         "67a811d44aa238bd316f5c3b83623293acdc7d3bf3bd36aa327d6f0f049331fa", "slua-compile.exe"),
        ("slua_analyzer", "1.70.1", "https://github.com/JohnnyMorganz/luau-lsp/releases/download/1.70.1/luau-lsp-win64.zip",
         "64225b9738102a30de6ee09fb28e5a3827edc402ecf2a6364af570312468159f", "luau-lsp.exe")],
    "linux": [
        ("compiler", "v0.732.17", "https://github.com/secondlife/slua/releases/download/v0.732.17/slua-v0.732.17-ubuntu.zip",
         "db83fc8d99b8a83a90d7d97f7ee0d87a84e4bc77af89c73d99a9cb2f9e8c1ec9", "slua-compile"),
        ("slua_analyzer", "1.70.1", "https://github.com/JohnnyMorganz/luau-lsp/releases/download/1.70.1/luau-lsp-linux-x86_64.zip",
         "1a2ea1ae4f98f8946cefd970a4b54853e11ab4775e6932faa7f60cf920346567", "luau-lsp")],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform not in ASSETS:
        parser.error("Automatic test-toolchain downloads currently support Windows and Linux x86-64")
    target = args.output_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    config = {"schema_version": 1}
    test_runtime = None
    for name, version, url, expected, filename in ASSETS[sys.platform]:
        with urlopen(Request(url, headers={"User-Agent": "second-life-mcp-toolchains"}), timeout=30) as response:
            archive = response.read(64 * 1024 * 1024 + 1)
        if len(archive) > 64 * 1024 * 1024 or hashlib.sha256(archive).hexdigest() != expected:
            raise ValueError("Pinned toolchain archive failed verification")
        with ZipFile(BytesIO(archive)) as package:
            candidates = [entry for entry in package.namelist() if Path(entry).name == filename]
            if len(candidates) != 1:
                raise ValueError("Expected one compiler executable")
            executable = target / filename
            executable.write_bytes(package.read(candidates[0]))
            if os.name != "nt":
                executable.chmod(0o755)
            if name == "compiler":
                # Same hash-verified official archive; separate from server config.
                runtime_name = "slua.exe" if os.name == "nt" else "slua"
                runtimes = [entry for entry in package.namelist() if Path(entry).name == runtime_name]
                if len(runtimes) != 1:
                    raise ValueError("Expected one native test runtime")
                runtime_path = target / runtime_name
                runtime_path.write_bytes(package.read(runtimes[0]))
                if os.name != "nt":
                    runtime_path.chmod(0o755)
                test_runtime = {"executable": str(runtime_path), "version": version,
                                "sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest()}
        config[name] = {"executable": str(executable), "version": version,
                        "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
    (target / "toolchains.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    (target / "test-runtime.json").write_text(json.dumps(test_runtime, indent=2) + "\n", encoding="utf-8")
    print(target / "toolchains.json")


if __name__ == "__main__":
    main()
