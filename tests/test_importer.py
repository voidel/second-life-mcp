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


def test_import_minimal_pinned_inventory(tmp_path):
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

    for name, body in sources.items():
        (tmp_path / name).write_bytes(body)
    output = tmp_path / "candidate"
    completed = subprocess.run([sys.executable, "-m", "second_life_mcp.importer", "--source-dir", str(tmp_path),
        "--revision", "a" * 40, "--output-dir", str(output)], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert (output / "secondlife.d.luau").read_bytes() == sources["secondlife.d.luau"]


@pytest.mark.parametrize("mismatch", [False,True])
def test_canonical_metadata_survives_import_and_rejects_mismatch(mismatch):
    xml=b"""<llsd><map>
      <key>llsd-lsl-syntax-version</key><integer>2</integer>
      <key>functions</key><map><key>llExample</key><map>
        <key>return</key><string>integer</string>
        <key>arguments</key><array>
          <map><key>index</key><map><key>type</key><string>integer</string></map></map>
          <map><key>link</key><map><key>type</key><string>integer</string></map></map>
        </array>
      </map></map>
      <key>events</key><map><key>event</key><map/></map>
      <key>constants</key><map><key>CONSTANT</key><map><key>value</key><integer>1</integer><key>type</key><string>integer</string></map></map>
      <key>types</key><map><key>integer</key><map/></map>
    </map></llsd>"""
    metadata=b"""llsd-lsl-syntax-version: 2
functions:
  llExample:
    arguments:
      - index: {type: integer, index-semantics: true}
      - link: {type: integer, enum-semantics: Link}
    index-semantics: true
    pure: true
    requires-permission: [PERMISSION_TAKE_CONTROLS]
"""
    if mismatch:metadata=metadata.replace(b'- index:',b'- wrong:')
    sources={"lsl_keywords_pretty.xml":xml,"lua_keywords_pretty.xml":xml.replace(b'llExample',b'll.Example'),
        "lsl_definitions.yaml":metadata,"slua_definitions.yaml":b"version: 1.0.0\nbase-classes: []\nclasses: []\n",
        "secondlife.d.luau":b"declare extern type DetectedEvent with\n  function getKey(self): uuid\nend\n"}
    if mismatch:
        with pytest.raises(ValueError,match="Canonical argument name mismatch"):
            import_catalogs(sources,"a"*40)
        return
    catalogs,_=import_catalogs(sources,"a"*40)
    for language,prefix,base in [("lsl","ll",0),("slua","ll.",1)]:
        record=Catalog(language,document=catalogs[language]).lookup(prefix+"Example")["symbol"]
        assert record["parameters"][0]["index_base"]==base
        assert record["parameters"][1]["enum_semantics"]=="Link"
        assert record["parameters"][1]["index_base"] is None
        assert record["index_base"]==base and record["pure"] is True
        assert record["requires_permissions"]==["PERMISSION_TAKE_CONTROLS"]
        assert record["delay_seconds"] is None
        assert record["metadata_source_url"].endswith('/lsl_definitions.yaml')
