"""Agent-declared state assertions — the agent's own claim, verified.

An episode's reward says whether the *task* succeeded.  It says nothing about
what the agent believed along the way, and on a long task that is where the
useful information is: an agent that mis-clicked a button and one that thought it
had finished are indistinguishable from a single terminal 0.

An assertion is the agent saying, mid-episode, *"I believe this is now true"* —
in machine-checkable terms, using the same predicate vocabulary as the reward
spec:

    assertion(name="invoice downloaded", checks=[
        {"kind": "file_exists", "path": "~/invoice.pdf"},
    ])

Why this is worth recording
---------------------------

**Credit assignment.**  The claim is bound to the audit position where it was
made, so a trajectory carries a milestone track — at step 12 the agent believed
X.  That is a far better credit signal than a per-step pixel diff, which cannot
tell a meaningful action from a clock tick.

**Calibration.**  Of the claims the agent made, how many held?  An agent that
says "done" when it is not is a specific, measurable failure mode, and
``precision`` is that measurement.  It is trainable: an agent whose assertions
are accurate is more usable, whatever its task score.

**Regressions.**  A claim is checked twice: when made, and again when the episode
closes.  One that held and then stopped holding means the agent declared success
and later broke it — a real failure mode that neither the terminal reward (too
coarse) nor the step effects (too local) can see.

An assertion is *not* a reward
------------------------------

Stated plainly, because it is the difference between a useful tool and a
reward-hacking surface: **assertions never contribute to the reward.**  The agent
chooses its own checks, and an agent optimising reward would simply assert
something it can trivially satisfy.  Reward comes only from the task's own spec,
whose checks the agent does not author.  An assertion is a *report of belief* —
for a verifier, a trainer, or a human reading the trajectory — and it is judged as
one.

Example::

    from opendesk.learning.assertions import declare, recheck, report

    # mid-episode, after the download
    await declare("invoice downloaded", checks=..., ctx=ctx, session_id="s1")

    # at episode close
    await recheck(session_id="s1", ctx=ctx)
    report("s1").precision        # 1.0 — every claim held
    report("s1").regressed        # 0   — and none was broken afterwards
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from opendesk.learning.rewards import Check, CheckResult, run_checks


@dataclass
class Assertion:
    """One claim the agent made about the state, and what it actually was."""

    name: str
    checks: list[Check]
    #: Position in the audit log when the claim was made.  Journal entries are
    #: filtered out of trajectories, so this is what lets a milestone be
    #: attached to the agent step it *followed* rather than to a bookkeeping
    #: record — see :func:`attach_to_steps`.
    index: int = 0
    #: The agent's own words, if it offered any.  Free text, never parsed: it is
    #: what makes a trajectory readable to a human.
    claim: str = ""
    declared_at: float = field(default_factory=time.time)
    episode_id: Optional[str] = None

    #: Verdict when the claim was made.
    results: list[CheckResult] = field(default_factory=list)
    #: Verdict when the episode closed.  ``None`` until re-checked.
    late_results: Optional[list[CheckResult]] = None
    rechecked_at: Optional[float] = None

    # -- verdicts ---------------------------------------------------------

    @property
    def held(self) -> bool:
        """Did every check pass when the agent made the claim?"""
        return bool(self.results) and all(r.passed for r in self.results)

    @property
    def held_late(self) -> Optional[bool]:
        """Did every check still pass when the episode closed?

        ``None`` when the assertion was never re-checked — which is not the same
        as ``False``, and collapsing the two would invent a regression that was
        never observed.
        """
        if self.late_results is None:
            return None
        return bool(self.late_results) and all(r.passed for r in self.late_results)

    @property
    def regressed(self) -> bool:
        """Held when claimed, and no longer holds at the end."""
        return self.held and self.held_late is False

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "index": self.index,
            "declared_at": self.declared_at,
            "held": self.held,
            "held_late": self.held_late,
            "regressed": self.regressed,
            "checks": [r.to_dict() for r in self.results],
        }
        if self.claim:
            d["claim"] = self.claim
        if self.episode_id:
            d["episode_id"] = self.episode_id
        if self.late_results is not None:
            d["rechecked_at"] = self.rechecked_at
            d["late_checks"] = [r.to_dict() for r in self.late_results]
        return d

    def describe(self) -> str:
        """One line for a human reading a trajectory or a report."""
        mark = "OK " if self.held else "NO "
        line = f"[{mark}] {self.name}"
        if self.claim:
            line += f" — \u201c{self.claim}\u201d"
        if self.held_late is not None:
            if self.regressed:
                line += "  (regressed: no longer true at the end)"
            elif self.held_late and self.held:
                line += "  (still true at the end)"
        for r in self.failed:
            line += f"\n        {r.check.target}: {r.detail}"
        return line


@dataclass
class AssertionReport:
    """How honest the agent's claims were over a session."""

    session_id: str
    assertions: list[Assertion] = field(default_factory=list)

    @property
    def declared(self) -> int:
        return len(self.assertions)

    @property
    def held(self) -> int:
        return sum(1 for a in self.assertions if a.held)

    @property
    def failed_count(self) -> int:
        return sum(1 for a in self.assertions if not a.held)

    @property
    def regressed(self) -> int:
        return sum(1 for a in self.assertions if a.regressed)

    @property
    def rechecked(self) -> int:
        return sum(1 for a in self.assertions if a.late_results is not None)

    @property
    def precision(self) -> float:
        """Share of the agent's claims that were true when made.

        The calibration number.  ``1.0`` when nothing was declared, following the
        convention the process report uses for a vacuous ratio: there is no
        observed dishonesty, so reporting ``0.0`` would read as total failure.
        """
        if not self.assertions:
            return 1.0
        return self.held / len(self.assertions)

    @property
    def stability(self) -> Optional[float]:
        """Share of the *verified* claims that were still true at the end.

        ``None`` when nothing was re-checked, so an un-rechecked session is not
        reported as perfectly stable.  Measured against claims that held, since a
        claim that was false on arrival cannot regress.
        """
        if not self.rechecked:
            return None
        verified = [a for a in self.assertions
                    if a.late_results is not None and a.held]
        if not verified:
            return 1.0
        return sum(1 for a in verified if a.held_late) / len(verified)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "metrics": {
                "declared": self.declared,
                "held": self.held,
                "failed": self.failed_count,
                "regressed": self.regressed,
                "rechecked": self.rechecked,
                "precision": round(self.precision, 4),
                "stability": None if self.stability is None else round(self.stability, 4),
            },
            "assertions": [a.to_dict() for a in self.assertions],
        }

    def summary_text(self, max_items: int = 12) -> str:
        if not self.assertions:
            return (
                "No assertions declared. An agent can claim a state mid-episode "
                "with reward(action='assert', name=..., checks=[...])."
            )
        lines = [
            "Agent-declared assertions",
            f"  {self.declared} declared  |  {self.held} held  |  "
            f"{self.failed_count} failed  |  {self.regressed} regressed",
            f"  precision {self.precision:.0%} "
            f"(claims that were true when made)"
            + (
                f"  |  stability {self.stability:.0%} (still true at the end)"
                if self.stability is not None else
                "  |  stability n/a (not re-checked)"
            ),
            "",
        ]
        lines = [ln for ln in lines if ln != ""]
        for a in self.assertions[:max_items]:
            lines.append("  " + a.describe())
        if self.declared > max_items:
            lines.append(f"  … {self.declared - max_items} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_assertions: dict[str, list[Assertion]] = {}


def _store(session_id: str) -> list[Assertion]:
    return _assertions.setdefault(session_id, [])


def list_assertions(session_id: str = "default") -> list[Assertion]:
    return list(_store(session_id))


def get_assertion(name: str, session_id: str = "default") -> Optional[Assertion]:
    """The most recent assertion with this name — names may repeat."""
    for a in reversed(_store(session_id)):
        if a.name == name:
            return a
    return None


def clear_assertions(session_id: str = "default") -> int:
    n = len(_assertions.get(session_id, []))
    _assertions.pop(session_id, None)
    return n


def report(session_id: str = "default") -> AssertionReport:
    return AssertionReport(session_id=session_id, assertions=list(_store(session_id)))


def for_episode(episode_id: str, session_id: str = "default") -> list[Assertion]:
    return [a for a in _store(session_id) if a.episode_id == episode_id]


# ---------------------------------------------------------------------------
# Declaring and re-checking
# ---------------------------------------------------------------------------

async def declare(
    name: str,
    *,
    checks: Any,
    ctx: Any = None,
    session_id: str = "default",
    claim: str = "",
    index: int = 0,
    episode_id: Optional[str] = None,
) -> Assertion:
    """Record and immediately verify a claim the agent is making.

    Verification happens now rather than later on purpose: the agent gets the
    verdict back in the same call, so a claim that does not hold is something it
    can act on instead of a post-mortem surprise.
    """
    from opendesk.learning.rewards import parse_checks

    parsed = parse_checks(checks)
    assertion = Assertion(
        name=str(name).strip() or "unnamed",
        checks=parsed,
        index=int(index),
        claim=str(claim or ""),
        episode_id=episode_id,
    )
    assertion.results = await run_checks(parsed, ctx=ctx, session_id=session_id)
    _store(session_id).append(assertion)
    return assertion


async def recheck(
    *,
    session_id: str = "default",
    ctx: Any = None,
    episode_id: Optional[str] = None,
) -> list[Assertion]:
    """Re-verify assertions against the closing state.

    Only assertions not already re-checked are touched, so calling this twice
    does not overwrite the first re-check with a fresher, differently-wrong
    answer.  Restricting to one episode when given matters on a best-of-N run,
    where several attempts share a session and only the finishing one is closing.
    """
    targets = [
        a for a in _store(session_id)
        if a.late_results is None
        and (episode_id is None or a.episode_id == episode_id)
    ]
    now = time.time()
    for a in targets:
        a.late_results = await run_checks(a.checks, ctx=ctx, session_id=session_id)
        a.rechecked_at = now
    return targets


# ---------------------------------------------------------------------------
# Trajectory integration
# ---------------------------------------------------------------------------

def attach_to_steps(
    assertions: list[Assertion],
    step_indices: list[int],
) -> dict[int, list[dict[str, Any]]]:
    """Map each assertion onto the agent step it followed.

    *step_indices* are the absolute audit positions of the steps that survive
    into a trajectory, in order.  An assertion is bound to the last such step
    *before* it, which is the action the agent had just taken when it made the
    claim.

    Assertions made before any recorded step are attached to the first step:
    dropping them would hide a claim, and a milestone track with a hole in it is
    worse than one with a slightly loose first entry.
    """
    out: dict[int, list[dict[str, Any]]] = {}
    if not step_indices:
        return out
    ordered = sorted(step_indices)
    for a in assertions:
        target: Optional[int] = None
        for idx in ordered:
            if idx < a.index:
                target = idx
            else:
                break
        if target is None:
            target = ordered[0]
        out.setdefault(target, []).append({
            "name": a.name,
            "held": a.held,
            "claim": a.claim or None,
            "regressed": a.regressed,
            "held_late": a.held_late,
        })
    return out
