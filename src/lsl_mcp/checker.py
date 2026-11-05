"""A deliberately limited lexical checker, not an LSL compiler."""
from bisect import bisect_right
from dataclasses import dataclass
import re

from second_life_mcp.limits import MAX_CODE, MAX_ISSUES
TYPES = {"integer", "float", "string", "key", "vector", "rotation", "list"}
KEYWORDS = TYPES | {"default", "state", "if", "else", "while", "do", "for", "jump", "return"}
SOURCE = "https://wiki.secondlife.com/wiki/LSL_Flow_Control"
REGIONS = re.compile(r'"(?:\\[\s\S]|[^"\\])*"?|//[^\n]*|/\*[\s\S]*?(?:\*/|$)')
TOKENS = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|[^\s]")


@dataclass(frozen=True)
class Token:
    text: str
    start: int


def mask_noncode(code):
    chars = list(code)
    lexical = []
    for match in REGIONS.finditer(code):
        text = match.group()
        if text.startswith("/*") and not text.endswith("*/"):
            lexical.append(("unterminated-comment", match.start(), "Block comment has no closing */."))
        elif text.startswith('"'):
            # A terminal escaped quote does not terminate a string.
            slashes = len(text[:-1]) - len(text[:-1].rstrip("\\"))
            if len(text) < 2 or not text.endswith('"') or slashes % 2:
                lexical.append(("unterminated-string", match.start(), "String has no closing unescaped quote."))
        for i in range(match.start(), match.end()):
            if chars[i] not in "\r\n":
                chars[i] = " "
    return "".join(chars), lexical


def check_code(code, catalog):
    if len(code) > MAX_CODE:
        raise ValueError(f"Code exceeds {MAX_CODE} characters")
    masked, lexical = mask_noncode(code)
    tokens = [Token(m.group(), m.start()) for m in TOKENS.finditer(masked)]
    newlines = [-1] + [m.start() for m in re.finditer("\n", code)]
    suggestions_cache = {}
    issues = []
    has_errors = False
    diagnostics_capped = False

    def report(rule, start, message, severity="error", source=SOURCE):
        nonlocal has_errors, diagnostics_capped
        has_errors |= severity == "error"
        if len(issues) >= MAX_ISSUES:
            diagnostics_capped = True
            return
        line = bisect_right(newlines, start - 1)
        issues.append({
            "rule": rule, "severity": severity, "line": line,
            "column": start - newlines[line - 1], "message": message, "source_url": source,
        })

    for rule, start, message in lexical:
        report(rule, start, message)

    # Identify function definitions, including forward calls and ll-prefixed helpers.
    # Delimiter pairing also supports declarations with multiple parameters.
    pairs, stack = {}, []
    for i, token in enumerate(tokens):
        if token.text in ("(", "[", "{"):
            stack.append(i)
        elif token.text in (")", "]", "}"):
            expected = {")": "(", "]": "[", "}": "{"}[token.text]
            if not stack or tokens[stack[-1]].text != expected:
                report("unmatched-delimiter", token.start, f"Unexpected {token.text}.")
            else:
                pairs[stack.pop()] = i
    for i in stack:
        report("unmatched-delimiter", tokens[i].start, f"Unclosed {tokens[i].text}.")
    declared = set()
    for i, token in enumerate(tokens[:-1]):
        if tokens[i + 1].text == "(":
            end = pairs.get(i + 1)
            if end is not None and end + 1 < len(tokens) and tokens[end + 1].text == "{":
                declared.add(token.text)

    for i, token in enumerate(tokens):
        value = token.text
        following = tokens[i + 1].text if i + 1 < len(tokens) else ""
        if value == "?":
            report("unsupported-ternary", token.start, "Portable LSL has no ?: operator; use if/else.")
        elif value == "switch" and following == "(":
            report("unsupported-switch", token.start, "Portable LSL has no switch statement; use if/else.")
        elif value in TYPES and following in KEYWORDS:
            report("reserved-identifier", tokens[i + 1].start, f"{following} is reserved and cannot name a variable or parameter.",
                   source="https://wiki.secondlife.com/wiki/LSL_Variables")
        elif following == "(" and value.startswith(("ll", "os")) and value not in declared:
            if value.startswith("os"):
                report("nonportable-extension", token.start, f"{value} uses the OpenSimulator extension namespace; verify the target grid.",
                       severity="warning", source="https://wiki.secondlife.com/wiki/LSL_Portal")
            elif value not in catalog.symbols:
                if value not in suggestions_cache:
                    suggestions_cache[value] = catalog.lookup(value)["suggestions"] if len(issues) < MAX_ISSUES else []
                suggestions = suggestions_cache[value]
                report("unverified-function", token.start,
                       f"{value} is absent from this partial reference. Verify it against the official wiki."
                       + (f" Nearby names: {', '.join(suggestions)}." if suggestions else ""),
                       severity="information", source="https://wiki.secondlife.com/wiki/Category:LSL_Functions")
    issues.sort(key=lambda issue: (issue["line"], issue["column"], issue["rule"]))
    return {
        "issues": issues, "has_errors": has_errors,
        "diagnostics_capped": diagnostics_capped,
        "coverage": "partial", "compiler_validated": False,
        "note": "Only lexical rules ran. No type, arity, scope, permissions, timing or in-world validation was performed.",
    }
