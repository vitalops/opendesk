"""DiagnoseTool — state-transition diagnosis of the current session.

Answers "where did this episode actually go wrong?" instead of only "did it
succeed?".  See :mod:`opendesk.computer.diagnostics` for the analysis.
"""

from __future__ import annotations

import json
from typing import Literal, Optional

from pydantic import Field

from opendesk.tools.base import Tool, ToolContext, ToolResult


class DiagnoseTool(Tool):
    """Report where a session's actions clustered, looped, or stalled."""

    name = "diagnose"
    title = "Diagnose Session"
    annotations = {
        "readOnlyHint": True, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": False,
    }
    description = (
        "Diagnose a session by building a state-transition graph over its "
        "recorded actions.\n\n"
        "Screens that differ only trivially (a clock tick, a cursor) are merged "
        "into one *functional state*, so you can see structure rather than "
        "hundreds of near-identical screenshots.\n\n"
        "  action='report' — human-readable diagnosis (default)\n"
        "  action='json'   — the same analysis as structured JSON, for tooling\n"
        "  action='steps'  — per-step effect table (did each action change the UI?)\n\n"
        "Reports bottlenecks (states where errors concentrate), inertia "
        "(actions that changed nothing), loops, and dead ends. Use it after a "
        "failure to decide what to fix, or before retrying to avoid repeating a "
        "stalled pattern."
    )

    class Params(Tool.Params):
        action: Literal["report", "json", "steps"] = Field(
            default="report", description="Output format."
        )
        session_id: Optional[str] = Field(
            default=None, description="Session to diagnose. Defaults to the current one."
        )
        tolerance: int = Field(
            default=4,
            ge=0,
            le=64,
            description=(
                "Fingerprint distance under which two screens count as the same "
                "functional state. Higher = more aggressive merging."
            ),
        )
        max_items: int = Field(
            default=5, ge=1, le=50,
            description="How many entries to show per section in action='report'.",
        )

    async def execute(self, ctx: ToolContext, params: "DiagnoseTool.Params") -> ToolResult:
        from opendesk.computer.diagnostics import diagnose
        from opendesk.computer.sandbox import get_sandbox

        session_id = params.session_id or ctx.session_id
        sandbox = get_sandbox(session_id)
        log = sandbox.export_audit_log()

        if not log:
            return ToolResult(
                title="Diagnosis",
                output=f"No actions recorded for session {session_id!r} — nothing to diagnose.",
            )

        report = diagnose(log, tolerance=params.tolerance)

        if not report.nodes:
            return ToolResult(
                title="Diagnosis",
                output=(
                    f"Recorded {len(log)} action(s) for session {session_id!r}, but none "
                    "carry a screen fingerprint, so no state graph could be built.\n"
                    "Take a screenshot before acting — actions are tagged with the "
                    "screen they were issued against."
                ),
            )

        if params.action == "json":
            return ToolResult(
                title="Diagnosis (JSON)",
                output=json.dumps(report.as_dict(), indent=2, ensure_ascii=False),
                metadata=report.as_dict()["metrics"],
            )

        if params.action == "steps":
            lines = [
                f"Per-step effect — session {session_id!r} "
                f"({report.step_count} steps, {report.state_count} states)\n"
            ]
            for s in report.steps:
                mark = {"changed": "→", "same": "=", "none": "·"}[s["effect"]]
                err = "  ERROR" if s["error"] else ""
                lines.append(
                    f"  [{s['step']:>3}] {s['state']:<4} {mark} "
                    f"{s['action']:<22} {s['effect']}{err}"
                )
            lines.append(
                "\n→ = changed state   = = no change   · = last step / unknown"
            )
            return ToolResult(
                title=f"Step effects ({report.step_count})",
                output="\n".join(lines),
                metadata=report.as_dict()["metrics"],
            )

        await self._audit(ctx, session_id, report)
        return ToolResult(
            title="Diagnosis",
            output=report.summary_text(max_items=params.max_items),
            metadata=report.as_dict()["metrics"],
        )

    @staticmethod
    async def _audit(ctx, session_id: str, report) -> None:
        try:
            from opendesk.computer.sandbox import ActionType, get_sandbox

            await get_sandbox(ctx.session_id).record_action(
                ActionType.DIAGNOSE,
                params={"session_id": session_id},
                result=f"{report.state_count} states, {report.error_count} errors",
            )
        except Exception:
            pass
