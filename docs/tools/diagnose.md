# `diagnose` — State-Transition Diagnosis

`diagnose` answers *where* a session went wrong, not just whether it did.

```
audit log ──► map screens to functional states ──► state-transition graph
                                                          │
                        bottlenecks · loops · inertia · dead ends
```

## Why it exists

The standard way to grade a computer-use agent is a single pass/fail at the end
of a hundred steps. That score tells you nothing actionable: an agent that
mis-typed a shortcut, one that mis-clicked a button, and one that wandered
through five unrelated menus all collapse to the same `0`.

State-centric analysis replaces the verdict with structure. Two ideas:

1. **Screens that look different can be the same state.** A clock ticks, a
   cursor moves, a scroll position shifts. Comparing screenshots for equality
   shatters one functional screen into dozens of near-duplicates. `diagnose`
   groups them, so the graph reflects the interface rather than its rendering
   noise.
2. **Failures are not uniform.** In published analyses of GUI failures, a small
   minority of screens accounts for the majority of errors. Localising them
   turns "improve the agent" into "fix these five screens".

### What "the same state" means

Grouping is the whole game, and there are two ways to do it:

**By accessibility content** (`identity="ui"`) — a digest of the tree's roles and
text. Two screens are the same state exactly when they present the same content.
This sees a one-character edit, and ignores a clock tick, because one is a string
that changed and the other is not. See
[The Accessibility Channel](../architecture/accessibility.md).

**By perceptual fingerprint** (`identity="screen"`) — pixel-based, needs no
accessibility tree, and groups by **layout within a tolerance**. It splits on a
dialog opening or a theme switch and *merges a typed glyph*, because a one-glyph
edit moves a downscaled global hash by zero bits. That is a limit of the
approach, not of the tolerance: no value of `tolerance` separates a glyph edit
from a clock tick.

`identity="auto"` (the default) uses content whenever *every* action in the log
carries a digest, and fingerprints otherwise. All-or-nothing rather than per
entry, because a graph that mixed the two would split one screen across two
states and merge two different ones. Whichever ran is reported as
`report.identity`, so a weaker signal is never mistaken for a stronger one.

## What it reports

| Section | Meaning |
|---|---|
| **States** | Functional screens: visits, errors, how many raw screens merged into each |
| **Bottlenecks** | States where errors concentrate, ranked |
| **Inertia** | Runs of consecutive actions that changed nothing |
| **Loops** | `state → action → state` cycles |
| **Dead ends** | States the agent acted from with no successful outgoing transition |

The headline number is **bottleneck concentration**: the share of all errors
that sit in the worst 20% of states. A high value means the problem is
localised and worth fixing; a low value means failures are diffuse and the task
itself may be the issue.

## Actions

| Action | What you get |
|---|---|
| `report` | Human-readable diagnosis (default) |
| `json` | The same analysis as structured JSON, for tooling |
| `steps` | Per-step effect table — did each action change the UI? |

`tolerance` (default `4`) controls how aggressively near-identical screens
merge. Higher merges more; `0` keeps every distinct fingerprint separate. The
default absorbs rendering jitter and small content edits, while a structural
change — a dialog opening (≈26 bits at 1920×1080), a theme switch (≈40 bits) —
still splits. It applies only to fingerprint grouping; content grouping is an
exact comparison.

## Examples

```python
from opendesk.registry import create_registry
from opendesk.tools.base import allow_all_context

tools = create_registry()
diag = tools.get("diagnose")
ctx = allow_all_context()

# Where did this session stall?
await diag.execute(ctx, diag.parse_params({"action": "report"}))

# Machine-readable, for a dashboard or an automated triage step
await diag.execute(ctx, diag.parse_params({"action": "json"}))

# Which individual actions had no effect?
await diag.execute(ctx, diag.parse_params({"action": "steps"}))
```

## How it is built

Diagnosis reuses the audit log's per-action identity field: every recorded action
is tagged with the screen it was issued against — its `ui` content digest when
one was taken, its `screen` fingerprint otherwise — so the graph is
reconstructed from ordinary session history with no extra instrumentation.
Reading the accessibility tree stamps the digest, which the
[`ui`](ui.md) tool does for free while resolving a target; a screenshot does it
when asked (`tree=true`).

Actions that never move the interface are classified rather than ignored:

- **Observation actions** (`screenshot`, `ocr`, reads, listings) are real agent
  steps and appear in a trajectory, but never form a state transition.
- **Journal actions** (the reward tool's own checks, episode markers) describe
  the recording rather than the task, and are excluded from the graph entirely.

## Notes

- Entries without an identity cannot be placed in the graph and are counted in
  the report. Taking a screenshot before acting keeps coverage complete.
- Detection is deliberately structural: nothing here needs a model, so the
  same session always diagnoses the same way.
- A content digest is only as good as the accessibility tree behind it. An
  application that exposes no tree falls back to pixels, and the report says
  which identity was used.
