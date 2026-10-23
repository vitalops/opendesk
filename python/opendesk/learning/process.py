"""Step-level process rewards.

An outcome reward alone tells a training loop *whether* a run succeeded, not
*which* of its hundred actions mattered.  This module turns the recorded action
stream into a per-step reward and a discounted return, which is the form an
RL loop actually consumes.

The signal is rule-based on purpose: it is derived only from what was observed
— whether each action changed the interface, errored, or repeated a stalled
pattern.  No model, no judgement call, reproducible.

Shaping
-------
Each step starts from a small negative ``step_cost`` (acting is not free, so an
efficient trajectory scores higher than a wandering one), then:

===============  ==============================================
state changed    ``+progress_reward``  — the action did something
no visible       ``-no_effect_penalty`` — the action was wasted
error            ``-error_penalty``
repeated loop    ``-loop_penalty`` — the same transition taken again
terminal bonus   ``+success_bonus * outcome_reward`` on the last step
===============  ==============================================

Returns are discounted with ``gamma``, so ``returns[0]`` is the value of the
whole trajectory from the start and ``returns[-1]`` is dominated by the outcome.

Where "changed" comes from
--------------------------
Three sources, in order of how much they can be trusted:

1. **Accessibility content** — when the session recorded a content digest per
   action (see :mod:`opendesk.computer.a11y`), consecutive digests that differ
   mean the *content* moved.  This sees a single edited glyph and ignores a
   ticking clock, which is exactly the distinction pixels cannot make.
2. **Screen fingerprints** — a session that took screenshots but read no tree
   falls back to this.  It groups states by layout, so a content edit inside an
   unchanged layout reads as no effect.
3. **The actions themselves** — a session with neither (a CLI-only task, or a
   host without capture) would otherwise produce no steps and no signal at all,
   so effects are inferred from the actions (see
   :func:`opendesk.computer.diagnostics.non_visual_step_signals`).

Which one ran is reported as ``report.signal_source``, so a silent downgrade to
a weaker signal is visible rather than indistinguishable from a real result.

Example::

    from opendesk.learning.process import score_process

    report = score_process(sandbox.export_audit_log(), outcome_reward=1.0)
    report.returns        # discounted return per step
    report.efficiency     # progress made / steps that could be judged
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from opendesk.computer.diagnostics import (
    DEFAULT_TOLERANCE,
    PASSIVE_ACTIONS,
    diagnose,
    non_visual_step_signals,
)

#: Default shaping weights.
DEFAULTS = {
    "step_cost": -0.1,
    "progress_reward": 1.0,
    "no_effect_penalty": -0.5,
    "error_penalty": -1.0,
    "loop_penalty": -0.5,
    "success_bonus": 10.0,
}


@dataclass
class StepReward:
    step: int
    state: str
    action: str
    effect: str
    error: bool
    no_effect: bool
    in_loop: bool
    reward: float
    reason: str = ""
    #: Position of this action in the source audit log — lets a trajectory
    #: attach the reward to the exact step it came from.
    index: Optional[int] = None
    #: The functional state the interface moved to after this action.
    next_state: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "index": self.index,
            "state": self.state,
            "next_state": self.next_state,
            "action": self.action,
            "effect": self.effect,
            "error": self.error,
            "no_effect": self.no_effect,
            "in_loop": self.in_loop,
            "reward": round(self.reward, 4),
            "reason": self.reason,
        }


@dataclass
class ProcessReport:
    steps: list[StepReward] = field(default_factory=list)
    returns: list[float] = field(default_factory=list)
    outcome_reward: float = 0.0
    gamma: float = 0.95
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULTS))
    #: Recorded calls that were not agent actions (screenshots, reward checks,
    #: bookkeeping) and were excluded from the reward.
    passive_skipped: int = 0
    #: What the step effects were read from: ``"ui"`` (accessibility content),
    #: ``"screen"`` (perceptual fingerprints), or ``"action"`` (the non-visual
    #: fallback, which infers effect from the action rather than observing it).
    #: Worth surfacing: the three differ in how much they can be trusted, and a
    #: silent downgrade used to be indistinguishable from a real result.
    signal_source: str = "screen"

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def effective_steps(self) -> int:
        return sum(1 for s in self.steps if s.effect == "changed")

    @property
    def observable_steps(self) -> int:
        """Steps whose effect could actually be judged.

        The last step of a trajectory has no successor to compare against, so
        both the screen graph and the non-visual fallback report its effect as
        ``"none"`` — unknown.  It can never count as progress, so leaving it in
        the denominator deflates every ratio by exactly one step.
        """
        return sum(1 for s in self.steps if s.effect != "none")

    @property
    def no_effect_steps(self) -> int:
        return sum(1 for s in self.steps if s.no_effect)

    @property
    def error_steps(self) -> int:
        return sum(1 for s in self.steps if s.error)

    @property
    def loop_steps(self) -> int:
        return sum(1 for s in self.steps if s.in_loop)

    @property
    def efficiency(self) -> float:
        """Share of *judgeable* steps that moved the interface.

        The terminal step is excluded from both sides of the ratio rather than
        counted as a failure to progress.  Counting it made the metric invert:
        a one-step episode always read 0%, and a two-step one could never beat
        50%, so the most direct attempt scored worse than a wandering one.  When
        nothing is judgeable — a single-step episode — there is no observed
        wasted effort, so the ratio is 1.0.
        """
        if not self.steps:
            return 0.0
        observable = self.observable_steps
        if observable == 0:
            return 1.0
        return self.effective_steps / observable

    @property
    def total_reward(self) -> float:
        return sum(s.reward for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome_reward": round(self.outcome_reward, 4),
            "gamma": self.gamma,
            "total_reward": round(self.total_reward, 4),
            "return_0": round(self.returns[0], 4) if self.returns else 0.0,
            "metrics": {
                "total_steps": self.total_steps,
                "effective_steps": self.effective_steps,
                "observable_steps": self.observable_steps,
                "no_effect_steps": self.no_effect_steps,
                "error_steps": self.error_steps,
                "loop_steps": self.loop_steps,
                "efficiency": round(self.efficiency, 4),
                "passive_skipped": self.passive_skipped,
                "signal_source": self.signal_source,
            },
            "steps": [s.to_dict() for s in self.steps],
            "returns": [round(r, 4) for r in self.returns],
        }

    def summary_text(self, max_items: int = 12) -> str:
        lines = [
            "Process rewards",
            f"  {self.total_steps} step(s)  |  reward total {self.total_reward:+.2f}  "
            f"|  return {self.returns[0]:+.2f}" if self.returns else "",
            f"  effective {self.effective_steps}  no-effect {self.no_effect_steps}  "
            f"errors {self.error_steps}  loop {self.loop_steps}  "
            f"efficiency {self.efficiency:.0%}",
            "",
        ]
        lines = [ln for ln in lines if ln != ""]
        for s in self.steps[:max_items]:
            mark = {"changed": "→", "same": "=", "none": "·"}[s.effect]
            lines.append(
                f"  [{s.step:>3}] {s.state:<4} {mark} {s.action:<22} "
                f"{s.reward:+.2f}  {s.reason}"
            )
        if self.total_steps > max_items:
            lines.append(f"  … {self.total_steps - max_items} more step(s)")
        return "\n".join(lines)


def score_process(
    entries: Iterable[Any],
    *,
    outcome_reward: float = 0.0,
    tolerance: int = DEFAULT_TOLERANCE,
    gamma: float = 0.95,
    weights: Optional[dict[str, float]] = None,
    index_offset: int = 0,
) -> ProcessReport:
    """Build per-step rewards and discounted returns from recorded actions.

    Parameters
    ----------
    entries:
        Audit entries in chronological order.
    outcome_reward:
        The trajectory-level reward (see :mod:`opendesk.learning.rewards`).
        Applied as a terminal bonus so earlier steps inherit it through the
        discounted return.
    tolerance:
        State-merging tolerance passed through to the state graph.
    gamma:
        Discount factor for the returns.
    weights:
        Override any of :data:`DEFAULTS`.
    index_offset:
        Added to each reported ``StepReward.index``.  Pass the position of
        ``entries[0]`` within the full audit log when scoring a slice, so the
        indices stay absolute and a trajectory can match rewards to steps.
    """
    w = dict(DEFAULTS)
    if weights:
        w.update({k: float(v) for k, v in weights.items()})

    # Materialise first: `entries` may be a one-shot iterable and it is walked
    # more than once.
    entries = list(entries)
    graph = diagnose(entries, tolerance=tolerance, index_offset=index_offset)
    signals = graph.steps
    source = graph.identity
    if not signals:
        # No usable identity anywhere in the stream — a CLI-only session, or a
        # host without capture.  Without this fallback every step would be
        # skipped and the whole dense signal would be empty, which is precisely
        # the case the hybrid `system` tool is meant to encourage.
        signals = non_visual_step_signals(entries, index_offset=index_offset)
        source = "action"

    # Only actions the agent took that could move the interface get a reward.
    # Bookkeeping calls (the reward tool's own checks, screenshots, reads) are
    # not actions to be credited or penalised, so they are excluded rather than
    # counted as wasted steps.
    active = [s for s in signals if s["action"] not in PASSIVE_ACTIONS]
    passive_skipped = len(signals) - len(active)

    # Which transitions recur — those are the loop steps.  The key includes the
    # destination state, not just (state, action): an action that finally moves
    # the interface is progress, even when the same action was tried on that
    # state before and did nothing.  Keying on (state, action) alone penalised
    # the very step that broke a stall.
    def transition_key(s: dict[str, Any]) -> tuple[str, str, str]:
        return (s["state"], s["action"], s.get("next_state") or "")

    pair_counts: dict[tuple[str, str, str], int] = {}
    for s in active:
        pair_counts[transition_key(s)] = pair_counts.get(transition_key(s), 0) + 1

    seen_pair: dict[tuple[str, str, str], int] = {}
    steps: list[StepReward] = []
    for s in active:
        pair = transition_key(s)
        seen_pair[pair] = seen_pair.get(pair, 0) + 1
        in_loop = pair_counts[pair] > 1 and seen_pair[pair] > 1
        no_effect = s["effect"] == "same"

        reward = w["step_cost"]
        reasons: list[str] = []
        if s["error"]:
            reward += w["error_penalty"]
            reasons.append("error")
        if s["effect"] == "changed":
            reward += w["progress_reward"]
            reasons.append("progress")
        elif no_effect:
            reward += w["no_effect_penalty"]
            reasons.append("no effect")
        if in_loop:
            reward += w["loop_penalty"]
            reasons.append("repeat")
        if not reasons:
            reasons.append("step")

        steps.append(StepReward(
            step=s["step"], index=s.get("index"), state=s["state"],
            action=s["action"], effect=s["effect"], error=s["error"],
            no_effect=no_effect, in_loop=in_loop, reward=reward,
            reason=", ".join(reasons), next_state=s.get("next_state"),
        ))

    if steps and outcome_reward:
        steps[-1].reward += w["success_bonus"] * outcome_reward
        if outcome_reward > 0:
            steps[-1].reason = (steps[-1].reason + ", success").strip(", ")

    # Discounted returns, computed backwards: G_t = r_t + gamma * G_{t+1}.
    returns: list[float] = []
    running = 0.0
    for s in reversed(steps):
        running = s.reward + gamma * running
        returns.append(running)
    returns.reverse()

    return ProcessReport(
        steps=steps, returns=returns, outcome_reward=outcome_reward,
        gamma=gamma, weights=w, passive_skipped=passive_skipped,
        signal_source=source,
    )
