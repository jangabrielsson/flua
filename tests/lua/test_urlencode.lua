-- urlencode(): the HC3's URL percent-encoding, byte-for-byte.
local script_dir = (_FLUA.arg[0] or "."):match("^(.*)[/\\]") or "."
local t = dofile(script_dir .. "/helpers.lua")

t.expect(type(urlencode) == "function", "urlencode global exists")
t.expect(urlencode(nil) == nil, "nil passes through")
t.expect(urlencode("") == "", "empty string passes through")

-- unreserved characters stay untouched
t.expect(urlencode("azAZ09-_.~") == "azAZ09-_.~", "unreserved kept")

-- space -> %20
t.expect(urlencode("a b") == "a%20b", "space is %20")

-- \n -> \r\n first, then encoded (the HC3 quirk)
t.expect(urlencode("a\nb") == "a%0D%0Ab", "newline becomes CRLF then %0D%0A")

-- other bytes -> %XX, per UTF-8 byte (å is C3 A5)
t.expect(urlencode("å") == "%C3%A5", "multibyte encoded per byte")
t.expect(urlencode("%") == "%25", "percent itself is encoded")
t.expect(urlencode("a/b?c=d&e") == "a%2Fb%3Fc%3Dd%26e", "reserved URL chars encoded")

t.done()
