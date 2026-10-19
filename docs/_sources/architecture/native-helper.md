# Native helper (`opendesk-ax`)

On macOS, opendesk reads the accessibility tree and delivers background input
through a small Swift program, `opendesk-ax`, instead of running an
AppleScript per query. This page explains what it does and how both SDKs use
it.

## Why

The AppleScript path (`osascript` + System Events `entire contents`) pays for a
new process and the AppleScript runtime on every call, then makes several
cross-process round trips per element. It is slow, has to be capped (200
elements), and sees almost nothing in Chromium/Electron apps, which only build
their accessibility tree when an assistive client asks for it.

The helper:

- **stays running** — `opendesk-ax serve` answers JSON-line requests over
  stdin/stdout, so there is no start-up cost per query;
- **batches attribute reads** — role, subrole, title, value, description,
  identifier, position, size, enabled, focused and children come back from one
  `AXUIElementCopyMultipleAttributeValues` call per element;
- **wakes Chromium/Electron** — sets `AXManualAccessibility` and
  `AXEnhancedUserInterface` on Chromium-based apps (detected by bundle id or
  an Electron/Chromium framework in the bundle) and retries for up to ~450 ms
  while the tree is built;
- **hands out stable element refs** so an agent can act on the exact element
  it saw;
- **delivers input in the background** with `CGEvent.postToPid`, without
  moving the user's cursor or activating the target app.

`get_tree`, median of 5 runs, macOS 26 on Apple silicon
(`python python/scripts/bench_ax.py --open`):

| App | AppleScript | `opendesk-ax` | Speed-up | Elements (AppleScript / helper) |
|-----|------------:|--------------:|---------:|-------------------------------:|
| Finder (Applications window) | 7,649 ms | 75 ms | ~100x | 28 / 175 |
| TextEdit (blank document) | 2,715 ms | 48 ms | ~55x | 3 / 45 |
| Google Chrome (one tab) | — | 120–190 ms | — | — / 599 |

## Build and lifecycle

The Swift source is embedded in both SDKs —
`python/opendesk/computer/macos_native.py` (`SWIFT_SOURCE`) and
`js/src/computer/macosNative.ts` (`SWIFT_SOURCE`). The two copies are
byte-identical, and a test in each SDK enforces it.

On first use the source is compiled with `swiftc -O` to
`<home>/bin/opendesk-ax-v1` (`<home>` is `$OPENDESK_HOME` or `~/.opendesk`)
and a `opendesk-ax-v1.sha256` stamp of the source is written next to it.
Compilation takes ~10–15 s once; whichever SDK runs first builds the binary
and the other reuses it. A changed source rebuilds automatically, and the
binary is written to a temp file and renamed into place, so concurrent
processes never see a partial file.

Each SDK keeps one helper process per host process:

- requests are serialised and matched to responses by id;
- every request has a timeout (10 s, 30 s for trees); a timed-out helper is
  killed and the next request starts a fresh one;
- a crashed helper is restarted on the next request;
- the helper exits when its stdin closes, so it never outlives its parent.
  The JS client unrefs the process while idle so it never keeps Node alive.

If the helper can't run — not macOS, no `swiftc` (install the Xcode Command
Line Tools), or no Accessibility permission — `available()` is false, the
`ui` tool falls back to AppleScript, and `window_text` / `windowText` return
`None` / `null`. Set `OPENDESK_NATIVE_AX=0` to disable it entirely.

The helper inherits Accessibility permission from the app that runs opendesk
(Terminal, your IDE, Claude Desktop): grant it there under
**System Settings → Privacy & Security → Accessibility**.

## Protocol

```
→ {"id": 7, "cmd": "tree", "app": "TextEdit", "max_nodes": 500}
← {"id": 7, "ok": true, "result": {"pid": 64076, "app": "TextEdit", "window_title": "Untitled",
                                   "truncated": false, "nodes": [...]}}
← {"id": 8, "ok": false, "error": "unknown ref zzzzzz; call tree again"}
```

| Command | Arguments | Result |
|---------|-----------|--------|
| `ping` | — | `{version, trusted, pid}` |
| `frontmost` | — | `{app, pid, bundle_id, window_title}` |
| `tree` | `pid` or `app` (default frontmost), `max_depth` (12), `max_nodes` (1500), `max_value` (300), `scope` (`window` \| `app`), `actions` (true) | `{pid, app, window_title, truncated, nodes}` |
| `get` | `ref`, `max_value` | one node, freshly read |
| `perform` | `ref`, `action` (default `AXPress`) | `{ref, action, pid}` |
| `set_value` | `ref`, `value` | `{ref, pid}` |
| `focus` | `ref` | `{ref, pid}` |
| `element_at` | `x`, `y` (logical screen points) | node + `pid`, `app`, `pressable` (nearest element with `AXPress`) |
| `window_text` | `pid` (default frontmost), `max_chars` (20000) | `{text, app, pid, window_title, nodes}` |
| `click_pid` | `x`, `y`, `pid` or `app` (default: owner of the window under the point), `button`, `count` | `{pid, window, ...}` |
| `key_pid` | `pid`, `app` or `ref`; `text`, or `key` / `keycode` + `modifiers` | `{pid, events}` |

Nodes are `{ref, parent, role, subrole?, title?, value?, description?,
identifier?, frame?{x,y,w,h}, enabled, focused, actions?}` in breadth-first
order, so one deep subtree can't starve the rest of the window. `max_depth`
counts meaningful levels only: unlabelled `AXGroup`, `AXScrollArea`,
`AXSplitGroup` and `AXLayoutArea` wrappers (common in web content) don't add
depth.

`opendesk-ax call '<json>'` runs a single request and prints the response,
which is handy for debugging.

## Element refs

A ref is a 6-character base-36 hash of the element's pid and its path from
the window: one `(role, index among same-role siblings, identifier-or-title)`
step per level. The window step deliberately omits the window title, which
changes as documents are edited. So:

- the same UI produces the same refs across calls and across helper restarts;
- a ref survives unrelated changes elsewhere in the window;
- renaming or moving the element (or an ancestor) changes it.

The helper keeps `ref → element` for the latest tree of each app. When a
stored element has gone stale it re-resolves the ref by walking its path
again; an unknown ref (for example after a helper restart) triggers a fresh
tree read of the known apps and the frontmost app before giving up.

On the Python wire protocol `UIElement.ref` travels inside
`metadata["ref"]`, so peers that predate the field (they reject unknown keys)
keep working in both directions.

## Background input

- `perform` / `set_value` / `focus` act through accessibility and never touch
  the cursor.
- `key_pid` posts keyboard events to one process (`CGEventPostToPid`) using a
  private event source, character by character with the Unicode string
  attached, so any text works without the clipboard. With `ref`, the element
  is focused first.
- `click_pid` posts mouse-down/up to one process with the target window's
  number attached. Apps that are inactive or on another Space may ignore it;
  the `mouse` tool therefore tries `element_at` + `AXPress` first.

`OPENDESK_BACKGROUND=1` makes the `ui` and `mouse` tools use only these paths
and refuse anything that would move the cursor.

## `window_text`

`window_text(pid=None, max_chars=20000)` (Python) /
`windowText(pid?, maxChars = 20000)` (JS) returns the visible text of the
frontmost (or given) window in accessibility reading order: titles, static
text, and text-field / text-area / heading values, deduplicated, one item per
line. Menus are skipped, tables and lists use their visible rows, and elements
outside the window frame are ignored. Screen memory uses it as a cheap,
exact alternative to OCR.

## Other platforms

- **Windows**: `LocalComputer.ui_tree` fetches the whole window subtree with
  one UI Automation `CacheRequest` (`TreeScope_Subtree`) when pywinauto's UIA
  backend is available, instead of several round trips per control, and falls
  back to the per-control walk otherwise.
- **Linux Wayland**: capture via `grim`, the xdg-desktop-portal Screenshot
  API (`gdbus`), or `gnome-screenshot`; input via `ydotool`. See
  [mouse → Wayland](../tools/mouse.md#wayland).
