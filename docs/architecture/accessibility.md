# The Accessibility Channel

An agent has to answer two different questions about the screen, and only one of
them can be answered from pixels.

| Question | Right channel |
|---|---|
| "Is this the same *screen*?" — which dialog, which app, which layout | pixels — see [Computer & Tools](layers.md) |
| "Did the *content* change, and how?" | the accessibility tree |

Everything on screen is eventually pixels, so it is tempting to answer both with
pixels. That works for the first question and fails for the second, and the
failure is not a matter of tuning. Measured against
`screen_fingerprint`'s 256-bit hash, on 1920×1080 frames:

| Change | Fingerprint distance |
|---|---|
| A dialog opens | ~26 bits |
| A light/dark theme switch | ~40 bits |
| **One character edited** | **0 bits** |
| A clock ticking one second | 0 bits |
| Cursor moved | 0 bits |

A glyph edit and a clock tick are *indistinguishable* by any downscaled global
image hash — both are zero. Trying a different hash does not help; the limit is
the approach, not the algorithm. Meanwhile the underlying difference in those two
cases is not visual at all: it is `"Total: 100"` versus `"Total: 150"`, and
`"09:41:00"` versus `"09:41:01"`.

The accessibility tree is text. Comparing it is exact, free of sensor noise, and
needs no model call.

---

## Content, not layout

The tree already crosses the `Computer` boundary as `UIElement`, carrying a
`role`, a `name`, and a `value`:

```python
class UIElement(BaseModel):
    role: str
    name: str = ""
    value: Optional[str] = None     # <- a field's contents live here
    bounds: Optional[Rect] = None
    children: list["UIElement"] = []
```

Which field holds the content depends on the widget — a text field keeps its
contents in `value` and its label in `name`, while a label keeps its text in
`name`. `element_content` reads `value` and falls back to `name`, so a caller
asking "what does this say" does not have to know which widget it is looking at.

---

## Diffing: three passes, in this order

`ui_diff(before_tree, after_tree)` returns `added` / `removed` / `modified` /
`moved`. The interesting part is the order of the matching passes, because a
single pass gets an obvious case wrong at each extreme.

**1. Same role and same content.** This is the element itself, wherever it now
sits. Matching here *first* is what keeps a structural shift from being reported
as a rewrite: insert one row at the top of a list and every ordinal below it
renumbers, so a purely positional diff sees the entire tail as
removed-and-added. Only elements that actually carry content take part — pairing
anonymous containers on an empty string would be guesswork, not matching.

**2. Same position in the tree.** Whatever pass 1 could not claim is compared
where it stands. This is the pass that catches text edited *in place*, and it
reports it as `modified` rather than as a removal plus an addition — precisely
because the key is the structural position and not the (changed) text. Keying on
`(role, name)` would have turned every label edit into an add plus a remove.

**3. Same role, same place on screen.** What is left has both shifted and
changed. Position on screen survives a structural shift in a way a tree ordinal
does not, so pairing on it recovers a genuine edit that passes 1 and 2 miss for
opposite reasons.

A pure reordering lands in `moved`, and `content_changes` counts only
`modified + added + removed`. So a screenshot that merely re-sorts a list reports
`changed` — something did happen — while `content_changes == 0`, because no new
content appeared.

---

## Ignoring ambient churn

The pixel channel has `ignore_regions` for a clock or a taskbar. The semantic
equivalent is `ignore_roles`, and it prunes by **subtree**, not by node:

```python
ui_diff(before, after, ignore_roles="menubar")
```

Pruning is by path prefix on purpose. The thing worth ignoring is usually a
container — the status bar whose *child* is the clock — so dropping only the
matching node would leave the churn exactly where it was.

`ignore_roles` is not a way to ignore all text. `"static text"` would discard the
content you came for. It is for furniture that changes on its own.

```python
from opendesk.computer.a11y import ui_diff, find_elements

diff = ui_diff(before_tree, after_tree)      # ambient roles pruned by default
diff.changed              # True — the total changed
diff.modified[0].before   # 'Total: 100'
diff.modified[0].after    # 'Total: 150'

find_elements(after_tree, name_regex="Total", value_regex=r"^150$")
```

### It is on by default, and it has to be

The interesting question is not whether you *can* prune the clock but whether you
must. For the operations that answer **"is this the same state"** and **"did this
change"** — `content_hash` and `ui_diff` — the answer is yes, and this is
`:data:`~opendesk.computer.a11y.AMBIENT_ROLES`:

```
menubar · menu bar · statusbar · status bar · taskbar · task bar
```

These are the containers where content changes *on its own*. Without pruning them
the semantic channel is not merely unimproved, it is **worse than the pixel
channel** on a real desktop: a menu-bar clock ticks on its own cadence — every
second, if it is configured to show seconds — so a ten-step episode produces ten
distinct states, the transition graph degenerates to a straight line, and every
step reads as progress. The pixel hash, for all its blindness, at least ignores
a tick.

The entries are each *platform's* role vocabulary rather than a shared one, and
an entry no backend emits never fires. Measured on Windows, where the backend
reports Win32 class names: `statusbar` matches a window's `StatusBar` control
and `menubar` matches a real `MenuBar`, but `taskbar` matches nothing — the
shell taskbar surfaces as `Pane`. That costs little, because the taskbar is a
separate top-level window and an application capture does not contain it. (On
macOS the menu bar *is* part of the app's own tree, which is why the hazard is
real there and why this tuple exists at all.) A clock outside the captured
window is the pixel channel's problem, and `ignore_regions` is the tool for it.

Because the same default applies everywhere the digest is taken — the `ui` tool,
`screenshot`, `diagnose` — digests from different tools stay comparable. A
per-caller default would have meant the same screen hashing two ways depending on
which tool looked at it.

`ignore_roles` is matched as a case-insensitive **substring**, so `"menubar"`
catches `AXMenuBar` and `MenuBar` but *not* a dropdown `AXMenu`. That is
deliberate: an open File ▸ Save menu is interface the agent is working with, not
furniture. Pruning is also a default rather than a rule — pass
`ignore_roles=None` for the raw digest over everything.

---

## Content identity for the state graph

`content_hash(tree)` folds every role and every piece of content, in order, into
a 12-character digest. Two states hash equal exactly when they present the same
roles and the same text in the same order.

It deliberately **excludes geometry**, which is the property that makes it
usable where a perceptual fingerprint is not:

- a window nudged three pixels → same hash, not a new state
- a layout reflowed → same hash
- **one glyph edited → different hash**
- a clock ticking → **same hash** (ambient roles are pruned by default; pass
  `ignore_roles=None` to see it)

Actions carry this digest into the audit log (`AuditEntry.ui`), and
[`diagnose`](../tools/diagnose.md) groups states by it when a session has one for
every action. That is what lets the state graph, and therefore step-level process
rewards, distinguish an edited glyph from nothing at all — a distinction the
pixel path cannot make at any tolerance.

`diagnose` decides this all-or-nothing rather than per entry, because a graph
that mixed the two identities would split one screen across two states and merge
two different ones.

---

## Where it plugs in

| Consumer | Uses |
|---|---|
| [`ui_element`](../tools/reward.md) | `value_regex` / `value_equals` — assert a field's contents |
| [`ui_changed`](../tools/reward.md) | compare accessibility content instead of pixels |
| `diagnose` | `identity="ui"` — group states by content |
| [`memory`](../tools/memory.md) | `find(text=…)` reaches what a past screen *said* |
| [`screenshot`](../tools/screenshot.md) | `tree=true` records the snapshot with the frame |

The digest is refreshed whenever a tree is read, which costs nothing extra: the
[`ui`](../tools/ui.md) tool already reads the tree to resolve a target, and
`screenshot` already reads it for `marks=true`.

---

## Limits

- **Not every application exposes a tree.** Electron apps, games, and
  canvas-rendered interfaces may report one node or none. The pixel channel is
  the fallback, and it stays the right tool for the "is this the same screen"
  question regardless.
- **Reading a tree is not free.** On macOS it shells out to `System Events`, which
  can take hundreds of milliseconds on a large window. That is why `screenshot`
  reads it only on request (`tree=true`, implied by `marks=true`) rather than on
  every capture.
- **Contents are truncated.** Walks stop at a bounded node count and depth so a
  diff stays prompt-sized; a very large list may be partially compared.
- **It answers "what changed", not "was it correct".** Content assertions state
  what a checker requires — `ui_element` with a `value_regex` — rather than
  inferring intent from a diff.
