# `ui` — Accessibility-based UI Interaction

The primary interaction tool. Clicks, types, and reads values using the platform's native accessibility API. No pixel coordinates needed.

```python
from opendesk.tools.ui import UITool
tool = UITool()
```

## Actions

| Action | Required params | Description |
|--------|----------------|-------------|
| `get_tree` | `app` | List the accessible elements in the app's window, each with its `[ref]` |
| `click` | `app`, `ref` or `title`/`role` | Press a button or element |
| `click_menu` | `app`, `menu`, `menu_item` | Click a menu bar item: `File → Save` |
| `type` | `app`, `text` (optional `ref`) | Type text into the focused element, or into `ref` (Unicode-safe). `verify=true` reports whether the content changed |
| `press_key` | `app`, `key` (optional `ref`) | Press a key or chord. `verify=true` as above |
| `get_value` | `app`, `ref` or `title`/`role` | Read the current text value of an element |

## Element refs

On macOS, `get_tree` labels every element with a short, stable **ref**:

```
Window: Untitled  [81dcaj]
  [wcsc7p] [AXTextArea] (unnamed)
  [ivp2vr] [AXCheckBox] bold = "0"
  [govglg] [AXPopUpButton] typeface = "Helvetica"
  [kl2lnd] [AXComboBox] font size = "12"
```

Pass `ref` to act on exactly that element — no name matching, no ambiguity
between two "OK" buttons, no pixel guessing:

```python
await tool.execute(ctx, params(action="click", app="TextEdit", ref="ivp2vr"))
await tool.execute(ctx, params(action="type", app="TextEdit", ref="wcsc7p", text="Hello"))
await tool.execute(ctx, params(action="get_value", app="TextEdit", ref="kl2lnd"))
```

Refs are derived from the element's position in the tree (role, index among
siblings of the same role, and identifier or title), so **the same UI gives
the same refs across calls**. They change when the UI around the element
changes; if a ref is rejected, run `get_tree` again.

Unlabelled layout containers (`AXGroup`, `AXScrollArea`, ...) are hidden from
the outline so the agent sees what it can act on.

## Background mode

Set `OPENDESK_BACKGROUND=1` to let an agent work without touching the user's
cursor or keyboard focus:

- `click` presses the element through accessibility (`AXPress`); elements
  with no press action get a click posted straight to the app's process.
- `type` and `press_key` post keystrokes directly to the app (to `ref` if
  given) — the app is not activated and the clipboard is not used.
- The `mouse` tool refuses actions that would move the cursor and points the
  agent back to `ui` with a ref.

Background mode needs the native macOS helper (below).

## Speed

On macOS the tool talks to a persistent native helper, `opendesk-ax`, instead
of spawning `osascript` per query. It reads each element's attributes in one
batched call and turns on Chromium/Electron accessibility, so trees from VS
Code, Slack, Chrome and other Electron apps are no longer empty.

`get_tree`, median of 5 runs on macOS 26 (Apple silicon):

| App | AppleScript | `opendesk-ax` | Elements (AppleScript / helper) |
|-----|------------:|--------------:|-------------------------------:|
| Finder (Applications window) | 7,649 ms | 75 ms | 28 / 175 |
| TextEdit (blank document) | 2,715 ms | 48 ms | 3 / 45 |

Reproduce with `python python/scripts/bench_ax.py --open`. See
[Native helper](../architecture/native-helper.md) for how it works.

## Ask Claude

> "Click the Save button in TextEdit"

> "Open the File menu in Safari and click New Window"

> "Type 'hello' into the search box in Finder"

> "What buttons are visible in this app?"

> "What's the current value of the address bar in Safari?"

This is the most reliable way to interact with apps — Claude uses the accessibility tree so it doesn't need to guess pixel coordinates.

---

## SDK examples

```python
params = UITool.Params

# List what's in the window (each line starts with the element's ref)
await tool.execute(ctx, params(action="get_tree", app="TextEdit"))

# Click a button by label, or by ref from get_tree
await tool.execute(ctx, params(action="click", app="TextEdit", title="Save"))
await tool.execute(ctx, params(action="click", app="TextEdit", ref="ivp2vr"))

# Open File menu → New
await tool.execute(ctx, params(action="click_menu", app="TextEdit", menu="File", menu_item="New"))

# Type text (clipboard-paste, full Unicode); with ref, the element is focused first
await tool.execute(ctx, params(action="type", app="TextEdit", text="Hello, 世界 🌍"))

# Press Cmd+S to save
await tool.execute(ctx, params(action="press_key", app="TextEdit", key="s", modifiers=["command"]))

# Read a text field value
await tool.execute(ctx, params(action="get_value", app="Safari", title="Address and Search Bar"))
```

## Platform notes

- **macOS**: the native `opendesk-ax` helper (compiled once with `swiftc`, needs
  Accessibility permission), falling back to AppleScript / System Events when
  it is unavailable. App name must match Activity Monitor (e.g. `"Google Chrome"` not `"chrome"`).
  Set `OPENDESK_NATIVE_AX=0` to force the AppleScript path.
- **Linux**: uses AT-SPI2 (`pyatspi`) with `xdotool` fallback for type/press_key.
  On Wayland, typing and key presses go through `ydotool` (see the [mouse docs](mouse.md#wayland)).
- **Windows**: uses UI Automation; the tree is fetched with one batched UIA
  `CacheRequest` when available, with Win32 fallback. App name matches window title or process name.

When an app uses custom rendering (canvas apps, games), `get_tree` may return an empty tree — fall back to `screenshot(marks=True)` and the `mouse` tool.

---

Next: [screenshot →](screenshot.md)
