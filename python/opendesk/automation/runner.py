"""Execute a scheduled task — replay a procedure or run a natural language task."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def run_task(task: str, project_dir: Path) -> str:
    """Execute a task string and return a status message.

    If task starts with 'replay <name>', runs the compiled program for that
    task deterministically (no LLM, no API key).  Only when there is no
    compiled program, or it stops at a step it cannot complete, does it fall
    back to an LLM replaying the natural-language procedure.

    Otherwise, sends the task as a natural language instruction to Claude —
    via the Anthropic SDK when ANTHROPIC_API_KEY is set, else via headless
    Claude Code (``claude -p``, subscription login) when it is installed.
    """
    task = task.strip()

    if task.lower().startswith("replay "):
        name = task[len("replay "):].strip()
        return await _run_replay(name, project_dir)
    else:
        return await _run_natural_language(task, project_dir)


def _replay_context(name: str) -> Any:
    """ToolContext for compiled replays (tests patch this to inject a fake Computer)."""
    from opendesk.tools.base import ToolContext
    return ToolContext(session_id=f"scheduler-{name}")


async def _run_replay(name: str, project_dir: Path) -> str:
    """Run the compiled program for *name*; fall back to Claude + the NL procedure."""
    from opendesk.automation.program import format_self_heal, load_program, run_program
    from opendesk.automation.storage import load_procedure

    proc = load_procedure(project_dir, name)
    program = load_program(project_dir, name)
    heal_note = ""
    if program is not None:
        try:
            result = await run_program(program, _replay_context(name))
        except Exception as exc:
            result = None
            heal_note = f"Compiled replay raised an error: {exc}"
        if result is not None and result.ok:
            return result.summary()
        if result is not None:
            heal_note = format_self_heal(result, proc)
            logger.info("compiled replay of %s failed: %s", name, result.reason)

    if proc is None:
        if program is not None:
            return f"Error: compiled replay failed and no NL procedure exists for '{name}'. {heal_note[:300]}"
        return f"Error: no procedure found for '{name}'"

    steps = proc.get("steps", [])
    description = proc.get("description", "")
    procedure_text = proc.get("procedure", "")

    prompt = (
        f"Execute this learned task: {proc.get('task_name', name)}\n"
        f"Goal: {description}\n\n"
        f"Steps:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)) +
        f"\n\nProcedure:\n{procedure_text}\n\n"
        "Use the ui tool first, screenshot(marks=True) if needed, mouse as last resort. "
        "Adapt to the current environment."
    )
    if heal_note:
        prompt += (
            "\n\nA deterministic replay already ran and stopped part-way. Do NOT redo the "
            "completed steps; continue from the failed step.\n\n" + heal_note
        )

    status = await _run_with_claude(prompt, project_dir)
    if program is not None:
        return f"compiled replay failed, LLM fallback → {status}"
    return status


async def _run_natural_language(task: str, project_dir: Path) -> str:
    """Run a natural language task with the configured inference backend."""
    return await _run_with_claude(task, project_dir)


async def _run_with_claude(prompt: str, project_dir: Path | None = None) -> str:
    """Use the selected local backend, or Claude by default."""
    backend = os.environ.get("OPENDESK_AGENT_BACKEND", "cloud")
    if backend in {"local-mlx", "local-http"}:
        from opendesk.integrations.local import run_local_process
        try:
            result = await run_local_process(
                prompt, model=os.environ.get("OPENDESK_MODEL"),
                backend=backend.removeprefix("local-"), workdir=str(project_dir) if project_dir else None,
                vision=os.environ.get("OPENDESK_LOCAL_VISION") == "1",
                base_url=os.environ.get("OPENDESK_LOCAL_URL"),
                structured=os.environ.get("OPENDESK_LOCAL_STRUCTURED") == "1",
                planner_model=os.environ.get("OPENDESK_LOCAL_PLANNER"),
            )
            return ("Error: " if result.error else "ok (local): ") + (result.output or result.metadata.get("stderr", ""))[:1000]
        except Exception as exc:
            return f"Error: local inference failed: {exc}"
    if backend != "cloud":
        return f"Error: unknown OPENDESK_AGENT_BACKEND {backend!r}"
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        if shutil.which("claude"):
            return await _run_with_claude_code(prompt, project_dir)
        return (
            "Error: ANTHROPIC_API_KEY environment variable not set "
            "(and the 'claude' CLI is not installed for subscription-based runs)"
        )

    try:
        import anthropic
    except ImportError:
        return "Error: anthropic package not installed. Run: pip install anthropic"

    try:
        from opendesk.integrations.claude_code import ClaudeCodeAdapter
        from opendesk.registry import create_registry
        from opendesk.tools.base import allow_all_context

        registry = create_registry()
        adapter = ClaudeCodeAdapter(registry)
        client = anthropic.Anthropic(api_key=api_key)

        messages = [{"role": "user", "content": prompt}]

        result = await adapter.run_loop(
            client=client,
            model=os.environ.get("OPENDESK_MODEL", "claude-sonnet-4-6"),
            messages=messages,
            system=(
                "You are a desktop automation agent. Complete the task using the available tools. "
                "Use the ui tool first (click by element name). "
                "Use screenshot(marks=True) to see numbered elements if ui fails. "
                "Use mouse as last resort for pixel-level control."
            ),
        )
        return f"ok: {str(result)[:200]}"

    except Exception as e:
        return f"Error: {e}"


async def _run_with_claude_code(prompt: str, project_dir: Path | None) -> str:
    """Headless Claude Code fallback — uses the user's Claude subscription login."""
    try:
        from opendesk.eval.backends import run_claude_headless
        run = await run_claude_headless(prompt, cwd=str(project_dir) if project_dir else None)
    except Exception as e:
        return f"Error: {e}"
    if run.error:
        return f"Error: {run.error}"
    return f"ok (claude-code): {run.final_text[:200]}"
