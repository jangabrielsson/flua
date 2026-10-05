# 09 · Multi-file QAs — your own libraries

The lamp has grown, and so will the next QuickApp. Before copy-pasting the
same helper into every QA, learn the HC3's answer: a QuickApp can consist of
**several files** — one main file plus your own libraries, packed and
deployed together as one device.

## Declaring extra files

The header directive `--%%file:path,name` adds a file. The files load **in
declaration order, before the main file**, and share the same environment —
a function defined in a library is simply there when the main file runs:

```lua
--%%name:multifile-demo
--%%file:multifile/lib.lua,lib
-- --------------- EOH ---------------
function QuickApp:onInit()
  print("helper says:", helper())
end
```

`multifile/lib.lua`:

```lua
function helper()
  return "loaded in order"
end
```

Run it:

```bash
flua --api local examples/multifile.lua
```

```text
🚀 flua 0.1.14 (Lua 5.5, Python 3.14.3), mode offline
[05.10.2026][10:33:55][DEBUG  ][multifile-demo5000]: helper says: loaded in order
```

That's the whole feature. The `,lib` part is the file's *name* on the HC3
(the path is where it lives on your disk — relative to the main file);
flua reports both when you ask:

```lua
local files = api.get("/quickApp/"..self.id.."/files")
for _, f in ipairs(files) do print("file:", f.name) end
```

```text
file: main
file: lib
```

## What libraries are good for

- **Shared helpers** — parsing, formatting, time math, the `findDevice`
  pattern from chapter 10 — written once, used by every QA that declares
  the file.
- **Big QAs, organized** — the lamp's sun logic, its UI callbacks and its
  actions can live in separate files instead of one long scroll.
- **Versioned code** — swap one library file to upgrade a behavior across
  QAs.

Two ground rules:

- The files are **one program**, not several QAs — a library has no
  `--%%name`, no `onInit` of its own (well, its top-level code *does* run,
  in declaration order — but one QA, one life).
- `--%%` lines in a library file are just comments to flua — directives are
  read from the **main file only**.

## Deploying multi-file QAs

`--tool uploadQA` packs the main file and every `--%%file` into one package
(the `.fqa` format the HC3 app understands), so the whole QA — libraries
included — travels as one device:

```bash
flua --tool uploadQA main.lua     # packs + uploads all declared files
flua --tool updateQA 123 main.lua # same, into an existing QA
```

And the other direction, `downloadQA`, writes the files out with names that
carry the HC3 id — `My QA_main_123.lua`, `My_QA_lib_123.lua` — so a
downloaded QA is a working flua project you can edit and re-upload.

## The Sunset Lamp, refactored

A taste of the payoff. Move the sun logic into `sun.lua`:

```lua
-- sun.lua — the lamp's library: everything about the sun
function sunMinutes()
  local h, m = fibaro.getValue(1, "sunsetHour"):match("(%d+):(%d+)")
  return tonumber(h) * 60 + tonumber(m)
end

function isAfterSunset()
  local now = os.date("*t")
  return now.hour * 60 + now.min >= sunMinutes()
end
```

…and the lamp's main file becomes smaller, with the library declared in the
header:

```lua
--%%name:SunsetLamp
--%%type:com.fibaro.binarySwitch
--%%file:sun.lua,sun

function QuickApp:checkSun()
  if not self:getVariable("auto") then return end
  if isAfterSunset() and not self.properties.value then
    self:turnOn()
  elseif not isAfterSunset() and self.properties.value then
    self:turnOff()
  end
end
```

Same behavior, easier to read — and `sun.lua` is ready for the next
sun-driven QA you write.

## What did we just learn?

- `--%%file:path,name` adds library files; they load **before the main
  file**, in declaration order, sharing its environment.
- One QA, several files — directives live in the main file only.
- The tools pack and unpack the whole set as one device.

Next: the finale of this tutorial — several QAs running *together*, finding
each other, and how to debug the ensemble.
