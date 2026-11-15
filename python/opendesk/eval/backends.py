"""Eval backends — how an instruction is handed to an agent.

=============================  ==================================================
``claude-code`` (default)      headless ``claude -p`` with OpenDesk as its only
                               MCP server; uses the Claude Code login
                               (subscription) — no API key needed.
``anthropic-api``              Messages API + OpenDesk tools in-process
                               (``ANTHROPIC_API_KEY`` or an ``ant`` profile).
``anthropic-native-computer``  Messages API + Anthropic's native computer-use
                               tool — the A/B control arm.
``program``                    deterministic compiled ``learn`` program (used
                               automatically for learn-regression tasks).
=============================  ==================================================

Hold ``--model`` constant across arms when comparing them.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Optional

from opendesk.eval.agents import (
    EVAL_SYSTEM_PROMPT, NATIVE_TOOLSET, AgentRun, run_native_computer_loop, run_opendesk_loop,
)
from opendesk.eval.task import EvalTask

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TURNS = 40


class Backend:
    """Base class.  Subclasses implement :meth:`run` and :meth:`describe`."""

    name = "base"

    def __init__(self, *, model: str = DEFAULT_MODEL, max_turns: int = DEFAULT_MAX_TURNS) -> None:
        self.model = model
        self.max_turns = max_turns

    def turns_for(self, task: EvalTask) -> int:
        return task.max_turns or self.max_turns

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        raise NotImplementedError

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        """What :meth:`run` would do — used by ``--dry-run``.  Must not execute anything."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# claude-code
# ---------------------------------------------------------------------------


def mcp_server_command() -> list[str]:
    """argv that launches the OpenDesk MCP server from this Python environment."""
    try:
        from opendesk.cli import _find_mcp_binary
        return [_find_mcp_binary()]
    except Exception:
        return [sys.executable, "-m", "opendesk.integrations.mcp"]


def mcp_config(server_cmd: Optional[list[str]] = None) -> dict:
    cmd = server_cmd or mcp_server_command()
    return {"mcpServers": {"opendesk": {"command": cmd[0], "args": cmd[1:]}}}


def build_claude_code_command(
    instruction: str,
    *,
    mcp_config_path: str,
    model: Optional[str] = None,
    max_turns: Optional[int] = None,
    claude_bin: str = "claude",
    system_prompt: Optional[str] = EVAL_SYSTEM_PROMPT,
) -> list[str]:
    """Headless Claude Code invocation whose only tools are OpenDesk's MCP tools.

    ``--tools ""`` removes Claude Code's built-in tools (Bash, Read, Edit, …) and
    ``--strict-mcp-config`` ignores the user's other MCP servers, so the agent
    can only act through OpenDesk — same surface as the API arms.
    """
    argv = [
        claude_bin, "-p", instruction,
        "--mcp-config", mcp_config_path,
        "--strict-mcp-config",
        "--tools", "",
        "--allowedTools", "mcp__opendesk__*",
        "--output-format", "json",
        "--no-session-persistence",
    ]
    if max_turns:
        argv += ["--max-turns", str(max_turns)]
    if model:
        argv += ["--model", model]
    if system_prompt:
        argv += ["--append-system-prompt", system_prompt]
    return argv


def parse_claude_code_output(stdout: str) -> AgentRun:
    """Parse ``claude -p --output-format json`` output into an :class:`AgentRun`."""
    run = AgentRun()
    text = stdout.strip()
    data: Any = None
    try:
        data = json.loads(text)
    except Exception:
        # Some versions print a JSON array of events; take the final result object.
        for line in reversed(text.splitlines()):
            try:
                data = json.loads(line)
                break
            except Exception:
                continue
    if isinstance(data, list):
        data = next((d for d in reversed(data) if isinstance(d, dict) and d.get("type") == "result"), None)
    if not isinstance(data, dict):
        run.error = f"unparseable claude output: {text[:300]!r}"
        return run
    run.final_text = str(data.get("result") or "")
    run.turns = int(data.get("num_turns") or 0)
    run.cost_usd = data.get("total_cost_usd", data.get("cost_usd"))
    run.stop_reason = str(data.get("subtype") or "")
    usage = data.get("usage") or {}
    if usage:
        run.input_tokens = int(
            (usage.get("input_tokens") or 0)
            + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("cache_read_input_tokens") or 0)
        )
        run.output_tokens = int(usage.get("output_tokens") or 0)
    if data.get("is_error") and run.stop_reason != "error_max_turns":
        run.error = f"claude reported an error ({run.stop_reason}): {run.final_text[:200]}"
    if data.get("duration_ms") is not None:
        run.extra["duration_ms"] = data.get("duration_ms")
    return run


class ClaudeCodeBackend(Backend):
    name = "claude-code"

    def __init__(
        self, *, claude_bin: str = "claude", system_prompt: Optional[str] = EVAL_SYSTEM_PROMPT, **kw: Any,
    ) -> None:
        super().__init__(**kw)
        self.claude_bin = claude_bin
        self.system_prompt = system_prompt

    def _argv(self, task: EvalTask, instruction: str, cfg_path: str) -> list[str]:
        return build_claude_code_command(
            instruction, mcp_config_path=cfg_path, model=self.model,
            max_turns=self.turns_for(task), claude_bin=self.claude_bin,
            system_prompt=self.system_prompt,
        )

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        return {
            "backend": self.name,
            "cwd": workdir,
            "mcp_config": mcp_config(),
            "command": self._argv(task, instruction, "<tmp>/opendesk-mcp.json"),
        }

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        if shutil.which(self.claude_bin) is None and not Path(self.claude_bin).exists():
            return AgentRun(error=f"'{self.claude_bin}' CLI not found on PATH")
        fd, cfg_path = tempfile.mkstemp(prefix="opendesk-mcp-", suffix=".json")
        with os.fdopen(fd, "w") as fh:
            json.dump(mcp_config(), fh)
        try:
            return await self._run_cli(self._argv(task, instruction, cfg_path), workdir, timeout)
        finally:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass

    async def _run_cli(self, argv: list[str], workdir: str, timeout: float) -> AgentRun:
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *argv, cwd=workdir, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return AgentRun(error=f"timeout after {timeout:.0f}s", stop_reason="timeout",
                            wall_time_s=time.monotonic() - t0)
        run = parse_claude_code_output(out.decode("utf-8", "replace"))
        run.wall_time_s = time.monotonic() - t0
        if proc.returncode not in (0, None) and run.error is None and not run.final_text:
            run.error = f"claude exited {proc.returncode}: {err.decode('utf-8', 'replace')[-300:]}"
        return run


# ---------------------------------------------------------------------------
# Messages API arms
# ---------------------------------------------------------------------------


def _anthropic_client() -> Any:
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("the 'anthropic' package is required: pip install anthropic") from exc
    # Credentials: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile.
    return anthropic.AsyncAnthropic()


class AnthropicAPIBackend(Backend):
    name = "anthropic-api"

    def __init__(self, *, client_factory: Callable[[], Any] = _anthropic_client, **kw: Any) -> None:
        super().__init__(**kw)
        self._client_factory = client_factory

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        from opendesk.registry import create_registry
        return {
            "backend": self.name,
            "request": {
                "endpoint": "POST /v1/messages (loop until stop_reason != tool_use)",
                "model": self.model,
                "max_turns": self.turns_for(task),
                "system": EVAL_SYSTEM_PROMPT,
                "tools": create_registry().names(),
                "auth": "ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ant profile",
            },
            "instruction": instruction,
        }

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        try:
            client = self._client_factory()
        except Exception as exc:
            return AgentRun(error=str(exc))
        try:
            return await asyncio.wait_for(
                run_opendesk_loop(
                    client, model=self.model, instruction=instruction,
                    max_turns=self.turns_for(task), session_id=f"eval-{task.id}",
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return AgentRun(error=f"timeout after {timeout:.0f}s", stop_reason="timeout")


class AnthropicNativeComputerBackend(AnthropicAPIBackend):
    name = "anthropic-native-computer"

    def __init__(self, *, tool_version: str = NATIVE_TOOLSET, **kw: Any) -> None:
        super().__init__(**kw)
        self.tool_version = tool_version

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        tool = (
            {"type": NATIVE_TOOLSET} if self.tool_version == NATIVE_TOOLSET
            else {"type": self.tool_version, "name": "computer",
                  "display_width_px": "<primary display>", "display_height_px": "<primary display>"}
        )
        return {
            "backend": self.name,
            "request": {
                "endpoint": "POST /v1/messages (loop until stop_reason != tool_use)",
                "model": self.model,
                "max_turns": self.turns_for(task),
                "system": EVAL_SYSTEM_PROMPT,
                "tools": [tool],
                "executor": "opendesk LocalComputer (same input backend as the OpenDesk arms)",
            },
            "instruction": instruction,
        }

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        try:
            client = self._client_factory()
        except Exception as exc:
            return AgentRun(error=str(exc))
        try:
            return await asyncio.wait_for(
                run_native_computer_loop(
                    client, model=self.model, instruction=instruction,
                    max_turns=self.turns_for(task), tool_version=self.tool_version,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return AgentRun(error=f"timeout after {timeout:.0f}s", stop_reason="timeout")


# ---------------------------------------------------------------------------
# Compiled learn programs (learn-regression)
# ---------------------------------------------------------------------------


class ProgramBackend(Backend):
    """Runs a task's compiled ``learn`` program — deterministic, no LLM."""

    name = "program"

    def __init__(self, *, computer_factory: Optional[Callable[[], Any]] = None, **kw: Any) -> None:
        super().__init__(**kw)
        self._computer_factory = computer_factory

    def _project(self, task: EvalTask, workdir: str) -> Path:
        return Path(task.project) if task.project else Path(workdir)

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        return {
            "backend": self.name,
            "program": task.program,
            "project": str(self._project(task, workdir)),
            "action": f"learn(action='run', task_name='{task.program}') — deterministic, no LLM",
            "inline_program_steps": len((task.program_json or {}).get("steps", [])) or None,
        }

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        from opendesk.automation.program import Program, load_program, run_program, save_program
        from opendesk.tools.base import ToolContext

        project = self._project(task, workdir)
        if task.program_json:
            data = dict(task.program_json)
            data["name"] = task.program
            save_program(project, Program.model_validate(data))
        prog = load_program(project, task.program or "")
        if prog is None:
            return AgentRun(error=f"no compiled program {task.program!r} in {project}")
        ctx = ToolContext(session_id=f"eval-{task.id}")
        if self._computer_factory is not None:
            ctx.computer = self._computer_factory()
        t0 = time.monotonic()
        try:
            res = await asyncio.wait_for(run_program(prog, ctx), timeout=timeout)
        except asyncio.TimeoutError:
            return AgentRun(error=f"timeout after {timeout:.0f}s", stop_reason="timeout",
                            wall_time_s=time.monotonic() - t0)
        run = AgentRun(
            final_text=res.summary(), turns=0, input_tokens=0, output_tokens=0, cost_usd=0.0,
            stop_reason=res.status, wall_time_s=time.monotonic() - t0,
            extra={"steps": len(res.outcomes)},
        )
        if not res.ok:
            run.error = res.summary()
        return run


# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class FakeBackend(Backend):
    """Scripted backend for tests: ``script(task, instruction, workdir) -> AgentRun``."""

    name = "fake"

    def __init__(self, script: Optional[Callable[..., Any]] = None, **kw: Any) -> None:
        super().__init__(**kw)
        self.script = script
        self.calls: list[tuple[str, str, str]] = []

    def describe(self, task: EvalTask, instruction: str, *, workdir: str) -> dict:
        return {"backend": self.name, "instruction": instruction}

    async def run(self, task: EvalTask, instruction: str, *, workdir: str, timeout: float) -> AgentRun:
        self.calls.append((task.id, instruction, workdir))
        if self.script is None:
            return AgentRun(final_text="done", turns=1)
        out = self.script(task, instruction, workdir)
        if asyncio.iscoroutine(out):
            out = await out
        return out


class LocalModelBackend(Backend):
    """Full registry, local inference; the harness still checks real task outcomes."""
    name = "local-mlx"
    inference = "mlx"

    def local_model(self):
        from opendesk.integrations.local_backends import DEFAULT_MODEL as LOCAL_MODEL, DEFAULT_VISION_MODEL
        if self.model == DEFAULT_MODEL and self.inference == "mlx":
            return DEFAULT_VISION_MODEL if os.environ.get("OPENDESK_LOCAL_VISION") == "1" else LOCAL_MODEL
        return self.model

    def describe(self, task, instruction, *, workdir):
        return {"backend": self.name, "model": self.local_model(), "instruction": instruction,
                "workdir": workdir, "max_steps": min(30, self.turns_for(task))}

    async def run(self, task, instruction, *, workdir, timeout):
        from opendesk.integrations.local import run_local_process
        start = time.monotonic()
        model = self.local_model()
        if self.inference == "http" and self.model == DEFAULT_MODEL:
            return AgentRun(error="Specify --model for a local HTTP evaluation")
        try:
            result = await run_local_process(
                instruction, model=model, backend=self.inference, workdir=workdir,
                timeout=timeout, max_steps=min(30, self.turns_for(task)),
                vision=os.environ.get("OPENDESK_LOCAL_VISION") == "1",
                base_url=os.environ.get("OPENDESK_LOCAL_URL"),
                structured=os.environ.get("OPENDESK_LOCAL_STRUCTURED") == "1",
                planner_model=os.environ.get("OPENDESK_LOCAL_PLANNER"))
            return AgentRun(final_text=result.output, error=(result.output or result.metadata.get("stderr") or "Local task failed") if result.error else None,
                            turns=result.metadata.get("steps", 0),
                            wall_time_s=time.monotonic() - start, extra=result.metadata)
        except Exception as exc:
            return AgentRun(error=f"Local model failed: {type(exc).__name__}: {exc}",
                            wall_time_s=time.monotonic() - start)


class LocalHTTPBackend(LocalModelBackend):
    name = "local-http"
    inference = "http"


BACKENDS = {
    "local-mlx": LocalModelBackend,
    "local-http": LocalHTTPBackend,
    "claude-code": ClaudeCodeBackend,
    "anthropic-api": AnthropicAPIBackend,
    "anthropic-native-computer": AnthropicNativeComputerBackend,
}


def get_backend(name: str, **kw: Any) -> Backend:
    try:
        cls = BACKENDS[name]
    except KeyError:
        raise ValueError(f"unknown backend {name!r}; choose from {', '.join(BACKENDS)}") from None
    return cls(**kw)


async def run_claude_headless(prompt: str, *, cwd: Optional[str] = None, model: Optional[str] = None,
                              max_turns: int = DEFAULT_MAX_TURNS, timeout: float = 1800) -> AgentRun:
    """Run one prompt through headless Claude Code with OpenDesk tools (scheduler fallback)."""
    task = EvalTask(id="scheduled", instruction=prompt, max_turns=max_turns)
    backend = ClaudeCodeBackend(
        model=model or os.environ.get("OPENDESK_MODEL") or "",  # "" → Claude Code's default
        system_prompt=(
            "You are a desktop automation agent. Complete the task using the opendesk tools. "
            "Use the ui tool first (click by element name), screenshot(marks=True) if ui fails, "
            "mouse as a last resort."
        ),
    )
    return await backend.run(task, prompt, workdir=cwd or os.getcwd(), timeout=timeout)
