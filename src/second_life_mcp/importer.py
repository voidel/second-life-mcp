"""Import versioned, MIT-licensed Linden Lab reference data; never execute it."""
import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import yaml

from .reference import Catalog

REPOSITORY = "secondlife/lsl-definitions"
SOURCE_FILES = ("lsl_keywords_pretty.xml", "lua_keywords_pretty.xml", "slua_definitions.yaml", "secondlife.d.luau", "lsl_definitions.yaml")
SOURCE_PATHS = {name: ("generated/" + name if name.endswith((".xml", ".luau")) else name) for name in SOURCE_FILES}
MAX_SOURCE_BYTES = 4 * 1024 * 1024


def parse_llsd(body):
    if len(body) > MAX_SOURCE_BYTES or b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ValueError("Oversized XML or unsupported XML declarations")
    root = ET.fromstring(body)
    def read(node):
        if node.tag == "map":
            children = list(node)
            if len(children) % 2 or any(children[i].tag != "key" for i in range(0, len(children), 2)):
                raise ValueError("Malformed LLSD map")
            result = {}
            for i in range(0, len(children), 2):
                key = children[i].text
                if key in result:
                    raise ValueError("Duplicate LLSD key")
                result[key] = read(children[i + 1])
            return result
        if node.tag == "array":
            return [read(child) for child in node]
        if node.tag in ("string", "uri", "uuid"):
            return node.text or ""
        if node.tag == "integer":
            return int(node.text)
        if node.tag == "real":
            return float(node.text)
        if node.tag == "boolean":
            return node.text in ("true", "1")
        raise ValueError(f"Unsupported LLSD node: {node.tag}")
    if root.tag != "llsd" or len(root) != 1:
        raise ValueError("Expected one LLSD document")
    result = read(root[0])
    if result.get("llsd-lsl-syntax-version") != 2:
        raise ValueError("Unsupported official syntax version")
    for bucket in ("functions", "events", "constants", "types"):
        if not isinstance(result.get(bucket), dict) or not result[bucket]:
            raise ValueError(f"Missing official inventory: {bucket}")
    return result


def parameters(arguments):
    result = []
    for entry in arguments:
        if not isinstance(entry, dict) or len(entry) != 1:
            raise ValueError("Malformed official parameter")
        name, data = next(iter(entry.items()))
        result.append({"name": name, "type": data["type"], "description": data.get("tooltip", ""),
                       "optional": data["type"].endswith("?"), "variadic": name == "..."})
    return result


def signature(name, kind, args, returns, language):
    if kind == "type":
        return name
    if language == "lsl":
        params = ", ".join(f'{p["type"]} {p["name"]}' for p in args)
        prefix = f"{returns} " if kind == "function" and returns != "void" else ""
        return f"{prefix}{name}({params})"
    params = ", ".join(f'{p["name"]}: {p["type"]}' for p in args)
    return f"{name}({params})" + (f": {returns}" if kind == "function" else "")


def split_parameters(text):
    parts, start, stack, quote = [], 0, [], None
    for i, char in enumerate(text):
        if quote:
            if char == quote and (i == 0 or text[i - 1] != "\\"):
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif char in "([{<":
            stack.append(char)
        elif char in ")]}>":
            if stack and char != ">":
                stack.pop()
            elif char == ">" and stack and stack[-1] == "<":
                stack.pop()
        elif char == "," and not stack:
            parts.append(text[start:i].strip())
            start = i + 1
    if text[start:].strip():
        parts.append(text[start:].strip())
    return parts


def import_catalogs(bodies, revision, imported_on=None):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("An immutable 40-character commit revision is required")
    if set(bodies) != set(SOURCE_FILES) or any(len(body) > MAX_SOURCE_BYTES for body in bodies.values()):
        raise ValueError("Incomplete or oversized official source set")
    imported_on = imported_on or date.today().isoformat()
    manifests = [{
        "name": name, "path": SOURCE_PATHS[name], "revision": revision,
        "sha256": hashlib.sha256(bodies[name]).hexdigest(),
        "git_blob_sha": hashlib.sha1(b"blob " + str(len(bodies[name])).encode() + b"\0" + bodies[name]).hexdigest(),
        "url": f"https://raw.githubusercontent.com/{REPOSITORY}/main/{SOURCE_PATHS[name]}",
        "pinned_url": f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/{SOURCE_PATHS[name]}",
    } for name in SOURCE_FILES]
    source_by_name = {row["name"]: row for row in manifests}
    lsl_metadata = yaml.safe_load(bodies["lsl_definitions.yaml"])
    if not isinstance(lsl_metadata, dict) or lsl_metadata.get("llsd-lsl-syntax-version") != 2:
        raise ValueError("Invalid canonical LSL metadata")
    catalogs = {}
    for language, filename in (("lsl", SOURCE_FILES[0]), ("slua", SOURCE_FILES[1])):
        doc = parse_llsd(bodies[filename])
        symbols = {}
        def make(name, kind, data, source=filename):
            args = parameters(data.get("arguments", []))
            returns = data.get("return", "void" if language == "lsl" else "()")
            flags = [flag for flag in ("deprecated", "god-mode", "private") if data.get(flag) in ("true", True, "1")]
            summary = data.get("tooltip", "").replace("\\n", "\n").strip() or f"Official {language.upper()} {kind}: {name}."
            symbol = {
                "name": name, "kind": kind, "signature": signature(name, kind, args, returns, language),
                "summary": summary, "parameters": args, "return_type": returns if kind == "function" else None,
                "value": str(data["value"]) if "value" in data else None,
                "type": data.get("type"), "type_parameters": data.get("type-arguments", []),
                "source_url": f"https://github.com/{REPOSITORY}/blob/{revision}/{SOURCE_PATHS[source]}",
                "source_revision": revision, "source_sha256": source_by_name[source]["sha256"],
                "imported_on": imported_on, "reviewed_on": None, "tags": [kind],
                "caveats": [f"Official source flag: {flag}." for flag in flags], "flags": flags,
                "delay_seconds": float(data["sleep"]) if "sleep" in data else None,
            }
            # Generated tooltips omit semantic tags and can retain LSL index prose.
            # Read canonical metadata without guessing from parameter names/types.
            canonical_name = "ll" + name[3:] if language == "slua" and name.startswith("ll.") else name
            metadata_bucket = {"function": "functions", "event": "events", "constant": "constants"}.get(kind, "")
            meta = lsl_metadata.get(metadata_bucket, {}).get(canonical_name, {})
            if meta and (language == "lsl" or (kind == "function" and name.startswith("ll."))):
                semantic_source = source_by_name["lsl_definitions.yaml"]
                symbol.update(metadata_source_url=f"https://github.com/{REPOSITORY}/blob/{revision}/lsl_definitions.yaml",
                              metadata_source_sha256=semantic_source["sha256"],
                              pure=meta.get("pure"), requires_permissions=meta.get("requires-permission", []),
                              index_base=(0 if language == "lsl" else 1) if meta.get("index-semantics") else None)
                canonical_args = meta.get("arguments", [])
                if canonical_args and len(canonical_args) != len(args):
                    raise ValueError(f"Canonical argument count mismatch: {name}")
                for parameter, original in zip(args, canonical_args):
                    if len(original) != 1 or parameter["name"] not in original:
                        raise ValueError(f"Canonical argument name mismatch: {name}")
                    semantics = original[parameter["name"]]
                    indexed = semantics.get("index-semantics", False)
                    parameter.update(index_semantics=indexed,
                                     index_base=(0 if language == "lsl" else 1) if indexed else None,
                                     enum_semantics=semantics.get("enum-semantics"),
                                     bool_semantics=semantics.get("bool-semantics", False))
                    if indexed and language == "slua":
                        parameter["description"] += " [SLua uses one-based index semantics; inherited LSL tooltip wording may describe zero-based indexing. Check negative indices and sentinels separately.]"
                if language == "slua" and (symbol["index_base"] is not None or any(p.get("index_semantics") for p in args)):
                    symbol["caveats"].append("Canonical index-semantics use a one-based origin in SLua. Enum/link/face arguments are not shifted. Do not blindly translate negative indices or not-found sentinels.")
            if kind == "constant":
                symbol["signature"] = f'{data.get("type", "keyword")} {name}' + (f' = {data["value"]}' if "value" in data else "")
            if language == "lsl":
                meta = lsl_metadata.get({"function": "functions", "event": "events", "constant": "constants"}.get(kind, ""), {}).get(name, {})
                symbol["tags"] += meta.get("categories", [])
                if meta.get("slua-removed"):
                    symbol["caveats"].append("Removed from the SLua API; migration requires a different pattern.")
            return symbol
        for bucket, kind in (("functions", "function"), ("events", "event"), ("constants", "constant"), ("types", "type")):
            for name, record in doc[bucket].items():
                if (kind, name) in symbols:
                    raise ValueError(f"Duplicate inventory name: {name}")
                symbols[(kind, name)] = make(name, kind, record)
        if language == "slua":
            supplement = yaml.safe_load(bodies["slua_definitions.yaml"])
            if not isinstance(supplement, dict) or supplement.get("version") != "1.0.0":
                raise ValueError("Unsupported supplemental SLua schema")
            for cls in supplement["base-classes"] + supplement["classes"]:
                for method in cls.get("methods", []) + cls.get("functions", []):
                    if method.get("private") or method.get("slua-removed"):
                        continue
                    is_method = method in cls.get("methods", [])
                    name = cls["name"] + (":" if is_method else ".") + method["name"]
                    args = [{"name": p["name"], "type": p.get("type", "any"),
                             "description": p.get("comment", ""), "optional": p.get("optional", p.get("type", "").endswith("?")),
                             "variadic": p["name"] == "..."} for p in method.get("parameters", []) if p.get("name") != "self"]
                    record = make(name, "function", {"tooltip": method.get("comment", cls.get("comment", ""))}, "slua_definitions.yaml")
                    record.update(parameters=args, return_type=method.get("return-type", "()"),
                                  signature=signature(name, "function", args, method.get("return-type", "()"), language))
                    record["overloads"] = method.get("overloads", [])
                    symbols[("function", name)] = record
            declarations = bodies["secondlife.d.luau"].decode("utf-8")
            for match in re.finditer(r"^(?:export )?type (\w+) = ([^\n]+)$", declarations, re.M):
                name, definition = match.groups()
                if definition.endswith(("{", "(")):
                    continue
                row = make(name, "type", {"tooltip": "Official SLua type alias."}, "secondlife.d.luau")
                row.update(signature=f"type {name} = {definition}", type=definition)
                symbols[("type", name)] = row
            # Generated detection methods are absent from the YAML class stub.
            detected = re.search(r"declare extern type DetectedEvent with\n(.*?)^end$", declarations, re.M | re.S)
            if not detected:
                raise ValueError("Missing generated detected-event class")
            for name, params, returns in re.findall(r"^  function (\w+)\((.*?)\): (.+)$", detected.group(1), re.M):
                args = []
                for p in split_parameters(params):
                    if p == "self":
                        continue
                    param_name, param_type = p.split(":", 1)
                    args.append({param_name.strip(): {"type": param_type.strip()}})
                full_name = "DetectedEvent:" + name
                symbols[("function", full_name)] = make(full_name, "function", {"arguments": args, "return": returns,
                                                               "tooltip": "Read or update detection data for this event."}, "secondlife.d.luau")
        counts = {bucket: len(doc[bucket]) for bucket in ("functions", "events", "constants", "types")}
        snapshot = {"schema_version": 2, "language": language, "coverage": "official_snapshot",
                    "inventory_counts": counts, "sources": manifests,
                    "symbols": sorted(symbols.values(), key=lambda s: s["name"])}
        Catalog(language, document=snapshot)
        catalogs[language] = snapshot
    return catalogs, manifests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.revision):
        parser.error("--revision must be an immutable commit hash")
    bodies = {}
    for name in SOURCE_FILES:
        if args.source_dir:
            bodies[name] = (args.source_dir / name).read_bytes()
        else:
            url = f"https://raw.githubusercontent.com/{REPOSITORY}/{args.revision}/{SOURCE_PATHS[name]}"
            with urlopen(Request(url, headers={"User-Agent": "second-life-mcp-import"}), timeout=20) as response:
                bodies[name] = response.read(MAX_SOURCE_BYTES + 1)
    catalogs, manifest = import_catalogs(bodies, args.revision)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for language, document in catalogs.items():
        (args.output_dir / f"{language}.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / "secondlife.d.luau").write_bytes(bodies["secondlife.d.luau"])
    (args.output_dir / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({lang: {"symbols": len(doc["symbols"]), "inventory": doc["inventory_counts"]} for lang, doc in catalogs.items()}))


if __name__ == "__main__":
    main()
