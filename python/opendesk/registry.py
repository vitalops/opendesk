"""Tool registry — create and look up tools by name.

Usage::

    from opendesk.registry import create_registry

    registry = create_registry()
    tool = registry.get("screenshot")
    result = await tool.execute(ctx, tool.parse_params({"marks": True}))
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendesk.tools.base import Tool


class ToolRegistry:
    """A dict-like container of :class:`~opendesk.tools.base.Tool` instances."""

    def __init__(self) -> None:
        self._tools: dict[str, "Tool"] = {}

    def register(self, tool: "Tool") -> None:
        """Add *tool* to the registry."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> "Tool":
        """Return the tool with *name*, raising :class:`KeyError` if not found."""
        if name not in self._tools:
            raise KeyError(
                f"Tool {name!r} not found. Available: {list(self._tools)}"
            )
        return self._tools[name]

    def names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools)

    def tools(self) -> list["Tool"]:
        """Return all registered tools."""
        return list(self._tools.values())

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({self.names()})"


def create_registry() -> ToolRegistry:
    """Create a :class:`ToolRegistry` populated with all built-in tools.

    Tools included
    --------------
    - ``screenshot`` — capture screen, SoM marks, cursor overlay, zoom, diff
    - ``mouse``      — click, scroll, drag, move, Retina-aware coordinate scaling
    - ``keyboard``   — type (Unicode), press, hotkey, hold
    - ``app``        — open / close / focus / list applications
    - ``ui``         — accessibility-based interaction (FIRST CHOICE over mouse)
    - ``clipboard``  — read / write system clipboard
    - ``ocr``        — extract text via pytesseract / Vision / WinRT
    - ``learn``      — record and replay computer tasks
    - ``audit``      — show the session audit log inside any MCP/agent session
    - ``script``     — shell / AppleScript / JXA / PowerShell (prefer over GUI)
    - ``browser``    — drive Chrome/Edge/Brave via DevTools (local-only)
    - ``fleet``      — run one tool call across many paired peers in parallel
    - ``memory``     — search the local screen-memory history (read-only recall)
    - ``memory_manage`` — pause / deny-list / config / delete screen memory
    - ``reward``     — verifiable task rewards, goal states, episode bookkeeping
    - ``diagnose``   — where a session stalled, and why
    """
    from opendesk.tools.screenshot import ScreenshotTool
    from opendesk.tools.mouse import MouseTool
    from opendesk.tools.keyboard import KeyboardTool
    from opendesk.tools.app import AppTool
    from opendesk.tools.ui import UITool
    from opendesk.tools.clipboard import ClipboardTool
    from opendesk.tools.ocr import OCRTool
    from opendesk.tools.automation import LearnTool, ScheduleTool
    from opendesk.tools.audit import AuditTool
    from opendesk.tools.script import ScriptTool
    from opendesk.tools.browser import BrowserTool
    from opendesk.tools.fleet import FleetTool
    from opendesk.tools.memory import MemoryManageTool, MemoryTool
    from opendesk.tools.reward import RewardTool
    from opendesk.tools.diagnose import DiagnoseTool

    registry = ToolRegistry()
    for tool_cls in (
        ScreenshotTool,
        MouseTool,
        KeyboardTool,
        AppTool,
        UITool,
        ClipboardTool,
        OCRTool,
        LearnTool,
        ScheduleTool,
        AuditTool,
        MemoryTool,
        ScriptTool,
        BrowserTool,
        FleetTool,
        MemoryManageTool,
        RewardTool,
        DiagnoseTool,
    ):
        registry.register(tool_cls())

    return registry


def create_minimal_registry() -> ToolRegistry:
    """Like :func:`create_registry` but without heavy optional tools (OCR).

    Suitable for environments where pytesseract / Tesseract are not installed.
    """
    from opendesk.tools.screenshot import ScreenshotTool
    from opendesk.tools.mouse import MouseTool
    from opendesk.tools.keyboard import KeyboardTool
    from opendesk.tools.app import AppTool
    from opendesk.tools.ui import UITool
    from opendesk.tools.clipboard import ClipboardTool

    registry = ToolRegistry()
    for tool_cls in (ScreenshotTool, MouseTool, KeyboardTool, AppTool, UITool, ClipboardTool):
        registry.register(tool_cls())
    return registry
