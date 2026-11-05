import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from second_life_mcp.compiler import compile_source, run_bounded, diagnostics, load_toolchains


def test_compiler_is_explicit_and_does_not_execute_without_configuration(monkeypatch):
    monkeypatch.delenv("SECOND_LIFE_MCP_TOOLCHAINS", raising=False)
    assert compile_source("default {}", "lsl")["status"] == "not_configured"


def test_configuration_hash_is_enforced(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"schema_version": 1, "compiler": {"executable": sys.executable, "version": "test", "sha256": "0" * 64}}))
    monkeypatch.setenv("SECOND_LIFE_MCP_TOOLCHAINS", str(path))
    assert compile_source("", "lsl")["status"] == "invalid_configuration"


def test_backend_output_and_time_are_bounded(tmp_path):
    output = run_bounded([sys.executable, "-c", "print('x'*100000)"], tmp_path, limit=1000)
    assert output["output_limited"] and len(output["output"]) == 1000
    timed = run_bounded([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, timeout=0.1)
    assert timed["timed_out"]


def test_lsl_line_mapping_and_slua_zero_exit_type_error():
    assert diagnostics("source.lsl(4,3): SyntaxError: bad type", "lsl", "compiler")[0]["line"] == 3
    config = {"compiler": {"executable": "compiler", "version": "pinned", "sha256": "a"*64},
              "slua_analyzer": {"executable": "analyzer", "version": "pinned", "sha256": "b"*64}}
    def runner(command, directory):
        return {"returncode": 0, "timed_out": False, "output_limited": False,
                "output": "source.luau:1:1-20: (W0) TypeError: wrong type" if command[0] == "analyzer" else ""}
    result = compile_source('local x: number = "wrong"', "slua", config=config, runner=runner)
    assert not result["success"]
    assert result["compiler_validated"]
    assert result["typechecked"]


def test_single_file_compilers_do_not_resolve_imports():
    config = {"compiler": {"executable": "unused", "version": "pinned", "sha256": "a"*64}}
    assert compile_source('require("../../private")', "slua", config=config)["status"] == "unsupported_import"


@pytest.mark.skipif(not os.environ.get("SECOND_LIFE_MCP_TOOLCHAINS"), reason="Pinned compiler toolchain not configured")
@pytest.mark.parametrize("language,good,bad", [
    ("lsl", 'default { state_entry() { llOwnerSay("hello"); } }',
     'default {\nstate_entry() {\ninteger x = "wrong";\n}\n}'),
    ("slua", 'll.Say(0,"hello")', 'local x: number = "wrong"\nll.Say(0,x)'),
])
def test_real_pinned_toolchain(language, good, bad):
    valid = compile_source(good, language)
    assert valid["status"] == "completed" and valid["success"], valid
    invalid = compile_source(bad, language)
    assert invalid["status"] == "completed" and not invalid["success"], invalid
    assert invalid["typechecked"]
    assert any(row["severity"] == "error" for row in invalid["diagnostics"])
    assert not valid["in_world_validated"]


def test_type_errors_after_diagnostic_cap_still_fail():
    config = {"compiler": {"executable": "compiler", "version": "pinned", "sha256": "a"*64},
              "slua_analyzer": {"executable": "analyzer", "version": "pinned", "sha256": "b"*64}}
    def runner(command, directory):
        text = "source.luau:1:1-2: (W1) LocalUnused: unused\n" * 100 + "source.luau:2:1-2: (W0) TypeError: wrong type"
        return {"returncode": 0, "timed_out": False, "output_limited": False,
                "output": text if command[0] == "analyzer" else ""}
    result = compile_source("local x = 1", "slua", config=config, runner=runner)
    assert not result["success"] and result["diagnostics_capped"]
    assert len(result["diagnostics"]) == 100


def test_require_mention_in_ordinary_string_does_not_request_module_resolution():
    config = {"compiler": {"executable": "compiler", "version": "pinned", "sha256": "a"*64}}
    def runner(*args):
        return {"returncode": 0, "timed_out": False, "output_limited": False, "output": ""}
    assert compile_source('local text = "require(ignored)"', "slua", config=config, runner=runner)["status"] == "completed"
