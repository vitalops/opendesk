"""Per-session audit sandbox.

The sandbox tracks every action taken against the screen, enforces an optional
application allow-list and screen-region constraint, and maintains a full audit
log that can be exported for reproducibility and compliance.

Usage::

    from opendesk.computer.sandbox import get_sandbox, ActionType

    sandbox = get_sandbox("session-abc")
    await sandbox.record_action(ActionType.SCREENSHOT, params={}, result="ok")
    log = sandbox.export_audit_log()
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """All actions the computer-use subsystem can perform."""

    SCREENSHOT = "screenshot"
    MOUSE_CLICK = "mouse_click"
    MOUSE_MOVE = "mouse_move"
    MOUSE_SCROLL = "mouse_scroll"
    MOUSE_DRAG = "mouse_drag"
    MOUSE_DOWN = "mouse_down"
    MOUSE_UP = "mouse_up"
    CURSOR_POSITION = "cursor_position"
    KEYBOARD_TYPE = "keyboard_type"
    KEYBOARD_PRESS = "keyboard_press"
    KEYBOARD_HOTKEY = "keyboard_hotkey"
    KEYBOARD_HOLD = "keyboard_hold"
    APP_OPEN = "app_open"
    APP_CLOSE = "app_close"
    APP_FOCUS = "app_focus"
    APP_LIST = "app_list"
    CLIPBOARD_READ = "clipboard_read"
    CLIPBOARD_WRITE = "clipboard_write"
    OCR = "ocr"
    UI_ACTION = "ui_action"
    #: Process diagnosis (`diagnose` tool)
    DIAGNOSE = "diagnose"
    #: Verifiable rewards and episode bookkeeping (`reward` tool).  These are
    #: journal entries rather than agent steps: they *score* a run, so a step
    #: walk must not count them as things the agent did.
    EPISODE_BEGIN = "episode_begin"
    EPISODE_END = "episode_end"
    REWARD_CHECK = "reward_check"
    ASSERTION = "assertion"
    ASSERTIONS = "assertions"
    GOAL_CAPTURE = "goal_capture"
    GOAL_SCORE = "goal_score"
    SCRIPT = "script"
    BROWSER = "browser"
    FLEET = "fleet"


@dataclass
class AuditEntry:
    """A single recorded action in the audit log."""

    id: str
    timestamp: float
    action_type: ActionType
    params: dict[str, Any]
    session_id: str
    result: str | None = None
    error: str | None = None
    replay_params: dict[str, Any] | None = None
    #: Fingerprint of the screen this action was issued against.  Lets callers
    #: reconstruct which actions happened on the same functional screen — the
    #: input to state-transition diagnosis.  ``None`` when no screenshot had
    #: been taken yet.
    screen: str | None = None
    #: Content digest of the accessibility tree this action was issued against
    #: (see :func:`opendesk.computer.a11y.content_hash`).  The perceptual
    #: ``screen`` fingerprint groups states by *layout*, so a single edited glyph
    #: does not register as a new state.  This one groups by *content*, so it
    #: does — and a clock tick does not, because the clock is text that did not
    #: change.
    ui: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "id": self.id,
            "timestamp": self.timestamp,
            "action": self.action_type.value,
            "params": self.params,
            "session_id": self.session_id,
            "result": self.result,
            "error": self.error,
        }
        if self.replay_params is not None:
            d["replay_params"] = self.replay_params
        if self.screen is not None:
            d["screen"] = self.screen
        if self.ui is not None:
            d["ui"] = self.ui
        return d


@dataclass
class ComputerSandbox:
    """Per-session sandbox that gates and records computer-use actions.

    Attributes
    ----------
    session_id:
        Owning session — used to correlate audit entries.
    allowed_apps:
        If non-empty, only these application names may be opened/focused.
        Comparisons are case-insensitive substring matches.
    screen_region:
        Optional ``(x, y, width, height)`` bounding box.  When set,
        screenshot and click coordinates are validated to stay inside.
    last_screenshot:
        Last captured PNG bytes — used for automatic change detection.
    audit_log:
        Ordered list of every action taken this session.
    """

    session_id: str
    allowed_apps: list[str] = field(default_factory=list)
    screen_region: tuple[int, int, int, int] | None = None
    last_screenshot: bytes | None = field(default=None, repr=False)
    #: Fingerprint of the most recent screenshot.  Each recorded action captures
    #: this value so the audit log can be grouped by functional screen.
    current_screen: str | None = None
    #: Content digest of the most recent accessibility tree read.  Captured onto
    #: each action so the audit log can be grouped by semantic content, which
    #: distinguishes content edits that look identical in pixels.
    current_ui: str | None = None
    audit_log: list[AuditEntry] = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def is_app_allowed(self, app_name: str) -> bool:
        """Return True when *app_name* passes the allow-list check."""
        if not self.allowed_apps:
            return True
        name_lower = app_name.lower()
        return any(allowed.lower() in name_lower for allowed in self.allowed_apps)

    def is_coordinate_allowed(self, x: int, y: int) -> bool:
        """Return True when *(x, y)* is within the permitted screen region."""
        if self.screen_region is None:
            return True
        rx, ry, rw, rh = self.screen_region
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    async def record_action(
        self,
        action_type: ActionType,
        params: dict[str, Any],
        result: str | None = None,
        error: str | None = None,
        replay_params: dict[str, Any] | None = None,
    ) -> AuditEntry:
        """Append an entry to the audit log and return it."""
        entry = AuditEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            action_type=action_type,
            params=params,
            session_id=self.session_id,
            result=result,
            error=error,
            replay_params=replay_params,
            screen=self.current_screen,
            ui=self.current_ui,
        )
        async with self._lock:
            self.audit_log.append(entry)
        return entry

    def export_audit_log(self) -> list[dict[str, Any]]:
        """Return the full audit log as a list of plain dicts."""
        return [e.to_dict() for e in self.audit_log]

    def summary(self) -> str:
        counts: dict[str, int] = {}
        for e in self.audit_log:
            counts[e.action_type.value] = counts.get(e.action_type.value, 0) + 1
        parts = ", ".join(f"{v}× {k}" for k, v in sorted(counts.items()))
        return (
            f"session={self.session_id[:12]}… | "
            f"{len(self.audit_log)} actions: {parts or 'none'}"
        )


_sandboxes: dict[str, ComputerSandbox] = {}


def get_sandbox(session_id: str) -> ComputerSandbox:
    """Return (creating if needed) the sandbox for *session_id*."""
    if session_id not in _sandboxes:
        _sandboxes[session_id] = ComputerSandbox(session_id=session_id)
    return _sandboxes[session_id]


def clear_sandbox(session_id: str) -> None:
    """Discard the sandbox for *session_id*."""
    _sandboxes.pop(session_id, None)


def configure_sandbox(
    session_id: str,
    allowed_apps: list[str] | None = None,
    screen_region: tuple[int, int, int, int] | None = None,
) -> ComputerSandbox:
    """Create or update a sandbox with specific restrictions.

    Parameters
    ----------
    session_id:
        Session to configure.
    allowed_apps:
        If set, restricts which apps the agent may open/focus.
    screen_region:
        If set, restricts which screen region mouse/screenshot actions may target.
    """
    sandbox = get_sandbox(session_id)
    if allowed_apps is not None:
        sandbox.allowed_apps = allowed_apps
    if screen_region is not None:
        sandbox.screen_region = screen_region
    return sandbox
