"""Run fixed migration probes only; the MCP service never executes client code."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import pytest

@pytest.mark.skipif(not os.environ.get("SECOND_LIFE_MCP_TEST_RUNTIME"), reason="Native developer runtime not configured")
def test_pinned_native_migration_semantics():
    record=json.loads(Path(os.environ["SECOND_LIFE_MCP_TEST_RUNTIME"]).read_text("utf-8"))
    executable=Path(record["executable"])
    assert executable.is_absolute() and executable.is_file()
    assert record["version"]=="v0.732.17"
    assert hashlib.sha256(executable.read_bytes()).hexdigest()==record["sha256"]
    flags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0
    result=subprocess.run([str(executable),"--sl",str(Path(__file__).with_name("native_migration_probes.luau"))],capture_output=True,text=True,encoding="utf-8",timeout=15,creationflags=flags)
    assert result.returncode==0,(result.stdout[-2000:],result.stderr[-2000:])
    assert "MIGRATION_PROBES_OK" in result.stdout
