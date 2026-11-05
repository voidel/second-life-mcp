# Second Life MCP

Offline MCP reference tools for **LSL** and **SLua**, with separate language
components and a combined stdio server.

This is an initial development release: **1,640 LSL records and 1,993 SLua records**,
plus focused guidance. Both catalogs cover pinned official inventories plus supplemental SLua methods and callback types. A missing symbol
means "unverified in this snapshot", not "does not exist". The code checkers are
lexical aids, not compilers or simulators.

## Install and run

Requires Python 3.11 or newer.

```sh
python -m venv .venv
# Activate .venv using your platform's normal command.
python -m pip install -e ".[dev]"
second-life-mcp
```

The process waits for MCP traffic on stdin. Protocol traffic is the only output
on stdout; diagnostics use stderr. No network, database initialization, scraping,
credentials or Second Life account are required during normal use.

| Entry point | Component |
| --- | --- |
| `second-life-mcp` / `python -m second_life_mcp` | LSL and SLua |
| `lsl-mcp` / `python -m lsl_mcp` | LSL only |
| `slua-mcp` / `python -m slua_mcp` | SLua only |

Example MCP host configuration (replace the absolute path):

```json
{
  "mcpServers": {
    "second-life": {
      "command": "/absolute/path/to/.venv/bin/second-life-mcp",
      "args": []
    }
  }
}
```

On Windows, set `command` to the absolute
`.venv\\Scripts\\second-life-mcp.exe` path. Using an installed executable
makes startup independent of the client's working directory.

## Tools

Each component exposes five tools. Names begin with `lsl_` or `slua_`:

| Suffix | Purpose |
| --- | --- |
| `reference_status` | Coverage, counts, review dates and availability caveats |
| `lookup_symbol` | Exact case-sensitive lookup, signature, source and caveats |
| `search_reference` | Literal word search, kind filter and bounded pagination |
| `check_code` | Language-specific findings with severity, line and column |
| `get_guidance` | Source-backed pitfalls and migration advice by topic |

Resources `lsl://status` and `slua://status` expose the same coverage metadata.
All tools are read-only and accept text, never arbitrary file paths.

Example: call `slua_lookup_symbol` with `{"name":"LLTimers:every"}`, or
`lsl_lookup_symbol` with `{"name":"llGetNotecardLineSync"}`.
Misspellings return suggestions without silently selecting a different symbol.

LSL checks mask comments and quoted strings, then check a few unsupported
constructs, reserved identifiers and unmatched delimiters. Unknown ll calls are
informational because the catalog is partial. Global variables are allowed.

SLua checks use their own lexer, including long-bracket strings/comments.
They identify a few LSL operators and legacy call forms. Valid Luau conditional
expressions, type annotations and table indexing are not subjected to LSL rules.
Backtick interpolation bodies are opaque to this first checker; namespace
shadowing, callback lifecycles and type correctness are outside its analysis.

## SLua status and sources

SLua is based on **Luau**, with Second Life APIs and runtime behavior; generic
Lua or Roblox documentation is insufficient on its own. Linden Lab announced
[open beta in December 2025](https://community.secondlife.com/news/featured-news/announcing-the-slua-open-beta-modern-scripting-comes-to-second-life-r11237/).
Check current viewer and region support before deployment.

Reference entries link to the
[Second Life Wiki](https://wiki.secondlife.com/wiki/LSL_Portal),
[official creation documentation](https://create.secondlife.com/script/) or a
pinned revision of Linden Lab's
[canonical definitions](https://github.com/secondlife/lsl-definitions/tree/77cca2b0ee676c46dab7146a2cf63692cc6b91fe).
Imported records include structured parameters, return types, source flags, revision and hash. Import dates are distinct from manual review dates.

Create candidate snapshots from an immutable official commit:

```sh
second-life-import --revision 77cca2b0ee676c46dab7146a2cf63692cc6b91fe --output-dir candidate
```

The importer validates both catalogs before writing candidates and never changes the bundled data.
Use --source-dir for an already downloaded source set.

## Maintain and verify

```sh
python -m pytest
python -m build
second-life-source-audit
```

The audit command checks all five canonical sources against their pinned hashes.
It never updates the catalogs or their review dates.

Generate an atomic, reviewable candidate without changing bundled snapshots:

```sh
second-life-update --output-dir candidate --cache-dir .source-cache
```

The updater resolves the official main branch to one immutable revision before
fetching. It uses conditional HTTP requests, checks cached content hashes, bounds
retries and downloads, validates both catalogs, and writes a semantic changes.json.
Incomplete downloads never replace the bundled data. Existing candidate directories
are not overwritten. After reviewing the candidate, copy its two catalog files
and source_manifest.json into the package data directory and run tests before
committing. The manual CI workflow uploads candidates for review; it never
publishes them automatically.

See [contributing](CONTRIBUTING.md) and [data attribution](DATA_LICENSE.md).
