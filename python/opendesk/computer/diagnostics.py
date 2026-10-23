"""State-transition diagnosis for recorded sessions.

Evaluation of a computer-use agent usually collapses a hundred-step episode into
a single pass/fail, which says nothing about *where* it went wrong.  This module
follows the state-centric view: map the visually diverse screens an agent saw
onto a smaller set of **functional states**, build a **state-transition graph**
(STG) over recorded actions, and report where failures and wasted effort
concentrate.

Two ideas drive the design:

* Screens that look different can be the *same* functional state (a status bar
  clock, a cursor, a scroll position).  Screens are therefore merged by
  perceptual fingerprint **within a tolerance** rather than compared for
  equality.
* The interesting signal is structural: a state the agent kept returning to, an
  action that never changed the screen, a state where every action errored.

What it reports
---------------
``bottlenecks``  states where errors concentrate (failures are rarely uniform)
``loops``        repeated (state → action → state) cycles
``inertia``      runs of actions that produced no visible state change
``dead_ends``    states with no successful outgoing transition
``replay``       per-step effect signal — the raw material for step-level rewards

Example::

    from opendesk.computer.sandbox import get_sandbox
    from opendesk.computer.diagnostics import diagnose

    report = diagnose(get_sandbox("s1").export_audit_log())
    print(report.summary_text())
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

#: Fingerprints within this Hamming distance are treated as the same state.
#: 4/256 bits absorbs rendering jitter and small content changes alike — see
#: :func:`opendesk.computer.capture.screen_fingerprint` for the measured
#: distances.  States therefore group by *structure*: a dialog opening (26 bits)
#: or a theme switch (40 bits) splits, while a typed glyph (0 bits) does not.
#: Raise it to merge more aggressively, lower it to split more.
#:
#: Only the pixel fallback uses this.  When a session recorded accessibility
#: content digests, states group by *content* instead and no tolerance applies —
#: see the ``identity`` parameter of :func:`diagnose`.
DEFAULT_TOLERANCE = 4

#: Actions that never move the interface on their own — excluded from the graph
#: so read-only polling does not look like a lack of progress.
#: The learning and diagnostic layer's own records.  These are journal entries
#: about a session, not actions taken in it, so they are excluded from the
#: state graph and from exported trajectories entirely.
JOURNAL_ACTIONS = frozenset({
    "episode_begin", "episode_end", "reward_check", "goal_capture",
    "goal_score", "diagnose", "assertion", "assertions",
})

#: Real agent actions that observe rather than act.  They belong in a
#: trajectory but never move the interface, so they carry no process reward.
OBSERVATION_ACTIONS = frozenset({
    "screenshot", "cursor_position", "app_list", "clipboard_read", "ocr",
    "clipboard_write",
})

#: Everything that never counts as a state-moving action.
PASSIVE_ACTIONS = JOURNAL_ACTIONS | OBSERVATION_ACTIONS


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class StateNode:
    """A functional screen state — possibly several raw screens merged."""

    id: str
    representative: str
    screens: set[str] = field(default_factory=set)
    visits: int = 0
    errors: int = 0
    actions: Counter = field(default_factory=Counter)
    successor_actions: set[str] = field(default_factory=set)
    first_step: int = -1
    last_step: int = -1

    @property
    def error_rate(self) -> float:
        return self.errors / self.visits if self.visits else 0.0

    def observe(self, fingerprint: str, step: int, action: Optional[str], error: bool) -> None:
        self.screens.add(fingerprint)
        self.visits += 1
        if error:
            self.errors += 1
        if action:
            self.actions[action] += 1
        if self.first_step < 0:
            self.first_step = step
        self.last_step = step

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "screen": self.representative[:12],
            "visits": self.visits,
            "errors": self.errors,
            "error_rate": round(self.error_rate, 3),
            "merged_screens": len(self.screens),
            "actions": dict(self.actions.most_common()),
        }


@dataclass
class Transition:
    src: str
    dst: str
    action: str
    count: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.src,
            "to": self.dst,
            "action": self.action,
            "count": self.count,
            "errors": self.errors,
        }


@dataclass
class DiagnosticReport:
    """Structured result of a state-transition diagnosis."""

    nodes: dict[str, StateNode] = field(default_factory=dict)
    transitions: list[Transition] = field(default_factory=list)
    bottlenecks: list[dict[str, Any]] = field(default_factory=list)
    loops: list[dict[str, Any]] = field(default_factory=list)
    inertia: list[dict[str, Any]] = field(default_factory=list)
    dead_ends: list[dict[str, Any]] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    tolerance: int = DEFAULT_TOLERANCE
    #: What the states were grouped by — ``"ui"`` (accessibility content) or
    #: ``"screen"`` (perceptual fingerprint).
    identity: str = "screen"
    fused_count: int = 0
    skipped: int = 0
    #: Journal entries (the learning layer's own bookkeeping) left out entirely.
    journal_skipped: int = 0

    # -- derived metrics ------------------------------------------------

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def state_count(self) -> int:
        return len(self.nodes)

    @property
    def error_count(self) -> int:
        return sum(n.errors for n in self.nodes.values())

    @property
    def no_effect_count(self) -> int:
        """Steps whose action left the interface unchanged."""
        return sum(1 for s in self.steps if s["effect"] == "same")

    def bottleneck_concentration(self) -> float:
        """Share of all errors that occurred in the worst 20% of states.

        The headline number from state-centric analysis: failures are far from
        uniform.  Returns ``0.0`` when there is nothing to compare.
        """
        if not self.nodes:
            return 0.0
        ordered = sorted(self.nodes.values(), key=lambda n: n.errors, reverse=True)
        top = max(1, round(len(ordered) * 0.2))
        total = sum(n.errors for n in ordered)
        if total == 0:
            return 0.0
        return sum(n.errors for n in ordered[:top]) / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "states": [n.to_dict() for n in self.nodes.values()],
            "transitions": [t.to_dict() for t in self.transitions],
            "bottlenecks": self.bottlenecks,
            "loops": self.loops,
            "inertia": self.inertia,
            "dead_ends": self.dead_ends,
            "metrics": {
                "steps": self.step_count,
                "states": self.state_count,
                "screens_merged": self.fused_count,
                "errors": self.error_count,
                "no_effect_steps": self.no_effect_count,
                "bottleneck_concentration": round(self.bottleneck_concentration(), 3),
                "tolerance": self.tolerance,
                "identity": self.identity,
                "journal_skipped": self.journal_skipped,
            },
        }

    def summary_text(self, max_items: int = 5) -> str:
        how = (
            "content digests" if self.identity == "ui"
            else f"screens merged within tolerance {self.tolerance}"
        )
        lines = [
            "State-transition diagnosis",
            f"  {self.step_count} step(s) → {self.state_count} functional state(s)"
            f"  ({self.fused_count} screen(s) merged by {how})",
            f"  {self.error_count} error(s)  |  {self.no_effect_count} action(s) with no visible effect",
        ]
        conc = self.bottleneck_concentration()
        if self.error_count:
            lines.append(
                f"  Bottleneck concentration: {conc:.0%} of errors sit in the "
                f"worst 20% of states"
            )
            if conc >= 0.6:
                lines.append(
                    "  → Failures are highly concentrated. Fix these states rather "
                    "than the whole task."
                )

        lines.append("")
        lines.append("States:")
        for node in sorted(self.nodes.values(), key=lambda n: n.visits, reverse=True)[:max_items]:
            lines.append(
                f"  {node.id}  visits={node.visits}  errors={node.errors}  "
                f"screens_merged={len(node.screens)}  {dict(node.actions.most_common(3))}"
            )

        if self.bottlenecks:
            lines.append("")
            lines.append("Bottlenecks (errors concentrate here):")
            for b in self.bottlenecks[:max_items]:
                lines.append(
                    f"  {b['state']}  {b['errors']}/{b['visits']} failed "
                    f"({b['error_rate']:.0%})  actions={b['actions']}"
                )

        if self.inertia:
            lines.append("")
            lines.append("Inertia (actions with no visible effect):")
            for g in self.inertia[:max_items]:
                lines.append(
                    f"  {g['length']}x {g['action']} on {g['state']} "
                    f"(steps {g['start']}–{g['end']})"
                )

        if self.loops:
            lines.append("")
            lines.append("Loops (state → action → state cycles):")
            for lp in self.loops[:max_items]:
                lines.append(
                    f"  {lp['from']} --{lp['action']}--> {lp['to']}  x{lp['count']}"
                )

        if self.dead_ends:
            lines.append("")
            lines.append("Dead ends (no successful outgoing transition):")
            for d in self.dead_ends[:max_items]:
                lines.append(f"  {d['state']}  visits={d['visits']}  actions={d['actions']}")

        if self.skipped:
            lines.append("")
            what = (
                "accessibility digest" if self.identity == "ui"
                else "screen fingerprint"
            )
            lines.append(
                f"  ({self.skipped} action(s) had no {what} and were skipped "
                "— observe the screen before acting to improve coverage.)"
            )
        if self.journal_skipped:
            lines.append(
                f"  ({self.journal_skipped} bookkeeping record(s) — reward checks, "
                "episode markers — excluded.)"
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _norm(entry: Any) -> dict[str, Any]:
    """Accept an :class:`AuditEntry`, its ``to_dict()`` form, or a plain dict."""
    if isinstance(entry, dict):
        return {
            "action": entry.get("action") or entry.get("action_type", ""),
            "error": bool(entry.get("error")),
            "screen": entry.get("screen"),
            "ui": entry.get("ui"),
            "timestamp": entry.get("timestamp", 0.0),
            "params": entry.get("params") or {},
            "result": entry.get("result"),
        }
    action = getattr(entry, "action_type", "")
    action = getattr(action, "value", action)
    return {
        "action": action,
        "error": bool(getattr(entry, "error", None)),
        "screen": getattr(entry, "screen", None),
        "ui": getattr(entry, "ui", None),
        "timestamp": getattr(entry, "timestamp", 0.0),
        "params": getattr(entry, "params", {}) or {},
        "result": getattr(entry, "result", None),
    }


def _distance(a: str, b: str) -> int:
    try:
        return (int(a, 16) ^ int(b, 16)).bit_count()
    except (ValueError, TypeError):
        return -1


def _resolve_identity(entries: list[dict[str, Any]], requested: str) -> str:
    """Decide whether to group states by accessibility content or by pixels.

    ``"auto"`` settles it once for the whole log rather than per entry: a state
    graph that mixed the two identities would split one screen across two states
    and merge two different ones, which is worse than either choice alone.
    """
    if requested == "screen":
        return "screen"
    considered = [e for e in entries if e["action"] not in JOURNAL_ACTIONS]
    with_ui = sum(1 for e in considered if e["ui"])
    if requested == "ui":
        return "ui" if with_ui else "screen"
    if considered and with_ui == len(considered):
        return "ui"
    return "screen"


def diagnose(
    entries: Iterable[Any],
    *,
    tolerance: int = DEFAULT_TOLERANCE,
    max_loop_length: int = 4,
    index_offset: int = 0,
    identity: str = "auto",
) -> DiagnosticReport:
    """Build a state-transition graph from recorded actions and diagnose it.

    Parameters
    ----------
    entries:
        Audit entries (``AuditEntry`` objects or their dict form), in
        chronological order.  Entries without the identity being used cannot be
        placed in the graph and are counted in ``report.skipped``.
    tolerance:
        Fingerprint Hamming distance under which two screens are the same state.
        Ignored when states are grouped by accessibility content, which is an
        exact comparison.
    max_loop_length:
        Longest cycle length to report as a loop.
    index_offset:
        Added to every reported ``index``.  ``entries`` is often a slice of a
        longer audit log; this keeps the reported positions absolute so callers
        that key off them (trajectory assembly) still line up.
    identity:
        What to group states by.

        ``"screen"``
            The perceptual fingerprint: fast, no accessibility tree needed, and
            blind to content edits — a one-glyph change is the same state.
        ``"ui"``
            The accessibility content digest recorded on each entry.  Sees a
            glyph edit and ignores a clock tick, at the cost of needing a tree
            read per action.
        ``"auto"`` (default)
            Use ``"ui"`` when *every* action in the log carries a digest, else
            ``"screen"``.  All-or-nothing rather than per-entry, because mixing
            identities would split a single screen across two states.

        The choice is reported as ``report.identity``.
    """
    report = DiagnosticReport(tolerance=tolerance)
    normalised = [_norm(e) for e in entries]

    identity = _resolve_identity(normalised, identity)
    report.identity = identity
    key = "ui" if identity == "ui" else "screen"
    semantic = identity == "ui"

    # --- 1. map identities → functional states ---------------------------
    raw_screens: list[str] = [
        e[key] for e in normalised
        if e[key] and e["action"] not in JOURNAL_ACTIONS
    ]
    if not raw_screens:
        report.journal_skipped = sum(
            1 for e in normalised if e["action"] in JOURNAL_ACTIONS
        )
        report.skipped = len(normalised) - report.journal_skipped
        return report

    represent_to_node: dict[str, str] = {}
    node_seq = 0

    def state_for(fingerprint: str) -> str:
        nonlocal node_seq
        if semantic:
            existing = represent_to_node.get(fingerprint)
            if existing is not None:
                return existing
        else:
            for rep, node_id in represent_to_node.items():
                if _distance(rep, fingerprint) <= tolerance:
                    return node_id
        node_id = f"S{node_seq}"
        node_seq += 1
        represent_to_node[fingerprint] = node_id
        node = StateNode(id=node_id, representative=fingerprint)
        node.screens.add(fingerprint)
        report.nodes[node_id] = node
        return node_id

    # --- 2. place actions on states, derive transitions ------------------
    # (step, state_id, entry, absolute index in the input list)
    seq: list[tuple[int, str, dict[str, Any], int]] = []
    step = 0
    for abs_index, entry in enumerate(normalised):
        if entry["action"] in JOURNAL_ACTIONS:
            report.journal_skipped += 1
            continue
        if not entry[key]:
            report.skipped += 1
            continue
        step += 1
        sid = state_for(entry[key])
        seq.append((step, sid, entry, abs_index))
        report.nodes[sid].observe(
            entry[key], step, entry["action"], entry["error"]
        )

    edges: dict[tuple[str, str, str], Transition] = {}
    for i, (step_i, state_i, entry_i, abs_i) in enumerate(seq):
        nxt = seq[i + 1] if i + 1 < len(seq) else None
        nxt_state = nxt[1] if nxt else None
        effect = "none"
        if nxt_state is not None:
            effect = "same" if nxt_state == state_i else "changed"

        report.steps.append({
            "step": step_i,
            "index": index_offset + abs_i,
            "state": state_i,
            "action": entry_i["action"],
            "error": entry_i["error"],
            "next_state": nxt_state,
            "effect": effect,
        })

        if entry_i["action"] in PASSIVE_ACTIONS:
            continue
        if nxt_state is not None:
            key = (state_i, nxt_state, entry_i["action"])
            tr = edges.get(key)
            if tr is None:
                tr = Transition(src=state_i, dst=nxt_state, action=entry_i["action"])
                edges[key] = tr
            tr.count += 1
            if entry_i["error"]:
                tr.errors += 1
            report.nodes[state_i].successor_actions.add(entry_i["action"])

    report.transitions = sorted(
        edges.values(), key=lambda t: t.count, reverse=True
    )

    # Number of raw screens folded into each state.
    for node in report.nodes.values():
        report.fused_count += max(0, len(node.screens) - 1)

    # --- 3. bottlenecks --------------------------------------------------
    for node in report.nodes.values():
        if node.errors:
            report.bottlenecks.append({
                "state": node.id,
                "visits": node.visits,
                "errors": node.errors,
                "error_rate": round(node.error_rate, 3),
                "actions": dict(node.actions.most_common(3)),
            })
    report.bottlenecks.sort(key=lambda b: (b["errors"], b["visits"]), reverse=True)

    # --- 4. inertia: runs of actions that changed nothing ----------------
    run: list[dict[str, Any]] = []

    def flush_inertia() -> None:
        if len(run) >= 2:
            report.inertia.append({
                "state": run[0]["state"],
                "action": run[0]["action"],
                "length": len(run),
                "start": run[0]["step"],
                "end": run[-1]["step"],
            })

    for s in report.steps:
        if s["effect"] == "same" and not s["error"]:
            if run and (s["state"], s["action"]) != (run[0]["state"], run[0]["action"]):
                flush_inertia()
                run = []
            run.append(s)
        else:
            flush_inertia()
            run = []
    flush_inertia()
    report.inertia.sort(key=lambda g: g["length"], reverse=True)

    # --- 5. loops: cycles of bounded length ------------------------------
    edge_by_pair: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for t in report.transitions:
        edge_by_pair[(t.src, t.dst)][t.action] += t.count

    seen_loops: set[tuple[str, ...]] = set()
    for (src, dst), actions in edge_by_pair.items():
        if src == dst:
            nodes_path = (src,)
        elif (dst, src) in edge_by_pair:
            nodes_path = (src, dst)
        else:
            continue
        if nodes_path in seen_loops:
            continue
        seen_loops.add(nodes_path)
        action = actions.most_common(1)[0][0]
        count = actions.most_common(1)[0][1] if src != dst else sum(actions.values())
        back = edge_by_pair.get((dst, src)) if src != dst else None
        report.loops.append({
            "from": src,
            "to": dst,
            "action": action,
            "count": count,
            "mutual": bool(back),
        })
    report.loops.sort(key=lambda x: x["count"], reverse=True)

    # --- 6. dead ends ----------------------------------------------------
    for node in report.nodes.values():
        if node.successor_actions:
            continue
        # Only flag states the agent actually tried to act from.
        acted = [a for a in node.actions if a not in PASSIVE_ACTIONS]
        if not acted:
            continue
        report.dead_ends.append({
            "state": node.id,
            "visits": node.visits,
            "actions": dict(node.actions.most_common(3)),
        })
    report.dead_ends.sort(key=lambda d: d["visits"], reverse=True)

    return report


def diagnose_sandbox(sandbox: Any, **kwargs) -> DiagnosticReport:
    """Convenience wrapper around :func:`diagnose` for a sandbox object."""
    return diagnose(sandbox.export_audit_log(), **kwargs)


def step_effect_signals(entries: Iterable[Any], **kwargs) -> list[dict[str, Any]]:
    """Return just the per-step effect signals (used for step-level rewards).

    Each item: ``{step, state, action, error, next_state, effect}`` where
    ``effect`` is ``"changed"``, ``"same"``, or ``"none"`` (last step).
    """
    return diagnose(entries, **kwargs).steps


def _mutation_key(entry: dict[str, Any]) -> str:
    """A stable, comparable identity for an action's arguments."""
    try:
        return json.dumps(entry.get("params") or {}, sort_keys=True, default=str)
    except Exception:  # pragma: no cover - params are plain data in practice
        return repr(entry.get("params"))


def non_visual_step_signals(
    entries: Iterable[Any], *, index_offset: int = 0
) -> list[dict[str, Any]]:
    """Per-step effect signals for an audit stream that carries no screenshots.

    The state-transition graph is built from screen fingerprints, so a session
    that never took a screenshot — a CLI-only task, or any host without capture
    — yields no graph and therefore no step-level reward at all.  That silently
    removes the dense signal from exactly the deployments the hybrid
    ``system`` tool is meant to encourage.

    This derives the same shape of signal from what a non-visual action *is*,
    rather than from what the screen looked like afterwards.  A non-passive
    action is presumed to move the world; the one case where it clearly did not
    is when it repeats the previous mutation verbatim and that previous
    mutation succeeded — retrying a *failed* action is a repair, not a stall.
    Repeating the same command twice is the command-line analogue of an action
    that left the interface unchanged.

    Returns the same dict shape as :func:`diagnose` produces in ``steps``, so
    callers that consume effect signals do not need to know which path ran.
    """
    normalised = [_norm(e) for e in entries]
    kept: list[tuple[int, dict[str, Any]]] = [
        (i, e) for i, e in enumerate(normalised) if e["action"] not in JOURNAL_ACTIONS
    ]

    # Walk the stream assigning each step the "world epoch" it was issued in.
    # The epoch advances only for an action presumed to have changed something.
    states: list[str] = []
    epoch = 0
    prev: Optional[tuple[str, str, bool]] = None
    for _index, entry in kept:
        states.append(f"A{epoch}")
        if entry["action"] in PASSIVE_ACTIONS:
            continue  # observing does not move the world
        key = _mutation_key(entry)
        repeated = (
            prev is not None
            and prev[0] == entry["action"]
            and prev[1] == key
            and not prev[2]
        )
        if not entry["error"] and not repeated:
            epoch += 1
        prev = (entry["action"], key, entry["error"])

    steps: list[dict[str, Any]] = []
    for i, (abs_index, entry) in enumerate(kept):
        next_state = states[i + 1] if i + 1 < len(states) else None
        if next_state is None:
            effect = "none"
        else:
            effect = "same" if next_state == states[i] else "changed"
        steps.append({
            "step": i + 1,
            "index": index_offset + abs_index,
            "state": states[i],
            "action": entry["action"],
            "error": entry["error"],
            "next_state": next_state,
            "effect": effect,
        })
    return steps
