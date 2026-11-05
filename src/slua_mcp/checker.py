"""Conservative SLua migration checks, independent of LSL syntax rules."""
from bisect import bisect_right
import re

from second_life_mcp.limits import MAX_CODE, MAX_ISSUES

SOURCE = "https://create.secondlife.com/script/learn-lua/from-lsl/"
LONG_OPEN = re.compile(r"\[(=*)\[")
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|~=|!=|&&|\|\||[^\s]")


def mask_noncode(code):
    chars = list(code)
    i = 0
    lexical = []
    while i < len(code):
        start = i
        comment = code.startswith("--", i)
        content_start = i + 2 if comment else i
        long = LONG_OPEN.match(code, content_start)
        if long:
            close = "]" + long.group(1) + "]"
            end = code.find(close, long.end())
            if end < 0:
                lexical.append(("unterminated-long-bracket", start, "Long bracket string or comment is unclosed."))
                i = len(code)
            else:
                i = end + len(close)
        elif comment:
            end = code.find("\n", content_start)
            i = len(code) if end < 0 else end
        elif code[i] in ("'", '"', "`"):
            quote = code[i]
            i += 1
            closed = False
            while i < len(code):
                if code[i] == "\\":
                    i += 2
                elif code[i] == quote:
                    i += 1
                    closed = True
                    break
                else:
                    i += 1
            i = min(i, len(code))
            if not closed:
                lexical.append(("unterminated-string", start, "Quoted string is unclosed."))
        else:
            i += 1
            continue
        for at in range(start, i):
            if chars[at] not in "\r\n":
                chars[at] = " "
    return "".join(chars), lexical


def check_code(code, catalog):
    if len(code) > MAX_CODE:
        raise ValueError(f"Code exceeds {MAX_CODE} characters")
    masked, lexical = mask_noncode(code)
    tokens = list(TOKEN.finditer(masked))
    newlines = [-1] + [m.start() for m in re.finditer("\n", code)]
    issues = []
    has_errors = False
    diagnostics_capped = False

    def report(rule, start, message, severity="warning"):
        nonlocal has_errors, diagnostics_capped
        has_errors |= severity == "error"
        if len(issues) >= MAX_ISSUES:
            diagnostics_capped = True
        else:
            line = bisect_right(newlines, start - 1)
            issues.append({"rule": rule, "severity": severity, "line": line,
                           "column": start - newlines[line - 1], "message": message, "source_url": SOURCE})

    for rule, start, message in lexical:
        report(rule, start, message, "error")
    declared = set(re.findall(r"\bfunction\s+(ll[A-Z]\w*)\s*\(", masked))
    declared.update(re.findall(r"\b(ll[A-Z]\w*)\s*=(?!=)", masked))
    for i, token in enumerate(tokens):
        text = token.group()
        following = tokens[i + 1].group() if i + 1 < len(tokens) else ""
        previous = tokens[i - 1].group() if i else ""
        if text in ("!=", "&&", "||", "!"):
            report("lsl-operator", token.start(), f"{text} is not a Luau operator; use ~=, and, or, or not as appropriate.", "error")
        elif re.fullmatch(r"ll[A-Z]\w*", text) and following == "(" and text not in declared and previous not in (".", ":"):
            report("legacy-lsl-call", token.start(), f"{text} resembles an LSL call. Look up its SLua ll namespace counterpart; verify the signature.")
        elif text in ("ll", "LLTimers", "LLEvents") and following in (".", ":") and i + 3 < len(tokens):
            member = tokens[i + 2].group()
            if tokens[i + 3].group() == "(":
                name = text + following + member
                if name not in catalog.symbols:
                    report("unverified-function", token.start(),
                           f"{name} is absent from the partial SLua snapshot; verify it against current official documentation.",
                           "information")
    issues.sort(key=lambda issue: (issue["line"], issue["column"], issue["rule"]))
    return {
        "issues": issues, "has_errors": has_errors,
        "diagnostics_capped": diagnostics_capped,
        "coverage": "partial", "compiler_validated": False,
        "note": "Lexical migration checks only. No Luau type/block/scope analysis or simulator execution. Backtick interpolation bodies are not inspected. Namespaces may be shadowed.",
    }
