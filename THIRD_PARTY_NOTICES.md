# Third-party notices

flua itself is MIT licensed — see [LICENSE](LICENSE). The third-party
components below ship inside flua's tree (and can travel inside QA archives
to the HC3) under their own licenses. Each file keeps its copyright and
license notice in its own header; this file collects them and carries the
license texts.

## MobDebug

- **Where**: `src/flua/lua/mobdebug.lua`
- **Upstream**: https://github.com/pkulchenko/MobDebug
- **Copyright**: 2011–2020 Paul Kulchenko; based on RemDebug 1.0, Copyright Kepler Project 2005
- **License**: MIT
- **Note**: the vendored copy carries flua patches (socket poll pacing,
  socket-error propagation, detach on closed connection, hook installed
  only while stepping or when breakpoints exist). Changes are documented
  in the file header and marked `flua patch`.

## serpent

- **Where**: embedded in `src/flua/lua/mobdebug.lua` (MobDebug's serializer)
- **Upstream**: https://github.com/pkulchenko/serpent
- **Copyright**: 2012–2018 Paul Kulchenko
- **License**: MIT (version 0.302)

## aeslua

- **Where**: `src/flua/lua/lib/aeslua53.lua` (bundled QA library, `--%%file:$aeslua53.lua`)
- **Upstream**: https://github.com/bighil/aeslua (Lua 5.3 port)
- **Copyright**: 2006, 2007 Matthias Hilbig
- **License**: GNU Lesser General Public License, version 2.1 or later (LGPL 2.1+)
- **Note**: kept as a separate, replaceable file, as LGPL requires. The
  license notice is in the file header; the full LGPL 2.1 text is at
  https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html

## sha2 (pure_lua_SHA)

- **Where**: `src/flua/lua/lib/sha2.lua` (bundled QA library, `--%%file:$sha2.lua`)
- **Upstream**: https://github.com/Egor-Skriptunoff/pure_lua_SHA (trimmed by tinman/Intuitech for the HC3)
- **Copyright**: Egor Skriptunoff
- **License**: MIT

## Not vendored, but used

- **lupa** — flua's runtime Lua bridge, installed as a Python dependency
  (not shipped in this tree). MIT style. https://github.com/scoder/lupa

## MIT license text

The following copyright and permission notice covers MobDebug, serpent,
and pure_lua_SHA:

Copyright (c) 2011-2020 Paul Kulchenko (MobDebug)
Copyright (c) 2012-2018 Paul Kulchenko (serpent)
Copyright (c) Egor Skriptunoff (pure_lua_SHA)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
