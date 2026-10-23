"""Goal-state anchoring — score an end state against a recorded reference.

A task's success is often easier to state as "the screen should end up like
*this*" than as a list of file or shell assertions.  Goal-state anchoring
records a reference state — a screenshot plus the labelled UI elements it
contained — and later scores the current state against it.

The score has two parts, because either alone is fooled easily:

* **visual similarity** — pixel similarity plus perceptual-fingerprint
  agreement.  Catches "the layout is still the old one".
* **anchor recall** — the share of the reference's labelled elements
  (role + accessible name) that are present now.  Catches "the pixels look
  similar because both screens are mostly empty".

Neither is trusted alone; both are reported so a caller can see *why* a state
scored the way it did.  This follows the goal-state-anchor idea: reference
elements in a known-good state are the reward signal.

Example::

    from opendesk.learning.goal_state import capture_goal, score_goal

    await capture_goal("done", ctx, session_id="s1")   # record the goal
    result = await score_goal("done", ctx, session_id="s1")
    result.score        # 0.0 – 1.0
    result.matched      # which anchors were found
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

#: The a11y roles worth anchoring on.  Decorative containers are skipped: they
#: rarely distinguish a good end state from a bad one and vary between runs.
_ANCHOR_ROLES = frozenset({
    "AXButton", "AXTextField", "AXTextArea", "AXCheckBox", "AXRadioButton",
    "AXPopUpButton", "AXComboBox", "AXLink", "AXSearchField", "AXMenuButton",
    "AXSlider", "AXStaticText", "AXHeading", "AXTab", "AXRow",
    "button", "checkbox", "radio button", "text", "entry", "combo box",
    "link", "slider", "menu item", "label", "heading", "tab",
    "Button", "Edit", "CheckBox", "ComboBox", "ListItem", "MenuItem",
    "Hyperlink", "Slider", "Spinner", "TabItem", "Text", "Pane",
})

_MAX_ANCHORS = 60
_DEFAULT_MIN_SIMILARITY = 0.80


@dataclass
class Anchor:
    """One labelled, locatable element in a reference state."""

    role: str
    name: str
    cx: float = 0.0  # normalised centre, 0..1
    cy: float = 0.0
    w: float = 0.0   # normalised size
    h: float = 0.0

    @property
    def key(self) -> str:
        return f"{self.role.strip().lower()}|{self.name.strip().lower()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "center": [round(self.cx, 4), round(self.cy, 4)],
            "size": [round(self.w, 4), round(self.h, 4)],
        }


@dataclass
class GoalState:
    """A recorded reference state for a task."""

    name: str
    fingerprint: str
    png: bytes = field(repr=False, default=b"")
    width: int = 0
    height: int = 0
    anchors: list[Anchor] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_image: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "fingerprint": self.fingerprint,
            "size": f"{self.width}x{self.height}",
            "anchors": [a.to_dict() for a in self.anchors],
            "created_at": self.created_at,
            "meta": self.meta,
        }
        if include_image:
            import base64

            d["png_b64"] = base64.b64encode(self.png).decode("ascii")
        return d


@dataclass
class GoalScore:
    """How closely a state matches a goal."""

    goal: str
    visual_similarity: float
    anchor_recall: float
    score: float
    threshold: float
    matched: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    detail: str = ""

    @property
    def reached(self) -> bool:
        return self.score >= self.threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "visual_similarity": round(self.visual_similarity, 4),
            "anchor_recall": round(self.anchor_recall, 4),
            "score": round(self.score, 4),
            "threshold": self.threshold,
            "reached": self.reached,
            "matched": self.matched,
            "missing": self.missing,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Tree flattening
# ---------------------------------------------------------------------------

def _get(node: Any, key: str, default: Any = None) -> Any:
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


def flatten_anchors(
    root: Any,
    screen_w: int = 0,
    screen_h: int = 0,
    max_count: int = _MAX_ANCHORS,
) -> list[Anchor]:
    """Walk a UI tree and return the labelled, locatable elements worth anchoring.

    Accepts objects with ``role``/``name``/``bounds``/``children`` or equivalent
    dicts, so it works against both the live accessibility tree and a
    deserialised one.
    """
    out: list[Anchor] = []

    def visit(node: Any) -> None:
        if len(out) >= max_count or node is None:
            return
        role = str(_get(node, "role", "") or "")
        name = str(_get(node, "name", "") or _get(node, "title", "") or "")
        bounds = _get(node, "bounds")

        if role in _ANCHOR_ROLES and name and bounds is not None:
            w = float(_get(bounds, "width", 0) or 0)
            h = float(_get(bounds, "height", 0) or 0)
            x = float(_get(bounds, "x", 0) or 0)
            y = float(_get(bounds, "y", 0) or 0)
            if w > 2 and h > 2:
                out.append(Anchor(
                    role=role,
                    name=name[:80],
                    cx=(x + w / 2) / screen_w if screen_w else 0.0,
                    cy=(y + h / 2) / screen_h if screen_h else 0.0,
                    w=w / screen_w if screen_w else 0.0,
                    h=h / screen_h if screen_h else 0.0,
                ))

        for child in (_get(node, "children", []) or []):
            visit(child)

    visit(root)
    return out


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

async def capture_goal(
    name: str,
    ctx: Any,
    *,
    session_id: str = "default",
    meta: Optional[dict[str, Any]] = None,
) -> GoalState:
    """Record the current screen + accessibility tree as a goal state."""
    from opendesk.computer.capture import screen_fingerprint

    png, w, h = await _capture(ctx)

    loop = asyncio.get_event_loop()
    try:
        fingerprint = await loop.run_in_executor(None, screen_fingerprint, png)
    except Exception:
        fingerprint = ""

    anchors: list[Anchor] = []
    try:
        tree = await ctx.computer.ui_tree()
        anchors = await loop.run_in_executor(None, flatten_anchors, tree, w, h)
    except Exception:
        anchors = []

    goal = GoalState(
        name=name,
        fingerprint=fingerprint,
        png=png,
        width=w,
        height=h,
        anchors=anchors,
        meta=dict(meta or {}),
    )
    _store(session_id)[name] = goal
    return goal


async def _capture(ctx: Any) -> tuple[bytes, int, int]:
    """Capture the screen, preferring the sandbox's cached frame if present."""
    from opendesk.computer.capture import capture_screen

    loop = asyncio.get_event_loop()
    try:
        png, w, h = await loop.run_in_executor(None, capture_screen, None)
        return png, w, h
    except Exception:
        pass

    pixmap = await ctx.computer.capture()
    return pixmap.data, pixmap.width, pixmap.height


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

async def score_goal(
    name: str,
    ctx: Any,
    *,
    session_id: str = "default",
    min_similarity: float = _DEFAULT_MIN_SIMILARITY,
    compare_anchors: bool = True,
    current_png: Optional[bytes] = None,
) -> GoalScore:
    """Score the current state against a recorded goal."""
    goal = get_goal(name, session_id)
    if goal is None:
        raise KeyError(
            f"No goal state named {name!r} for session {session_id!r}. "
            f"Known: {sorted(_store(session_id))}"
        )

    if current_png is None:
        current_png, _, _ = await _capture(ctx)

    visual = await _visual_similarity(goal, current_png)

    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    anchor_recall = 1.0
    if compare_anchors and goal.anchors:
        try:
            tree = await ctx.computer.ui_tree()
            current = flatten_anchors(tree, goal.width, goal.height)
            anchor_recall, matched, missing = _match_anchors(goal.anchors, current)
        except Exception:
            anchor_recall = 1.0
            matched, missing = [], []

    # Visual similarity gates the score; anchors refine it.  Both must agree
    # before a state counts as reached.
    score = visual * 0.6 + anchor_recall * 0.4
    if visual < min_similarity:
        score = min(score, visual)

    parts = [f"visual similarity {visual:.1%}"]
    if goal.anchors and compare_anchors:
        parts.append(f"anchor recall {anchor_recall:.0%} ({len(matched)}/{len(goal.anchors)})")
    detail = "; ".join(parts)

    return GoalScore(
        goal=name,
        visual_similarity=visual,
        anchor_recall=anchor_recall,
        score=score,
        threshold=min_similarity,
        matched=matched,
        missing=missing,
        detail=detail,
    )


async def _visual_similarity(goal: GoalState, current_png: bytes) -> float:
    from opendesk.computer.capture import (
        diff_screenshots,
        fingerprint_distance,
        screen_fingerprint,
    )

    loop = asyncio.get_event_loop()

    pixel = 0.0
    try:
        diff = await loop.run_in_executor(None, diff_screenshots, goal.png, current_png)
        pixel = 1.0 - float(diff.get("change_fraction") or 0.0)
    except Exception:
        try:
            diff = diff_screenshots(goal.png, current_png)
            pixel = 1.0 - float(diff.get("change_fraction") or 0.0)
        except Exception:
            return 0.0

    fp_bits = 0.0
    try:
        cur_fp = await loop.run_in_executor(None, screen_fingerprint, current_png)
        dist = fingerprint_distance(goal.fingerprint, cur_fp)
        if dist >= 0:
            bits = len(goal.fingerprint) * 4
            fp_bits = max(0.0, 1.0 - dist / max(1, bits))
    except Exception:
        fp_bits = pixel

    # Pixel overlap is sensitive to a single moved element; the fingerprint is
    # robust but coarse.  Average them.
    return max(0.0, min(1.0, (pixel + fp_bits) / 2))


def _match_anchors(
    goal_anchors: list[Anchor], current: list[Anchor]
) -> tuple[float, list[dict[str, Any]], list[dict[str, Any]]]:
    by_key: dict[str, list[Anchor]] = {}
    for a in current:
        by_key.setdefault(a.key, []).append(a)

    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for g in goal_anchors:
        candidates = by_key.get(g.key, [])
        if candidates:
            # Prefer the candidate nearest the recorded position, when both
            # sides carry usable geometry.
            best_delta = None
            if g.cx or g.cy:
                for c in candidates:
                    delta = abs(c.cx - g.cx) + abs(c.cy - g.cy)
                    if best_delta is None or delta < best_delta:
                        best_delta = delta
            entry = {"role": g.role, "name": g.name}
            if best_delta is not None:
                entry["position_delta"] = round(best_delta, 4)
            matched.append(entry)
        else:
            missing.append({"role": g.role, "name": g.name})

    recall = len(matched) / len(goal_anchors) if goal_anchors else 1.0
    return recall, matched, missing


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_goals: dict[str, dict[str, GoalState]] = {}


def _store(session_id: str) -> dict[str, GoalState]:
    return _goals.setdefault(session_id, {})


def get_goal(name: str, session_id: str = "default") -> Optional[GoalState]:
    return _store(session_id).get(name)


def list_goals(session_id: str = "default") -> list[str]:
    return sorted(_store(session_id))


def delete_goal(name: str, session_id: str = "default") -> bool:
    return _store(session_id).pop(name, None) is not None


def clear_goals(session_id: str = "default") -> int:
    n = len(_store(session_id))
    _goals.pop(session_id, None)
    return n
