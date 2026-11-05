"""Regressions for source metadata lost during a practical LSL/SLua migration."""
from copy import deepcopy
import json
import pytest
from pydantic import ValidationError
from second_life_mcp.reference import Catalog, Parameter
from second_life_mcp.migration import migration_guidance

@pytest.mark.parametrize("language,base", [("lsl",0),("slua",1)])
def test_index_origins_and_enums_remain_distinct(language,base):
    prefix="ll" if language=="lsl" else "ll."
    for suffix,index in [("List2String",1),("GetInventoryName",1),("GetNotecardLineSync",1),("GetSubString",1)]:
        row=Catalog(language).lookup(prefix+suffix)["symbol"]
        assert row["parameters"][index]["index_semantics"]
        assert row["parameters"][index]["index_base"]==base
        assert row["metadata_source_url"].endswith("/lsl_definitions.yaml")
        assert len(row["metadata_source_sha256"])==64
    link=Catalog(language).lookup(prefix+"GetLinkName")["symbol"]["parameters"][0]
    assert link["enum_semantics"]=="Link" and link["index_base"] is None
    assert not link["index_semantics"]
    face=Catalog(language).lookup(prefix+"GetLinkPrimitiveParams")["symbol"]["parameters"][0]
    assert face["index_base"] is None

def test_permissions_purity_and_unknowns_are_not_invented():
    for language,prefix in [("lsl","ll"),("slua","ll.")]:
        row=Catalog(language).lookup(prefix+"TakeControls")["symbol"]
        assert row["requires_permissions"]==["PERMISSION_TAKE_CONTROLS"]
        assert row["parameters"][1]["bool_semantics"]
        assert row["parameters"][1]["index_base"] is None
        assert Catalog(language).lookup(prefix+"GetSubString")["symbol"]["pure"] is True
        status=Catalog(language).status()
        assert status["caveat_coverage"]=="partial"
        assert status["behavioral_coverage"]["unknown_delays"]>0
        assert status["behavioral_coverage"]["known_delays"]>0

@pytest.mark.parametrize("value", [-1,2,True,"1"])
def test_index_metadata_rejects_invalid_origins(value):
    with pytest.raises(ValidationError):Parameter(name="index",type="integer",index_base=value)

def test_migration_keeps_rounding_uuid_and_event_recovery_caveats():
    report=migration_guidance("lsl",symbol="llRound")
    assert report["items"][0]["topic"]=="rounding"
    assert "-0.5" in report["items"][0]["summary"]
    for language in ("lsl","slua"):
        text=json.dumps(migration_guidance(language,topic="conversions"))
        assert "canonical UUID" in text and "arbitrary text" in text
        assert "generation/session" in json.dumps(migration_guidance(language,topic="timers"))
