import importlib.util
from pathlib import Path
import pytest
from second_life_mcp import __version__

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location("release_notes",ROOT/"tools/release_notes.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_current_release_has_reviewed_notes_and_matching_versions():
    notes=module.release_notes("v"+__version__,(ROOT/"README.md").read_text("utf-8"))
    assert "index" in notes and "SLua" in notes
    assert f'version = "{__version__}"' in (ROOT/"pyproject.toml").read_text("utf-8")
    assert f'name = "second-life-mcp"\nversion = "{__version__}"' in (ROOT/"uv.lock").read_text("utf-8")

@pytest.mark.parametrize("tag,text",[("bad",""),("v1.0.0",""),("v1.0.0","## Release 1.0.0\n"),("v1.0.0","## Release 1.0.0\na\n## Release 1.0.0\nb")])
def test_missing_empty_duplicate_or_invalid_notes_fail(tag,text):
    with pytest.raises(ValueError):module.release_notes(tag,text)

def test_notes_stop_at_next_section():
    assert module.release_notes("v1.0.0","## Release 1.0.0\nHello\n## Other\nHidden") == "Hello\n"
