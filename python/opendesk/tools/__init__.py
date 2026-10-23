"""opendesk.tools — all built-in computer use tools."""

from opendesk.tools.app import AppTool
from opendesk.tools.audit import AuditTool
from opendesk.tools.browser import BrowserTool
from opendesk.tools.clipboard import ClipboardTool
from opendesk.tools.fleet import FleetTool
from opendesk.tools.keyboard import KeyboardTool
from opendesk.tools.memory import MemoryManageTool, MemoryTool
from opendesk.tools.mouse import MouseTool
from opendesk.tools.ocr import OCRTool
from opendesk.tools.screenshot import ScreenshotTool
from opendesk.tools.script import ScriptTool
from opendesk.tools.diagnose import DiagnoseTool
from opendesk.tools.reward import RewardTool
from opendesk.tools.ui import UITool

__all__ = [
    "AppTool",
    "AuditTool",
    "BrowserTool",
    "ClipboardTool",
    "DiagnoseTool",
    "FleetTool",
    "KeyboardTool",
    "MemoryManageTool",
    "MemoryTool",
    "MouseTool",
    "OCRTool",
    "RewardTool",
    "ScreenshotTool",
    "ScriptTool",
    "UITool",
]
