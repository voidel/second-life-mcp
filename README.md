# Second Life MCP

Offline MCP tools for Second Life **LSL** and **SLua**: API reference, caveats,
migration guidance and optional local compilation. Includes 1,640 LSL and 1,993
SLua records from pinned official sources.

## Install

Requires Python 3.11+. Install the [1.0.0 release](https://github.com/voidel/second-life-mcp/releases/tag/v1.0.0)
in your Python environment:

```sh
python -m pip install https://github.com/voidel/second-life-mcp/releases/download/v1.0.0/second_life_mcp-1.0.0-py3-none-any.whl
```

The release includes a source archive and SHA-256 checksums. The package is not
published to PyPI. Normal use requires no network, credentials or Second Life account.

## Connect

Add this to your MCP client's configuration, replacing the interpreter path:

```json
{
  "mcpServers": {
    "second-life": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "second_life_mcp"]
    }
  }
}
```

On Windows, use the environment's `Scripts\python.exe`. Client-specific examples:
[Claude Code](examples/clients/claude-code.json) and [VS Code](examples/clients/vscode.json).

The server uses stdio and waits for MCP requests. Use `lsl_mcp` or `slua_mcp`
instead of `second_life_mcp` for a single language. Console commands are
`second-life-mcp`, `lsl-mcp` and `slua-mcp`.

## Tools

Tool names start with `lsl_` or `slua_`. All are read-only.

| Suffix | Purpose |
| --- | --- |
| `reference_status` | Coverage, source revisions and review dates |
| `lookup_symbol` | Exact signature, parameter semantics, source and caveats |
| `search_reference` | Literal search with filters and pagination |
| `check_code` | Lexical diagnostics with line and column |
| `compile_code` | Optional local compilation and SLua type checking |
| `get_guidance` | Reviewed pitfalls by topic |
| `migration_guidance` | LSL/SLua API and behavior comparisons |

Examples:

- `slua_lookup_symbol`: `{"name":"LLTimers:every"}`
- `lsl_migration_guidance`: `{"symbol":"llSetTimerEvent"}`
- `lsl_get_guidance`: `{"topic":"async-recovery"}`

Status is also available through `lsl://status` and `slua://status` resources.
Lookups include index origins, enum/boolean semantics, permissions and provenance
where verified. Unknown symbols are not automatically corrected or declared invalid.

## Compiler setup

```sh
second-life-toolchains --output-dir .toolchains
```

This downloads the hash-pinned SLua v0.732.17 compiler and luau-lsp 1.70.1 analyzer
for Windows/Linux x86-64. Set `SECOND_LIFE_MCP_TOOLCHAINS` in your MCP host's
environment to the absolute `.toolchains/toolchains.json` path.

LSL uses SLua's LSL compiler frontend; SLua uses compilation and optional type
analysis against the bundled official definitions. Checks are time-limited,
verify executable hashes and never execute submitted code. Single-file checks
do not resolve imports. No compiler is downloaded during MCP requests.

## Limits and sources

`check_code` is lexical, not compilation. It does not establish types, callback
lifecycles or runtime safety; SLua backtick interpolation bodies are not inspected.
Compilation also cannot verify simulator timing, memory, throttles or rendering.
Empty caveats do not prove safety, and a null delay means unknown. Confirm SLua
viewer/region support before deployment.

References use the [Second Life Wiki](https://wiki.secondlife.com/wiki/LSL_Portal),
[creation documentation](https://create.secondlife.com/script/) and
[pinned official definitions](https://github.com/secondlife/lsl-definitions/tree/77cca2b0ee676c46dab7146a2cf63692cc6b91fe).
Import dates and manual review dates are recorded separately.

## Development

```sh
python -m pip install uv==0.13.7
uv sync --locked --extra dev
uv run --no-sync python -m pytest
uv run --no-sync second-life-evaluate
uv run --no-sync python -m build
```

For compiler and fixed native-runtime tests, fetch the toolchains above and set
`SECOND_LIFE_MCP_TOOLCHAINS` and `SECOND_LIFE_MCP_TEST_RUNTIME` to the absolute
`toolchains.json` and `test-runtime.json` paths. CI tests Windows/Linux with
Python 3.11–3.13. Evaluations exercise real MCP transport, not in-world behavior.

`second-life-source-audit` checks upstream fingerprints. To prepare a reviewable
reference update without changing bundled data:

```sh
second-life-update --output-dir candidate --cache-dir .source-cache
```

Review candidates before applying them. See [contributing](CONTRIBUTING.md) and
[data attribution](DATA_LICENSE.md).

## Release 1.0.0

- Canonical index, enum and boolean semantics, permissions and purity metadata.
- Expanded SLua migration guidance and behavior caveats.
- Native semantic regressions and stable wheel/source releases with checksums.
