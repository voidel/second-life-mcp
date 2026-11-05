import pytest

from lsl_mcp.checker import check_code as lsl_check, MAX_CODE
from slua_mcp.checker import check_code as slua_check
from second_life_mcp.reference import Catalog


def lsl(code):
    return lsl_check(code, Catalog())


def slua(code):
    return slua_check(code, Catalog("slua"))


def test_lsl_globals_and_forward_helpers_are_valid():
    result = lsl('integer count; default { state_entry() { count++; llHelper(); } } llHelper() { llOwnerSay("ok"); }')
    assert result["issues"] == []
    assert result["compiler_validated"] is False


def test_lsl_masks_comments_strings_and_escaped_quotes():
    code = r'// switch(x) llFake() ? a : b' + "\n" + r'default { state_entry() { string s = "llFake() \" ? x : y"; /* integer key; */ } }'
    assert lsl(code)["issues"] == []


def test_lsl_multiline_ternary_and_locations():
    code = 'default {\r\n state_entry() {\r\n integer x = TRUE\r\n ? 1\r\n : 2;\r\n }\r\n}'
    issue = lsl(code)["issues"][0]
    assert issue["rule"] == "unsupported-ternary"
    assert (issue["line"], issue["column"]) == (4, 2)


def test_lsl_detects_specific_errors_and_unknown_is_only_information():
    result = lsl("default { state_entry() { integer key; switch (1) {} llNotInSnapshot(); } }")
    rules = {i["rule"]: i["severity"] for i in result["issues"]}
    assert rules["reserved-identifier"] == "error"
    assert rules["unsupported-switch"] == "error"
    assert rules["unverified-function"] == "information"
    assert lsl("default { state_entry() { llNewFunction(); } }")["has_errors"] is False


@pytest.mark.parametrize("code,rule", [
    ('"unclosed', "unterminated-string"),
    ("/* unclosed", "unterminated-comment"),
    ("default {", "unmatched-delimiter"),
    ("}", "unmatched-delimiter"),
])
def test_lsl_malformed_regions(code, rule):
    assert rule in {i["rule"] for i in lsl(code)["issues"]}


def test_slua_valid_luau_features_do_not_trigger_lsl_rules():
    code = """local x: number? = nil
local values = {1, 2, 3}
values[0] = 4
local result = if x then 1 else 2
LLEvents:on("touch_start", function(events)
    ll.Say(0, tostring(values[1]))
end)
local timer = LLTimers:every(0.5, function(scheduled, interval) end)
LLTimers:off(timer)
"""
    assert slua(code)["issues"] == []


@pytest.mark.parametrize("literal", [
    '"llSay() != &&"', "'llSay() != &&'", "[[llSay() != &&]]",
    "[==[llSay() != &&]==]", "`llSay() != &&`",
    "-- llSay() != &&", "--[[ llSay() != && ]]", "--[==[ llSay() != && ]==]",
])
def test_slua_masks_literals_and_comments(literal):
    assert slua(literal)["issues"] == []


def test_slua_strings_preserve_following_diagnostic_location():
    result = slua('--[==[llSay()\n]==]\nllSay(0, "hello")')
    issue = result["issues"][0]
    assert issue["rule"] == "legacy-lsl-call"
    assert (issue["line"], issue["column"]) == (3, 1)


def test_slua_helpers_and_table_methods_do_not_look_like_lsl_globals():
    assert slua("local function llHelper() end\nllHelper()\nobj.llCustom()")["issues"] == []


def test_slua_operator_errors_and_unverified_names():
    result = slua("if x != 0 && y || !z then ll.Missing() end")
    assert result["has_errors"]
    assert len([i for i in result["issues"] if i["severity"] == "error"]) == 4
    assert result["issues"][-1]["severity"] == "information"
    assert slua("if x ~= nil and not y then end")["issues"] == []


@pytest.mark.parametrize("code", ["[=[unclosed", "--[==[unclosed", "'unclosed"])
def test_slua_unclosed_regions(code):
    assert slua(code)["has_errors"]


@pytest.mark.parametrize("checker", [lsl, slua])
def test_input_and_output_caps(checker):
    with pytest.raises(ValueError):
        checker("x" * (MAX_CODE + 1))
    result = checker("llNoSuchEntry();\n" * 1000)
    assert len(result["issues"]) == 100
    assert result["diagnostics_capped"]


@pytest.mark.parametrize("checker,bad", [(lsl, "integer key;"), (slua, "if x != y then end")])
def test_error_summary_remains_true_after_diagnostic_cap(checker, bad):
    result = checker("llUnknown();\n" * 100 + bad)
    assert result["has_errors"] is True
    assert result["diagnostics_capped"] is True
    assert len(result["issues"]) == 100
