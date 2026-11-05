"""Explicit, local, hash-pinned compiler adapters; submitted scripts are never run."""
import hashlib
from importlib.resources import files
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading

from .limits import MAX_CODE

MAX_OUTPUT = 65536
TIMEOUT = 10


def load_toolchains():
    configured = os.environ.get("SECOND_LIFE_MCP_TOOLCHAINS")
    if not configured:
        return {}
    path = Path(configured)
    if path.stat().st_size > 16384:
        raise ValueError("Toolchain configuration exceeds its size limit")
    data = json.loads(path.read_text("utf-8"))
    if data.get("schema_version") != 1 or set(data) - {"schema_version", "compiler", "slua_analyzer"}:
        raise ValueError("Unsupported toolchain configuration")
    for name in ("compiler", "slua_analyzer"):
        if name not in data:
            continue
        entry = data[name]
        if set(entry) != {"executable", "sha256", "version"}:
            raise ValueError("Toolchains require executable, sha256 and version")
        executable = Path(entry["executable"])
        if not executable.is_absolute() or not executable.is_file():
            raise ValueError("A toolchain executable must be an existing absolute file")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) or not entry["version"]:
            raise ValueError("Toolchain identity is not pinned")
        with executable.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError("Toolchain executable hash does not match its configuration")
    return data


def run_bounded(command, cwd, timeout=TIMEOUT, limit=MAX_OUTPUT):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, shell=False, creationflags=flags)
    output = bytearray()
    overflow = []
    def drain():
        while True:
            chunk = process.stdout.read(1024)
            if not chunk:
                return
            remaining = limit - len(output)
            output.extend(chunk[:remaining])
            if len(chunk) > remaining:
                overflow.append(True)
                process.kill()
                return
    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait()
    reader.join(timeout=2)
    process.stdout.close()
    return {"returncode": process.returncode, "output": output.decode("utf-8", errors="replace"),
            "timed_out": timed_out, "output_limited": bool(overflow)}


def diagnostics(output, language, backend, version="v0.732.17"):
    rows = []
    for line in output.splitlines():
        if backend == "compiler":
            match = re.match(r"^.*\((\d+),(\d+)\): (\w+): (.*)$", line)
            if not match:
                continue
            line_number, column, kind, message = match.groups()
            # The pinned SLua LSL frontend passes one-based lines through a
            # zero-based diagnostic wrapper. Luau locations do not need this fix.
            line_number = max(1, int(line_number) - (language == "lsl" and version == "v0.732.17"))
            severity = "error"
        else:
            match = re.match(r"^.*?:(\d+):(\d+)(?:-\d+)?: \(([EW])\d+\) (.*)$", line)
            if not match:
                continue
            line_number, column, level, message = match.groups()
            kind = message.split(":", 1)[0]
            severity = "error" if level == "E" or kind in ("TypeError", "SyntaxError") else "warning"
        rows.append({"line": int(line_number), "column": int(column), "severity": severity,
                     "kind": kind, "message": message[:2000], "backend": backend})
    return rows


def compile_source(code, language, config=None, runner=run_bounded):
    if language not in ("lsl", "slua") or len(code) > MAX_CODE:
        raise ValueError("Invalid language or oversized source")
    result = {"status": "not_configured", "language": language, "success": False,
              "compiler_validated": False, "typechecked": False, "in_world_validated": False,
              "diagnostics": [], "diagnostics_capped": False, "backends": [],
              "note": "Configure SECOND_LIFE_MCP_TOOLCHAINS with local executable paths, versions and SHA-256 hashes."}
    try:
        config = load_toolchains() if config is None else config
    except (OSError, ValueError, TypeError, KeyError):
        result.update(status="invalid_configuration", note="The local toolchain configuration failed validation.")
        return result
    if "compiler" not in config:
        return result
    # Single-file analysis cannot safely resolve arbitrary external module paths.
    from slua_mcp.checker import mask_noncode as mask_slua
    from lsl_mcp.checker import mask_noncode as mask_lsl
    masked, _ = (mask_lsl if language == "lsl" else mask_slua)(code)
    imports = re.search(r"\brequire\s*\(|^\s*#\s*include\b", masked, re.M)
    interpolated_import = language == "slua" and re.search(r"`[^`]*\brequire\s*\(", code)
    if imports or interpolated_import:
        result.update(status="unsupported_import", note="Single-file compiler checks do not resolve require/include imports.")
        return result
    with tempfile.TemporaryDirectory(prefix="second-life-compile-") as temporary:
        directory = Path(temporary)
        source = directory / ("source.lsl" if language == "lsl" else "source.luau")
        source.write_text(code, encoding="utf-8")
        compiler = config["compiler"]
        runs = [("compiler", [compiler["executable"], "--null", "-O0", str(source)], compiler)]
        analyzer = config.get("slua_analyzer")
        if language == "slua" and analyzer:
            definitions = directory / "secondlife.d.luau"
            body = files("second_life_mcp").joinpath("data/secondlife.d.luau").read_bytes()
            manifest = json.loads(files("second_life_mcp").joinpath("data/source_manifest.json").read_text("utf-8"))
            expected = next(row["sha256"] for row in manifest if row["name"] == "secondlife.d.luau")
            if hashlib.sha256(body).hexdigest() != expected:
                result.update(status="invalid_definitions", note="Bundled analyzer definitions do not match the source manifest.")
                return result
            definitions.write_bytes(body)
            (directory / ".luaurc").write_text('{"languageMode":"strict"}', encoding="utf-8")
            runs.append(("analyzer", [analyzer["executable"], "analyze", "--platform=standard", "--formatter=plain",
                                      "--definitions=" + str(definitions), str(source)], analyzer))
        result.update(status="completed", success=True, note="Local compilation only; simulator behavior and deployment availability are unverified.")
        for backend, command, entry in runs:
            try:
                completed = runner(command, directory)
            except OSError:
                result.update(status="backend_unavailable", success=False)
                break
            result["backends"].append({"backend": backend, "version": entry["version"], "sha256": entry["sha256"]})
            if completed["timed_out"] or completed["output_limited"]:
                result.update(status="timeout" if completed["timed_out"] else "output_limit", success=False)
                break
            rows = diagnostics(completed["output"], language, backend, entry["version"])
            remaining = 100 - len(result["diagnostics"])
            result["diagnostics_capped"] |= len(rows) > remaining
            result["diagnostics"].extend(rows[:remaining])
            errors = any(row["severity"] == "error" for row in rows)
            if backend == "compiler":
                result["compiler_validated"] = completed["returncode"] == 0
                result["typechecked"] = language == "lsl"
            else:
                result["typechecked"] = True
            # luau-lsp may return zero while reporting TypeError diagnostics.
            if completed["returncode"] != 0 or errors:
                result.update(success=False)
                if not rows:
                    result["note"] = "The backend failed without recognized diagnostics; no clean result is claimed."
                break
        if language == "slua" and not analyzer:
            result["note"] += " No SLua type analyzer is configured; static types were not checked."
    return result
