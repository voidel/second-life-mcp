"""Extract the matching reviewed README release section; never publish on its own."""
from pathlib import Path
import re
import sys

def release_notes(tag, readme):
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?",tag):
        raise ValueError("Expected a semantic version tag")
    marker="## Release "+tag[1:]+"\n"
    if readme.count(marker)!=1:
        raise ValueError("Expected one matching README release section")
    body=readme.split(marker,1)[1].split("\n## ",1)[0].strip()
    if not body:raise ValueError("Release notes are empty")
    return body+"\n"

if __name__=="__main__":
    print(release_notes(sys.argv[1],Path(__file__).resolve().parents[1].joinpath("README.md").read_text("utf-8")),end="")
