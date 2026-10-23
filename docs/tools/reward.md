# `reward` — Verifiable Rewards & Goal States

`reward` declares what "done" means for a task as machine-checkable predicates,
scores a run against them, and closes the run as an exportable episode.

```
reward(begin) ──► … do the work … ──► reward(check) ──► reward(end)
                                            │                 │
                                     {reward, evidence}   episode + process rewards
```

## Why it exists

Training an agent with reinforcement learning needs a reward signal. The
bottleneck is well documented: environments must supply **verifiable rewards**,
and hand-written evaluators are either unscalable or unreliable.

A computer-use harness is unusually well placed here — it already has a shell,
a filesystem, an accessibility tree, and screenshots. Those are exactly the
raw materials a verifiable reward is built from. `reward` turns them into a
declarative scoring surface.

Nothing in `reward` calls a model. Every verdict is backed by observed state,
so the same task scored twice gives the same answer and a reviewer can inspect
the evidence.

## Reward specs

A spec is plain data:

```python
{
    "task": "Write a 3-line report to ~/report.txt",
    "mode": "all",                      # "all" | "any" | "weighted"
    "checks": [
        {"kind": "file_exists", "path": "~/report.txt"},
        {"kind": "file_contains", "path": "~/report.txt", "regex": "^total:"},
        {"kind": "shell", "command": "wc -l < ~/report.txt", "stdout_regex": "^3$"},
        {"kind": "screen_matches", "goal": "done", "category": "ui", "weight": 0.5},
    ]
}
```

Each check takes `required` (default `true`), `weight` (default `1`),
`category` (for a coarse-to-fine breakdown) and `label`.

### Reward semantics

| Field | Meaning |
|---|---|
| `reward` | **Binary** — `1.0` when every required check passes. This is the signal an RLVR loop optimises. |
| `score` | **Dense** — weighted fraction of required checks passed. |

`mode` decides how the two relate:

- `all` (default) — binary reward; `score` is still reported as a dense signal
- `any` — reward when at least one required check passes
- `weighted` — reward *is* the dense score

Optional checks (`required: false`) are evaluated and reported but never affect
the reward. Use them for diagnostics.

## Check kinds

| Kind | Arguments |
|---|---|
| `file_exists` | `path` |
| `file_absent` | `path` |
| `file_contains` | `path`, `text` *or* `regex` |
| `shell` | `command`, `expect_exit?`, `stdout_regex?`, `stderr_regex?`, `timeout?` |
| `clipboard_contains` | `text` |
| `clipboard_equals` | `text` |
| `app_running` | `name` |
| `ui_element` | `role?`, `name_regex?`, `value_regex?`, `value_equals?`, `content_regex?`, `present?` |
| `ui_changed` | `ref?`, `ignore_roles?` |
| `screen_matches` | `goal`, `min_similarity?` |
| `screen_changed` | `ref?`, `ignore_regions?` |

Shell output is normalised to LF before regex matching, so `^…$` anchors behave
the same on Windows and POSIX.

### Asserting what the screen *says*

`ui_element` is the difference between a visual check and a **verifiable** one.
"The screen changed" is not a statement about the task; "the Total field reads
300" is:

```json
{"kind": "ui_element", "role": "textfield", "value_regex": "^300$"}
{"kind": "ui_element", "name_regex": "^Total$", "value_equals": "300"}
{"kind": "ui_element", "content_regex": "Total: 3\\d\\d"}
```

Criteria combine with **AND**. `value_regex` and `value_equals` read a widget's
contents (`value`, falling back to `name`), and a failure reports what was looked
for, so a spec that stops matching is diagnosable rather than merely red.

`ui_changed` is the semantic counterpart of `screen_changed`. It compares
accessibility content rather than pixels, so it sees a one-character edit —
which no pixel threshold can — and ignores a ticking clock:

```json
{"kind": "ui_changed", "ref": "previous"}
{"kind": "ui_changed", "ref": "previous", "ignore_roles": []}
```

Ambient furniture — menu bars and status bars — is pruned **by default**,
because a `ui_changed` that fired on a clock tick would be a verifiable predicate
reporting a change that never happened. Pruning is by subtree, so ignoring a
status bar also drops the clock inside it. The names are each *platform's* role
vocabulary: on Windows the backend reports Win32 class names, so `statusbar` and
`menubar` match but a shell taskbar (which surfaces as `Pane`) does not — that
one is a separate top-level window an application capture does not contain, and
`ignore_regions` is the tool for it. Pass `ignore_roles: []` for the raw
comparison, or your own list to prune something else. The verdict's evidence
records which roles were ignored, so a default that swallowed a real edit is
visible rather than silent.

Its reference comes from the observation memory, so capture with `tree=true` (see
[screenshot](../tools/screenshot.md)) to populate it; when no snapshot was
recorded the check says so rather than passing or failing on a guess.

### Ignoring ambient churn

A ticking clock, a taskbar, or a notification badge is **genuine** pixel change,
so no threshold can separate it from a real edit — the two differ in *meaning*,
not in magnitude. `screen_changed` therefore accepts `ignore_regions`, a list of
`[x, y, w, h]` boxes excluded from the comparison:

```json
{"kind": "screen_changed", "ref": "previous",
 "ignore_regions": [[1790, 0, 130, 40]]}
```

Do not hardcode those coordinates. Ask the accessibility tree where the churn
lives, which survives theme and resolution changes:

```python
from opendesk.computer.capture import regions_for_roles

regions = regions_for_roles(ui_tree, ["menu bar", "static text"])
```

The reported `suppressed_pixels` and `ignored_regions` show what was excluded, so
an exclusion that quietly swallows a real edit is visible in the evidence rather
than silent.

For content rather than pixels, `ui_changed` is the better tool: it needs no
coordinates at all, and ignores the clock by role. Reach for `ignore_regions` when
a region is doing something a semantic diff cannot express — a progress bar
animating inside a panel whose labels are unchanged.

## Goal states

Sometimes success is easier to state as "end up looking like *this*". A goal
state records a reference screenshot **plus the labelled elements it contained**,
then scores a later state against both:

- **visual similarity** — pixel overlap averaged with perceptual-fingerprint
  agreement. Catches "the layout is still the old one". Both parts are coarse:
  a one-glyph edit reads as ~100% similar, so this half confirms *structure*,
  not content.
- **anchor recall** — the share of the reference's labelled elements
  (role + accessible name) present now. Catches "the pixels match because both
  screens are mostly empty", and is the half that carries content identity.

Neither is trusted alone. The combined score is capped by visual similarity, so
a screen full of the right labels in the wrong layout cannot pass.

Anchor recall compares *which elements are present*, not what they say. To assert
a field's value, use `ui_element` with a `value_regex` — see
[Asserting what the screen says](#asserting-what-the-screen-says) above.

## Agent assertions

A reward spec is authored *for* the task, before anyone runs it. An **assertion**
is authored *by the agent*, mid-episode, about what it thinks is true *now*:

```python
reward(action="assert", name="invoice downloaded",
       claim="the export finished and the PDF is on disk",
       checks=[{"kind": "file_exists", "path": "~/invoice.pdf"}])
```

It uses the same check vocabulary as a spec, and is verified **immediately** —
the verdict comes back in the same call, so a belief that does not hold is
something the agent can act on rather than a post-mortem surprise.

Three things this buys:

| What | Why |
|---|---|
| **Milestone track** | The claim is bound to the step it followed, so a trajectory reads "at step 12 the agent believed X, and X held". Far better credit assignment than a per-step pixel diff, which cannot tell a meaningful action from a clock tick. |
| **Calibration** | `assertions` reports **precision** — of the claims made, how many held. An agent that says "done" when it is not is a specific, measurable failure mode. |
| **Regressions** | A claim is re-checked when the episode closes. Held when made, false at the end means the agent declared success and later broke it — a failure neither the terminal reward (too coarse) nor the step effects (too local) can see. |

```
assert(name, checks, claim?)          at the moment of belief
        │
        ├── held?     precision  ◄──── was the claim true when made
        └── still held at end?  ◄──── stability / regressions
```

### An assertion is not a reward

Stated plainly, because it is the difference between a useful tool and a
reward-hacking surface: **assertions never contribute to the reward.** The agent
chooses its own checks, so an agent optimising reward would simply assert
something it can trivially satisfy and collect. Reward comes only from the task's
own spec, whose checks the agent does not author.

An assertion is a *report of belief* — for a verifier, a trainer, or a human
reading the trajectory — and it is judged as one. It is still worth recording:
`precision` measures the agent's self-knowledge, which is trainable independently
of its task score.

## Actions

| Action | Arguments | What it does |
|---|---|---|
| `begin` | `task`, `spec?`, `goal?`, `meta?` | Start an episode |
| `check` | `spec?`, `episode_id?` | Evaluate the spec now, without closing |
| `assert` | `name`, `checks`, `claim?` | Declare what you believe is true now, and check it |
| `assertions` | — | Calibration report: how many of your claims held |
| `end` | `episode_id?`, `gamma?` | Score, attach process rewards, re-check claims, close |
| `goal_capture` | `goal` | Record the current screen as a goal state |
| `goal_score` | `goal`, `min_similarity?` | Score the current screen against one |
| `goal_list` | — | List recorded goal states |
| `episodes` | — | List episodes in this session |

## Examples

```python
from opendesk.registry import create_registry
from opendesk.tools.base import allow_all_context

tools = create_registry()
reward = tools.get("reward")
ctx = allow_all_context()

# Record a reference end state
await reward.execute(ctx, reward.parse_params(
    {"action": "goal_capture", "goal": "done"}
))

# Declare the task
await reward.execute(ctx, reward.parse_params({
    "action": "begin",
    "task": "Export the invoice to ~/invoice.pdf",
    "goal": "done",
    "spec": {
        "task": "Export the invoice",
        "checks": [
            {"kind": "file_exists", "path": "~/invoice.pdf"},
            {"kind": "screen_matches", "goal": "done", "category": "ui"},
        ],
    },
}))

# … do the work …

# Say what you believe, mid-flight — the verdict comes straight back
claim = await reward.execute(ctx, reward.parse_params({
    "action": "assert",
    "name": "invoice downloaded",
    "claim": "the export finished and the PDF is on disk",
    "checks": [{"kind": "file_exists", "path": "~/invoice.pdf"}],
}))
print(claim.output)           # HOLDS: invoice downloaded

report = await reward.execute(ctx, reward.parse_params({"action": "check"}))
print(report.output)          # [PASS] Export the invoice …

episode = await reward.execute(ctx, reward.parse_params({"action": "end"}))
print(episode.metadata["reward"])              # 1.0
print(episode.metadata["process_metrics"])     # steps, efficiency, errors …
print(episode.metadata["assertions"]["metrics"]["precision"])   # 1.0
```

## Notes

- `check` is idempotent and cheap — call it as often as useful to see how close
  a run is, rather than only at the end.
- `assert` is the agent's own instrument, not the task's: use it to *find out*
  whether a belief is true, and to leave a readable trace of what the agent
  thought. It cannot score the task.
- A claim with no `checks` is refused. A belief nothing can falsify is not an
  assertion, and recording one would pad the milestone track with noise.
- `end` attaches **step-level process rewards** to the episode and re-checks the
  episode's assertions. Use [`diagnose`](diagnose.md) to see where the steps that
  did not move the interface clustered.
- Episodes record the audit-log position at `begin` and `end`, so a trajectory
  covers exactly the work done for the task.
