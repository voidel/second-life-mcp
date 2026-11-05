import json
from pathlib import Path
import subprocess
import sys

import pytest

from second_life_mcp.importer import parse_llsd, import_catalogs
from second_life_mcp.reference import Catalog


@pytest.mark.parametrize("body", [
    b'<!DOCTYPE llsd [<!ENTITY a "bad">]><llsd><string>&a;</string></llsd>',
    b'<llsd><map><key>x</key></map></llsd>',
    b'<llsd><map><key>x</key><string>a</string><key>x</key><string>b</string></map></llsd>',
    b'<llsd><map><key>llsd-lsl-syntax-version</key><integer>99</integer></map></llsd>',
])
def test_reject_malformed_or_unsafe_xml(body):
    with pytest.raises(ValueError):
        parse_llsd(body)


def test_import_rejects_incomplete_sources_and_floating_revision():
    with pytest.raises(ValueError):
        import_catalogs({}, "main")
    with pytest.raises(ValueError):
        import_catalogs({}, "0" * 40)


def test_official_snapshot_has_structured_types_and_provenance():
    for language in ("lsl", "slua"):
        catalog = Catalog(language)
        assert len(catalog.records) >= 1600
        assert len(catalog.snapshot.sources) == 5
        assert catalog.snapshot.coverage == "official_snapshot"
        assert catalog.status()["oldest_review"] is None
        assert all(row.source_revision and row.source_sha256 for row in catalog.records)
    call = Catalog().lookup("llHTTPRequest")["symbol"]
    assert call["return_type"] == "key"
    assert [p["name"] for p in call["parameters"]] == ["url", "parameters", "body"]
    assert "deprecated" in Catalog().lookup("llSetPrimitiveParams")["symbol"]["flags"]
    assert Catalog("slua").lookup("touch_start")["symbol"]["parameters"][0]["type"] == "{DetectedEvent}"
    assert Catalog("slua").lookup("DetectedEvent:getKey")["symbol"]["return_type"] == "uuid"
    assert Catalog("slua").lookup("LLTimerEveryCallback")["symbol"]["type"] == "(scheduled: number, interval: number) -> ()"


def test_constructor_and_type_are_both_retained():
    result = Catalog("slua").lookup("vector")
    assert result["symbol"]["kind"] == "function"
    assert any(row["kind"] == "type" for row in result["alternatives"])
    assert Catalog("slua").search("vector", kind="type")["results"]


def test_invalid_cli_source_set_never_writes_output(tmp_path):
    target = tmp_path / "candidate"
    result = subprocess.run([sys.executable, "-m", "second_life_mcp.importer",
        "--source-dir", str(tmp_path), "--revision", "0" * 40, "--output-dir", str(target)],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert not target.exists()


def test_import_minimal_pinned_inventory():
    xml = b"""<llsd><map>
      <key>llsd-lsl-syntax-version</key><integer>2</integer>
      <key>functions</key><map><key>example</key><map><key>return</key><string>integer</string></map></map>
      <key>events</key><map><key>event</key><map/></map>
      <key>constants</key><map><key>CONSTANT</key><map><key>value</key><integer>1</integer><key>type</key><string>integer</string></map></map>
      <key>types</key><map><key>integer</key><map/></map>
    </map></llsd>"""
    sources = {"lsl_keywords_pretty.xml": xml, "lua_keywords_pretty.xml": xml,
        "slua_definitions.yaml": b"version: 1.0.0\nbase-classes: []\nclasses: []\n",
        "lsl_definitions.yaml": b"llsd-lsl-syntax-version: 2\n",
        "secondlife.d.luau": b"declare extern type DetectedEvent with\n  function getKey(self): uuid\nend\n"}
    catalogs, manifest = import_catalogs(sources, "a" * 40, imported_on="2026-11-05")
    assert len(catalogs["lsl"]["symbols"]) == 4
    assert len(catalogs["slua"]["symbols"]) == 5
    assert all(row["revision"] == "a" * 40 for row in manifest)
    assert Catalog(document=catalogs["lsl"]).lookup("CONSTANT")["symbol"]["value"] == "1"
