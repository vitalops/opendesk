# The Learning Layer

opendesk runs the computer. It does not train a model. The learning layer is
what it can honestly contribute to reinforcement learning anyway: the
**environment and reward** half.

```
        ┌──────────────── opendesk ────────────────┐
        │  observe  →   act   →  score   →  diagnose│
        │  screenshot   ui        reward     diagnose│
        │  memory       keyboard  assert             │
        └────────────────────┬─────────────────────┘
                             │  reward-labelled episodes
                             ▼
                  your training loop (gradients happen there)
```

## The split

Recent work on GUI agents does two very different things, and it is worth being
precise about which is which.

**Policy side — needs model weights and GPUs.** Group-relative methods that
compare several responses sampled from one screen, token-level on-policy
self-distillation, spatial credit assignment for click coordinates, test-time
gradient updates. These change a policy. A tool server cannot do them, and
pretending otherwise would produce a stub that trains nothing.

**Environment side — needs a machine that can be observed.** An RL loop needs
environments that *provide verifiable rewards, support long-horizon
interaction, and scale cheaply*. Published work is explicit that this is the
bottleneck, and that hand-written evaluators are either unscalable or
unreliable.

The second half is what a computer-use harness is. opendesk already had the
primitives — shell, filesystem, accessibility tree, screenshots — but nothing
surfaced them as a reward. The learning layer does.

## The three interfaces

### 1. Verifiable rewards (`reward`)

Declare success as machine-checkable predicates over observable state. Every
verdict carries its evidence, so a reward can be re-checked and audited.

`reward` reports a **binary** reward (did every required check pass) and a
**dense** score (what fraction did), because an RL loop wants the first and
debugging wants the second.

See [`reward`](../tools/reward.md).

### 2. Process signals (`diagnose`, `process`)

An outcome reward says *whether* a run succeeded, not *which* of its hundred
actions mattered. opendesk maps screens to functional states, builds a
state-transition graph, and derives a per-step reward plus a discounted return
from three observable facts: did the action change the interface, did it error,
and was it a repeat of a stalled pattern.

Effects come from one of three sources, in order of how much each can be
trusted, and the chosen one is reported as `signal_source` so a downgrade is
visible rather than silent:

1. **Accessibility content** — when the session recorded a tree digest per action
   (see [The Accessibility Channel](accessibility.md)), successive digests that
   differ mean the *content* moved. This sees a single edited glyph and ignores a
   ticking clock.
2. **Screen fingerprints** — a session that took screenshots but read no tree
   falls back to this. It groups states by layout, so a content edit inside an
   unchanged layout reads as no effect.
3. **The actions themselves** — a session with neither (a CLI-only task, or a
   host without capture) has no graph at all, so effects are inferred: a
   non-passive action is presumed to move the world, and a verbatim repeat of the
   previous *successful* mutation is the one clear case where it did not.
   Retrying a failure counts as a repair, not a repeat.

Reported efficiency is progress over the steps whose effect could be judged, so
the terminal step — which has no successor to compare against — does not deflate
it.

The same graph answers a different question — *where* did this go wrong —
through bottlenecks, loops, inertia and dead ends.

See [`diagnose`](../tools/diagnose.md).

### 3. Agent-declared assertions (`assert`)

The interfaces above are authored *about* the task. An assertion is authored *by*
the agent, mid-episode, about what it believes is true right now:

```python
reward(action="assert", name="invoice downloaded",
       checks=[{"kind": "file_exists", "path": "~/invoice.pdf"}])
```

It is verified immediately, bound to the step it followed, and re-checked when
the episode closes. That produces three signals an outcome reward cannot:

- **A milestone track** for credit assignment — "at step 12 the agent believed X,
  and X held" — instead of a per-step pixel diff that cannot tell a meaningful
  action from a clock tick.
- **Calibration**: of the claims made, how many held. An agent that says "done"
  when it is not is a specific, measurable failure mode, and `precision` is that
  measurement.
- **Regressions**: a claim that held when made and no longer holds at the end.
  The agent declared success and later broke it — invisible to the terminal
  reward (too coarse) and to the step effects (too local).

An assertion **never contributes to the reward**. The agent chooses its own
checks, so an agent optimising reward would assert something trivially
satisfiable and collect; the checks would grade the agent's question rather than
its answer. Reward comes only from the task spec, whose checks the agent does not
author. Assertions are a report of belief, judged as one — see
[`reward`](../tools/reward.md#agent-assertions).

## Goal-state anchoring

Some tasks are easier to describe as "end up looking like this". A goal state
records a reference screenshot plus the labelled elements it contained, and
scores a later state on two independent axes: visual similarity and anchor
recall. Neither is trusted alone, because each is fooled by a different failure
mode — see [`reward`](../tools/reward.md#goal-states).

## What the layer will not do

- **No gradients.** No loss function, no optimiser, no weight updates.
- **No policy.** opendesk does not decide what to click.
- **No model in the reward path.** Every check reads files, shell output, the
  accessibility tree or pixels. A reward that consults a model is a reward you
  cannot audit.

## Module map

| Module | Role |
|---|---|
| `opendesk.learning.rewards` | Check kinds, spec parsing, evaluation |
| `opendesk.learning.goal_state` | Goal capture, anchor extraction, scoring |
| `opendesk.learning.process` | Step rewards, discounted returns |
| `opendesk.learning.trajectories` | Episode lifecycle |
| `opendesk.learning.assertions` | Agent-declared claims, calibration, regressions |
| `opendesk.computer.diagnostics` | State-transition graph |
| `opendesk.computer.observations` | Lossless visual memory |

## A complete loop

```python
from opendesk.registry import create_registry
from opendesk.tools.base import allow_all_context

tools = create_registry()
ctx = allow_all_context()
reward, diagnose = tools.get("reward"), tools.get("diagnose")

await reward.execute(ctx, reward.parse_params(
    {"action": "goal_capture", "goal": "done"}
))

await reward.execute(ctx, reward.parse_params({
    "action": "begin", "task": "Export the invoice", "goal": "done",
    "spec": {"task": "Export the invoice", "checks": [
        {"kind": "file_exists", "path": "~/invoice.pdf"},
    ]},
}))
# … the agent works here …
outcome = await reward.execute(ctx, reward.parse_params({"action": "end"}))
where = await diagnose.execute(ctx, diagnose.parse_params({}))
```

The episode closes with an outcome reward, step rewards, a discounted return and
a diagnosed state graph — produced without a single model call in the
measurement path.
