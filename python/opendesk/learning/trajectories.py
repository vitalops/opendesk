"""Episodes and RL-ready trajectory export.

A recorded session is a useful log; a *trajectory* is training data.  The
difference is structure: an episode has a task, a start, an end, a reward, and
a step sequence in which each step ties an observation to the action taken
against it and the reward that followed.

This module defines that structure and writes it out as JSONL, one record per
line — the shape offline RL and RLVR pipelines expect::

    {"type": "episode", "task": "...", "outcome": {"reward": 1.0, ...}, ...}
    {"type": "step", "step": 1, "observation": {...}, "action": {...},
     "reward": 0.9, "return": 8.4, "done": false, ...}

Screenshots are written alongside as PNG files by default rather than inlined;
a base64 blob per step makes a trajectory unreadable and awkward to stream.
Pass ``embed_images=True`` when a single self-contained file is genuinely
wanted.

Example::

    from opendesk.learning.trajectories import begin_episode, end_episode, export

    ep = begin_episode("install the package", session_id="s1", sandbox=sb)
    ...
    end_episode(ep, session_id="s1", sandbox=sb, outcome={"reward": 1.0})
    path = export(ep, session_id="s1", sandbox=sb, path="runs/ep1.jsonl")
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from opendesk.computer.diagnostics import JOURNAL_ACTIONS

SCHEMA_VERSION = "opendesk.trajectory/1"


@dataclass
class Episode:
    """One task attempt within a session."""

    id: str
    task: str
    session_id: str
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    start_index: int = 0          # audit-log length when the episode began
    end_index: Optional[int] = None
    goal: Optional[str] = None
    spec: Optional[dict[str, Any]] = None
    meta: dict[str, Any] = field(default_factory=dict)
    outcome: Optional[dict[str, Any]] = None
    process: Optional[dict[str, Any]] = None
    #: How honest this attempt's self-reported claims were — see
    #: :mod:`opendesk.learning.assertions`.  ``None`` when the agent declared
    #: none.
    assertions: Optional[dict[str, Any]] = None

    @property
    def finished(self) -> bool:
        return self.ended_at is not None

    @property
    def reward(self) -> Optional[float]:
        if not self.outcome:
            return None
        return self.outcome.get("reward")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_s": round((self.ended_at or time.time()) - self.started_at, 2),
            "goal": self.goal,
            "meta": self.meta,
            "outcome": self.outcome,
            "assertions": self.assertions,
            "process": (
                {k: v for k, v in self.process.items() if k not in ("steps", "returns")}
                if self.process else None
            ),
        }


# ---------------------------------------------------------------------------
# Episode store
# ---------------------------------------------------------------------------

_episodes: dict[str, list[Episode]] = {}


def begin_episode(
    task: str,
    *,
    session_id: str = "default",
    sandbox: Any = None,
    goal: Optional[str] = None,
    spec: Optional[dict[str, Any]] = None,
    meta: Optional[dict[str, Any]] = None,
    episode_id: Optional[str] = None,
) -> Episode:
    """Start a new episode, marking the current position in the audit log."""
    start_index = 0
    if sandbox is not None:
        try:
            start_index = len(sandbox.audit_log)
        except Exception:
            start_index = 0

    ep = Episode(
        id=episode_id or uuid.uuid4().hex[:12],
        task=task,
        session_id=session_id,
        start_index=start_index,
        goal=goal,
        spec=spec,
        meta=dict(meta or {}),
    )
    _episodes.setdefault(session_id, []).append(ep)
    return ep


def end_episode(
    episode: Episode,
    *,
    session_id: str = "default",
    sandbox: Any = None,
    outcome: Optional[dict[str, Any]] = None,
    process: Optional[dict[str, Any]] = None,
    assertions: Optional[dict[str, Any]] = None,
) -> Episode:
    """Close an episode and attach its reward signals."""
    episode.ended_at = time.time()
    if sandbox is not None:
        try:
            episode.end_index = len(sandbox.audit_log)
        except Exception:
            episode.end_index = None
    if outcome is not None:
        episode.outcome = outcome
    if process is not None:
        episode.process = process
    if assertions is not None:
        episode.assertions = assertions
    return episode


def get_episode(episode_id: str, session_id: str = "default") -> Optional[Episode]:
    for ep in _episodes.get(session_id, []):
        if ep.id == episode_id:
            return ep
    return None


def list_episodes(session_id: str = "default") -> list[Episode]:
    return list(_episodes.get(session_id, []))


def latest_episode(session_id: str = "default") -> Optional[Episode]:
    eps = _episodes.get(session_id, [])
    return eps[-1] if eps else None


def clear_episodes(session_id: str = "default") -> int:
    n = len(_episodes.get(session_id, []))
    _episodes.pop(session_id, None)
    return n


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _norm(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return {
            "action": entry.get("action") or entry.get("action_type", ""),
            "params": entry.get("params") or {},
            "result": entry.get("result"),
            "error": entry.get("error"),
            "screen": entry.get("screen"),
            "timestamp": entry.get("timestamp", 0.0),
        }
    action = getattr(entry, "action_type", "")
    return {
        "action": getattr(action, "value", action),
        "params": getattr(entry, "params", {}) or {},
        "result": getattr(entry, "result", None),
        "error": getattr(entry, "error", None),
        "screen": getattr(entry, "screen", None),
        "timestamp": getattr(entry, "timestamp", 0.0),
    }


def _match_observation(store: Any, fingerprint: Optional[str], timestamp: float):
    """Find the observation that a step was issued against.

    The audit entry records the fingerprint of the last screenshot taken before
    the action, so the newest observation with that fingerprint at or before the
    step is the one the agent was looking at.
    """
    if store is None or not fingerprint:
        return None
    best = None
    for obs in store.all():
        if obs.fingerprint == fingerprint and obs.timestamp <= timestamp + 0.001:
            best = obs
    return best


def build_trajectory(
    episode: Episode,
    *,
    entries: list[Any],
    store: Any = None,
    process: Optional[dict[str, Any]] = None,
    assertions: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Assemble a structured trajectory dict for *episode*."""
    raw_window = entries[episode.start_index: episode.end_index] \
        if episode.end_index is not None else entries[episode.start_index:]

    # Journal entries (the reward tool's own checks, episode markers, the
    # agent's assertions) describe the recording, not the task — leaving them in
    # would pad every trajectory with steps that correspond to no agent action.
    # Their absolute positions are kept so process rewards and assertions can
    # still be matched exactly.
    window: list[tuple[int, Any]] = []
    for offset, raw in enumerate(raw_window):
        if _norm(raw)["action"] in JOURNAL_ACTIONS:
            continue
        window.append((episode.start_index + offset, raw))

    # Process rewards are keyed by audit position, since passive calls carry no
    # reward and the two sequences do not line up one-to-one.
    proc_by_index: dict[int, dict[str, Any]] = {}
    return_by_index: dict[int, float] = {}
    if process:
        psteps = process.get("steps") or []
        rvals = process.get("returns") or []
        for i, p in enumerate(psteps):
            idx = p.get("index")
            if idx is None:
                continue
            proc_by_index[idx] = p
            if i < len(rvals):
                return_by_index[idx] = float(rvals[i])

    # Assertions become a milestone track bound to the step each one followed.
    # This is the dense credit-assignment signal: "at step 12 the agent believed
    # X, and X held" is far more useful than a per-step pixel diff.
    from opendesk.learning.assertions import attach_to_steps

    milestone_by_index: dict[int, list[dict[str, Any]]] = {}
    if assertions:
        milestone_by_index = attach_to_steps(assertions, [i for i, _ in window])

    steps: list[dict[str, Any]] = []
    for i, (abs_index, raw) in enumerate(window):
        entry = _norm(raw)
        obs = _match_observation(store, entry["screen"], entry["timestamp"])
        prow = proc_by_index.get(abs_index, {})
        milestones = milestone_by_index.get(abs_index) or []
        steps.append({
            "step": i + 1,
            "timestamp": entry["timestamp"],
            "observation": {
                "screen": entry["screen"],
                "observation_index": obs.index if obs else None,
                "app": obs.app if obs else None,
                "window": obs.window if obs else None,
                "size": f"{obs.width}x{obs.height}" if obs else None,
                "screenshot": None,  # filled by export()
            },
            "action": {"type": entry["action"], "params": entry["params"]},
            "result": entry["result"],
            "error": entry["error"],
            "effect": prow.get("effect"),
            "next_state": prow.get("next_state"),
            "reward": round(float(prow.get("reward", 0.0)), 4),
            "return": round(return_by_index[abs_index], 4)
                      if abs_index in return_by_index else None,
            "assertions": milestones,
            "done": i == len(window) - 1,
        })

    metrics = (process or {}).get("metrics") or {}
    return {
        "schema": SCHEMA_VERSION,
        "type": "episode",
        "episode_id": episode.id,
        "task": episode.task,
        "session_id": episode.session_id,
        "started_at": episode.started_at,
        "ended_at": episode.ended_at,
        "duration_s": round((episode.ended_at or time.time()) - episode.started_at, 2),
        "goal": episode.goal,
        "reward_spec": episode.spec,
        "meta": episode.meta,
        "outcome": episode.outcome,
        "assertions": episode.assertions,
        "process": {
            "gamma": (process or {}).get("gamma"),
            "weights": (process or {}).get("weights"),
            "metrics": metrics,
        },
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export(
    episode: Episode,
    *,
    entries: list[Any],
    store: Any = None,
    process: Optional[dict[str, Any]] = None,
    assertions: Optional[list[Any]] = None,
    path: str,
    image_dir: Optional[str] = None,
    embed_images: bool = False,
) -> dict[str, Any]:
    """Write an episode as JSONL and return a small manifest.

    Parameters
    ----------
    path:
        Destination ``.jsonl`` file.
    image_dir:
        Directory for step screenshots.  Defaults to ``<path>_images/``.
        Ignored when ``embed_images`` is true or the memory holds no images.
    embed_images:
        Inline each screenshot as base64 in the step record instead of writing
        files.  Produces one self-contained but much larger file.
    """
    trajectory = build_trajectory(
        episode, entries=entries, store=store, process=process,
        assertions=assertions,
    )

    dest = os.path.expanduser(path)
    parent = os.path.dirname(dest)
    if parent:
        os.makedirs(parent, exist_ok=True)

    images_written = 0
    if store is not None:
        if embed_images:
            import base64

            for step in trajectory["steps"]:
                idx = step["observation"].get("observation_index")
                obs = store.get(idx) if idx is not None else None
                if obs is not None:
                    step["observation"]["screenshot"] = (
                        "data:image/png;base64,"
                        + base64.b64encode(obs.png).decode("ascii")
                    )
                    images_written += 1
        else:
            img_dir = os.path.expanduser(
                image_dir or f"{dest}_images"
            )
            os.makedirs(img_dir, exist_ok=True)
            for step in trajectory["steps"]:
                idx = step["observation"].get("observation_index")
                obs = store.get(idx) if idx is not None else None
                if obs is None:
                    continue
                name = f"{episode.id}_step{step['step']:03d}.png"
                full = os.path.join(img_dir, name)
                with open(full, "wb") as fh:
                    fh.write(obs.png)
                step["observation"]["screenshot"] = os.path.relpath(
                    full, parent or "."
                ).replace(os.sep, "/")
                images_written += 1

    header = {k: v for k, v in trajectory.items() if k != "steps"}
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({**header, "step_count": len(trajectory["steps"])},
                            ensure_ascii=False) + "\n")
        for step in trajectory["steps"]:
            fh.write(json.dumps({"type": "step", **step}, ensure_ascii=False) + "\n")

    return {
        "path": dest,
        "episode_id": episode.id,
        "steps": len(trajectory["steps"]),
        "images": images_written,
        "image_dir": None if (embed_images or not images_written) else
                     os.path.expanduser(image_dir or f"{dest}_images"),
        "reward": episode.reward,
        "schema": SCHEMA_VERSION,
    }
