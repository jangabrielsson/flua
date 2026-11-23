# The button that did nothing — how QuickApp UI events really work on the HC3

*Forum draft. A friendly explainer of the HC3's UI event system — v1 and v2, the main QA and its children — based on live-verified 5.221 behavior and flua's matching implementation.*

---

It started as a mystery. A QuickApp with a child device — a small sensor with its own little UI: a button, a slider, a tabbed panel. In flua's web viewer everything worked. On the real HC3 the slider worked, the select worked, but the button did *absolutely nothing*. No log line, no error, no warning. Just silence.

Two evenings later, the button's secret was out, and the whole UI event system of the HC3 finally made sense. This post is the version I wish I'd read at the start.

## The two UI formats, in ten seconds

The HC3 has two ways to describe a QuickApp's interface:

- **The old one (v1)** — the "layout". A tree of rows with buttons and sliders. Solid, everywhere, but nothing fancy.
- **The new one (v2)** — the "uiView". Same elements, plus the modern stuff: `tabView` (tabbed panels) and `collapsible` (expandable sections).

You choose with `--%%useUiView:true`. Tabs and collapsibles *only exist in v2* — declare them without it and the app shows you a blank view. (flua's `--check` now warns you about exactly that.)

## The two roads a button press can take

This is the part that clears everything up. When someone taps a control, the app sends the controller *one of two things*:

**Road 1 — the action.** The view says: "when pressed, call the method `turnOn`." The controller calls `turnOn`. Direct, simple, no middleman.

**Road 2 — the event.** The view says: "the element named `onBtn` got the event `onReleased`." The controller takes that and looks it up in a phone book — the QA's `uiCallbacks` table — finds `turnOn`, and calls it, this time handing over an event table (`event.values[1]` is the value).

Both roads end at a method. The difference is *who knows which method*.

## Who owns the phone book

The phone book (`uiCallbacks`) belongs to the **main QuickApp** — it's built from your `--%%u:` declarations and registered at startup.

**Children have no phone book.** Their views don't say "element X was pressed"; they say "call this method" — the action name *is* the method name, and the method lives on the child's own class (the one you pass to `createChildDevice` as the second argument):

```lua
Child = {}
class "Child"(QuickAppChild)
function Child:__init(dev) QuickAppChild.__init(self, dev) end
function Child:turnOn() print(self.name, "pressed") end   -- ← this runs

function QuickApp:onInit()
  self:createChildDevice({
    name = "Tabs child", type = "com.fibaro.floodSensor",
    initialProperties = { uiView = uiView },   -- bindings name turnOn directly
  }, Child)
end
```

So: main QA → phone book. Child → the view names the method. One uiView format, two delivery styles.

## The four gotchas (all caught in the wild)

**1. Tabs and collapsibles are v2-only.** A tabbed QA must declare `--%%useUiView:true`, or the app's old renderer shows nothing at all. (flua's web viewer renders them either way — the rule is about the app.)

**2. Never edit a v2 QA in the HC3's UI editor.** The editor doesn't know `tabView`/`collapsible` — it can't edit them, and an edit there can rewrite the view and drop them. Keep tabbed QAs flua-authored and update them with `--tool updateQA`/`uploadQA`. Child devices are the happy exception: the editor never touches their views, so tabs on children are completely safe.

**3. The silent button — `{}` vs `[]`.** This was the actual bug. An argless child-button binding carried `args = {}` — an empty Lua table. When the controller JSON-encodes that, `{}` becomes an *object*, and the app — expecting an *array* — silently drops the action. No log, no error. Just the silence from the opening. The fix is one idiom:

```lua
-- argless binding: mark the empty array, or the app drops the action
eventBinding = { onReleased = {{ type="deviceAction",
  params = { actionName = "turnOn", args = json.array() } }} }
```

**4. One view, one owner.** A child's uiView names the child's methods — per child, so two children can both have a "Turn On" button calling their own `turnOn`. Don't reuse a binding that targets a method that doesn't exist on that child's class: the action simply won't resolve.

## Where flua fits

flua's viewer plays the exact same game as the app: non-`UIAction` bindings fire as device actions, `UIAction` bindings go through the phone book, and the simulated `onAction`/`onUIEvent` route identically — so the QA you debug in the viewer behaves the same once uploaded (all of the above is live-verified on 5.221). And when you want a child with a tabbed UI, `flua --tool ui --as-lua` prints the compiled view as a paste-ready Lua table for `createChildDevice` — same format, with the bindings naming your methods directly, the way a child's view needs them.

`examples/ui-3-children.lua` is the complete pattern: a tabbed child with button, slider, switch and select, working identically offline and on the controller.

## TL;DR

- v1 = old layout, no event fields — everything resolves through the main QA's `uiCallbacks`.
- v2 = uiView. Main QA: `UIAction` bindings → phone book. Child: `actionName` = the method on the child's class.
- Tabs/collapsibles: v2 only, `useUiView:true`, never edit them in the HC3 editor.
- Argless child bindings need `json.array()` — the plain `{}` button press dies silently.
- flua's viewer and sim mirror both roads — develop offline, upload with confidence.
