-- Fixed developer regression probes, never submitted MCP client code.
-- Pinned Second Life SLua v0.732.17; no simulator I/O or user assets.
assert(math.round(-0.5) == -1 and math.floor(-0.5 + 0.5) == 0)
assert(math.floor(-1.5 + 0.5) == -1 and math.round(-1.5) == -2)
assert(bit32.s32(4294967295) == -1)
assert(ll.List2String({1}, 1) == "1.000000")
assert(ll.List2String({1}, 2) == "")
assert(ll.GetSubString("abcd", 1, 2) == "ab")
assert(utf8.len("日本語") == 3 and #"日本語" == 9)
local a, b = vector(1, 2, 3), vector(4, 5, 6)
assert(a * b == vector(4, 10, 18) and vector.dot(a, b) == 32)
assert(vector.cross(a, b) == vector(-3, 6, -3))
local original = {1, 2, 3}
local copy = table.clone(original)
copy[1] = 9
assert(original[1] == 1 and table.find(original, 8) == nil)
local canonical = "abcdef12-3456-4789-abcd-123456789abc"
assert(tostring(touuid("abcdef12_3456_4789_abcd_123456789abc")) == canonical)
assert(not assert(touuid("00000000-0000-0000-0000-000000000000")).istruthy)
local decoded = lljson.decode('{"n":1.0,"a":[false,null]}')
assert(decoded.n == 1 and decoded.a[1] == false and decoded.a[2] == lljson.null)
print("MIGRATION_PROBES_OK")
