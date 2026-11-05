# Contributing

Keep LSL and SLua language semantics separate. Shared code owns transport,
catalog validation and search; the language components own diagnostics.

## Reference changes

1. Use current primary sources: Linden Lab's wiki, creation portal, official
   definitions or the SLua/Luau upstream source.
2. Add a compact original summary, exact spelling, signature, source URL and
   actual review date. Prefer pinned source revisions when available.
3. Preserve null for unknown delay data. Do not turn an unverified fact into a
   default value or infer availability from a function name.
4. Check that the documented API is implemented for the intended runtime.
   Requested, removed, privileged and preview APIs need explicit caveats.
5. Keep both catalogs marked partial until coverage can be measured against a
   versioned official inventory. Missing names must stay informational.
6. Run tests and build the wheel. Reference data must be included in the wheel.

Do not copy prose, example implementations or datasets without checking
attribution and terms. Retain source notices in DATA_LICENSE.md.

## Diagnostics

Each new rule needs a positive example and a plausible valid counterexample.
Preserve line breaks while masking comments/strings. Locations are one-based
Unicode code-point line/column positions. Never label a lexical pass as
"compiled" or claim permission, simulator timing or memory validation.
Do not send source code to a remote service or write it to logs.

## Checks

```sh
python -m pip install -e ".[dev]"
python -m pytest
python -m build
```

The real stdio tests launch subprocesses from unrelated working directories and
exercise both current and legacy MCP negotiation. They require no network.
CI tests Windows and Linux with Python 3.11–3.13.

Run `second-life-source-audit` explicitly when reviewing upstream changes.
It checks only the source manifest, not the whole reference. Update the source
baseline and review dates only after examining the changes. Failures leave data
untouched. The manual workflow never publishes data automatically.
