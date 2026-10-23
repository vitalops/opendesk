"""Lossless visual observation memory.

A computer-use agent reasons over a stream of screenshots, but the framework
that feeds it usually keeps only the most recent frame.  Once a screenshot is
dropped the agent cannot look at it again — it can only re-capture a *new*
screen and guess what changed.  That is a real handicap on long-horizon tasks:
"what did this dialog look like before I dismissed it?" becomes unanswerable.

This module keeps every observation the agent has made, in its original form,
and makes the history queryable.  The design follows the visual-memory idea
from recent multimodal agent work: a *lossless* store of past observations that
the model can *actively retrieve* and reorganise as it reasons.

Lossless means the original PNG bytes are kept exactly as captured — no
re-encoding, no re-downscaling, no thumbnail substitution.  To bound memory the
store is a bounded ring buffer (``cap``); evicted entries are reported by
:meth:`ObservationStore.stats` so the loss is visible rather than silent.

Layout of a stored observation::

    Observation(
        index=7,                      # absolute, stable across evictions
        timestamp=…,
        png=b"\\x89PNG…",              # lossless original bytes
        width=1920, height=1080,
        fingerprint="3f0a…",          # see computer.capture.screen_fingerprint
        app="Google Chrome",
        window="Invoices — Chrome",
        change_fraction=0.123,        # vs the previous observation
        changed_region=[400, 200, 600, 300],
        marks_summary="[3] AXButton ‟Save” …",
        source="screenshot",
        metadata={},
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

#: Default ring-buffer capacity.  A 1920×1080 PNG is ~1–4 MB, so this caps a
#: session's visual memory at roughly 100–300 MB.  Raise it for long-horizon
#: tasks, lower it on constrained machines.
DEFAULT_CAP = 80


def _snapshot_text(snapshot: Optional[dict[str, Any]]) -> str:
    """Flatten a stored accessibility snapshot into searchable text.

    Lets ``find(text=...)`` reach what a screen actually *said* — the value in a
    field, a row in a list — rather than only the app and window labels.
    """
    if not snapshot:
        return ""
    parts: list[str] = []
    for node in snapshot.values():
        if isinstance(node, dict):
            role = node.get("role", "")
            content = node.get("content") or node.get("value") or node.get("name", "")
        else:
            role = getattr(node, "role", "")
            content = getattr(node, "content", "") or getattr(node, "name", "")
        parts.append(f"{role} {content}")
    return " ".join(parts)


@dataclass
class Observation:
    """One captured screen state, stored losslessly."""

    index: int
    timestamp: float
    png: bytes
    width: int = 0
    height: int = 0
    fingerprint: Optional[str] = None
    app: Optional[str] = None
    window: Optional[str] = None
    change_fraction: Optional[float] = None
    changed_region: Optional[list[int]] = None
    marks_summary: Optional[str] = None
    source: str = "screenshot"
    metadata: dict[str, Any] = field(default_factory=dict)
    #: The accessibility tree's content at capture time, as a
    #: ``{path: A11yNode}`` mapping (see :func:`opendesk.computer.a11y.ui_snapshot`).
    #: Stored alongside the pixels because the two answer different questions:
    #: the PNG says what the screen *looked* like, this says what it *said*.
    #: ``None`` when the capture did not read a tree.
    ui_snapshot: Optional[dict[str, Any]] = None

    def summary(self) -> dict[str, Any]:
        """Compact, image-free description (safe to put in a prompt)."""
        d: dict[str, Any] = {
            "index": self.index,
            "age_s": round(max(0.0, time.time() - self.timestamp), 1),
            "size": f"{self.width}x{self.height}",
            "bytes": len(self.png),
            "source": self.source,
        }
        if self.app:
            d["app"] = self.app
        if self.window:
            d["window"] = self.window
        if self.fingerprint:
            d["screen"] = self.fingerprint[:12]
        if self.change_fraction is not None:
            d["change_fraction"] = round(self.change_fraction, 4)
        if self.changed_region is not None:
            d["changed_region"] = self.changed_region
        if self.marks_summary:
            d["has_marks"] = True
        if self.ui_snapshot:
            d["ui_elements"] = len(self.ui_snapshot)
        return d

    def describe(self) -> str:
        """One-line human/agent-readable label."""
        parts = [f"#{self.index}", f"{self.width}x{self.height}"]
        if self.app:
            parts.append(str(self.app))
        if self.window and self.window != self.app:
            parts.append(f"“{self.window}”")
        if self.change_fraction is not None:
            parts.append(f"Δ{self.change_fraction:.1%}")
        if self.fingerprint:
            parts.append(f"screen={self.fingerprint[:8]}")
        parts.append(f"({int(len(self.png) / 1024)} KB)")
        return "  ".join(parts)


class ObservationStore:
    """Bounded, queryable history of a session's screen captures."""

    def __init__(self, session_id: str, cap: int = DEFAULT_CAP) -> None:
        self.session_id = session_id
        self.cap = max(1, cap)
        self._items: list[Observation] = []
        self._next_index = 0
        self.evicted = 0

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def record(
        self,
        png: bytes,
        *,
        width: int = 0,
        height: int = 0,
        fingerprint: Optional[str] = None,
        app: Optional[str] = None,
        window: Optional[str] = None,
        change_fraction: Optional[float] = None,
        changed_region: Optional[list[int]] = None,
        marks_summary: Optional[str] = None,
        source: str = "screenshot",
        metadata: Optional[dict[str, Any]] = None,
        ui_snapshot: Optional[dict[str, Any]] = None,
    ) -> Observation:
        """Append an observation, evicting the oldest when over capacity."""
        obs = Observation(
            index=self._next_index,
            timestamp=time.time(),
            png=png,
            width=width,
            height=height,
            fingerprint=fingerprint,
            app=app,
            window=window,
            change_fraction=change_fraction,
            changed_region=list(changed_region) if changed_region else None,
            marks_summary=marks_summary,
            source=source,
            metadata=dict(metadata or {}),
            ui_snapshot=dict(ui_snapshot) if ui_snapshot else None,
        )
        self._next_index += 1
        self._items.append(obs)
        while len(self._items) > self.cap:
            self._items.pop(0)
            self.evicted += 1
        return obs

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._items)

    def all(self) -> list[Observation]:
        return list(self._items)

    def latest(self) -> Optional[Observation]:
        return self._items[-1] if self._items else None

    def first(self) -> Optional[Observation]:
        return self._items[0] if self._items else None

    def previous(self) -> Optional[Observation]:
        """The observation before the most recent one."""
        return self._items[-2] if len(self._items) >= 2 else None

    def get(self, index: int) -> Optional[Observation]:
        """Look up by *absolute* index. Returns ``None`` if evicted or absent."""
        for obs in self._items:
            if obs.index == index:
                return obs
        return None

    def resolve(self, ref: Optional[str | int] = None) -> Optional[Observation]:
        """Resolve a user-facing reference to an observation.

        Accepts:

        * ``None`` / ``"latest"`` — the most recent observation
        * ``"first"`` — the oldest still held
        * ``"previous"`` — one before the most recent
        * an ``int`` or numeric string — an absolute index
        * a negative int (or ``"-1"``, ``"-2"`` …) — an offset from the end
        """
        if ref is None or ref == "latest":
            return self.latest()
        if isinstance(ref, int):
            return self._resolve_offset(ref)
        text = str(ref).strip().lower()
        if text == "first":
            return self.first()
        if text == "previous":
            return self.previous()
        if text == "latest":
            return self.latest()
        try:
            return self._resolve_offset(int(text))
        except ValueError:
            return None

    def _resolve_offset(self, value: int) -> Optional[Observation]:
        if not self._items:
            return None
        if value < 0:
            pos = len(self._items) + value
            return self._items[pos] if 0 <= pos < len(self._items) else None
        return self.get(value)

    def timeline(self, limit: Optional[int] = None) -> list[Observation]:
        """Most recent observations in chronological order (oldest → newest)."""
        if limit is not None and limit > 0:
            return self._items[-limit:]
        return list(self._items)

    def find(
        self,
        *,
        app: Optional[str] = None,
        text: Optional[str] = None,
        since: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[Observation]:
        """Filter observations by app, free text, and/or timestamp."""
        app_l = app.lower() if app else None
        text_l = text.lower() if text else None
        out: list[Observation] = []

        for obs in self._items:
            if app_l is not None:
                hay = f"{obs.app or ''} {obs.window or ''}".lower()
                if app_l not in hay:
                    continue
            if text_l is not None:
                hay = " ".join(
                    [
                        str(obs.app or ""),
                        str(obs.window or ""),
                        str(obs.marks_summary or ""),
                        str(obs.metadata),
                        _snapshot_text(obs.ui_snapshot),
                    ]
                ).lower()
                if text_l not in hay:
                    continue
            if since is not None and obs.timestamp < since:
                continue
            out.append(obs)

        if limit is not None and limit > 0:
            out = out[-limit:]
        return out

    def stats(self) -> dict[str, Any]:
        """Memory accounting — how much is held and how much was evicted."""
        total_bytes = sum(len(o.png) for o in self._items)
        return {
            "session_id": self.session_id,
            "held": len(self._items),
            "cap": self.cap,
            "evicted": self.evicted,
            "total_bytes": total_bytes,
            "total_mb": round(total_bytes / (1024 * 1024), 2),
            "lossless": True,
            "oldest_index": self._items[0].index if self._items else None,
            "newest_index": self._items[-1].index if self._items else None,
            "distinct_screens": len(
                {o.fingerprint for o in self._items if o.fingerprint}
            ),
        }

    def clear(self) -> int:
        """Drop everything; returns the number of observations removed."""
        n = len(self._items)
        self._items.clear()
        return n


# ---------------------------------------------------------------------------
# Per-session registry (mirrors computer.sandbox)
# ---------------------------------------------------------------------------

_stores: dict[str, ObservationStore] = {}


def get_store(session_id: str, cap: Optional[int] = None) -> ObservationStore:
    """Return (creating if needed) the observation store for *session_id*."""
    if session_id not in _stores:
        _stores[session_id] = ObservationStore(session_id, cap or DEFAULT_CAP)
    elif cap is not None:
        _stores[session_id].cap = max(1, cap)
    return _stores[session_id]


def clear_store(session_id: str) -> None:
    """Discard the observation store for *session_id*."""
    _stores.pop(session_id, None)
