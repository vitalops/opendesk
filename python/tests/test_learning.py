"""Tests for the learning layer — verifiable rewards, process signals and
trajectories (the environment side of RL)."""

from __future__ import annotations

import asyncio
import io
import json

import pytest

from opendesk.computer import diagnostics
from opendesk.computer.sandbox import ActionType, clear_sandbox, get_sandbox
from opendesk.learning import rewards, goal_state, process, trajectories
from opendesk.tools.base import ToolContext
from opendesk.tools.reward import RewardTool
from tests._fakes import FakeComputer


def make_png(seed: int = 0, size: tuple[int, int] = (64, 48)) -> bytes:
    from PIL import Image

    img = Image.new("RGB", size)
    w, h = size
    img.putdata([
        ((x * 7 + y * 13 + seed * 97) % 256,
         (x * 3 + seed * 11) % 256,
         (y * 5 + seed * 29) % 256)
        for y in range(h) for x in range(w)
    ])
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def ctx_for(session_id: str) -> ToolContext:
    return ToolContext(session_id=session_id, computer=FakeComputer())


class ShellComputer(FakeComputer):
    """A fake whose ``shell`` really runs the command.

    The point is the *path*, not the fake: a reward check must go through
    ``ctx.computer`` so the same risk tiers and approval apply as for a step.
    Recording every command makes a check that bypassed it visible.
    """

    def __init__(self) -> None:
        super().__init__()
        self.shells: list[str] = []

    async def shell(self, command, *, timeout=None, cwd=None, env=None):
        from opendesk.computer.types import CompletedCommand

        self.shells.append(command)
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise
        return CompletedCommand(returncode=proc.returncode, stdout=out, stderr=err)


def shell_ctx(session_id: str) -> ToolContext:
    return ToolContext(session_id=session_id, computer=ShellComputer())


def entry(action: str, screen: str | None, *, error: bool = False, ts: float = 0.0) -> dict:
    return {"action": action, "screen": screen, "error": error, "timestamp": ts,
            "params": {}, "result": None}


def ui_entry(action: str, digest: str | None, *, error: bool = False,
             screen: str | None = None, ts: float = 0.0) -> dict:
    """An audit entry carrying an accessibility content digest."""
    return {"action": action, "screen": screen, "ui": digest, "error": error,
            "timestamp": ts, "params": {}, "result": None}


class TreeComputer(FakeComputer):
    """A fake whose accessibility tree the test can set."""

    def __init__(self, tree) -> None:
        super().__init__()
        self._tree = tree

    async def ui_tree(self, *, window_id=None, app=None, max_depth=8):
        return self._tree


def ui_tree(*children, window_name: str = "Invoices"):
    from opendesk.computer.types import UIElement

    return UIElement(role="window", name=window_name, children=list(children))


def ui_node(role: str, name: str = "", *, value=None, children=None):
    from opendesk.computer.types import UIElement

    return UIElement(role=role, name=name, value=value, children=list(children or []))


FP0 = "0000000000000000"
FP1 = "000000000000ffff"
FP2 = "ffffffffffff0000"


# ---------------------------------------------------------------------------
# Reward spec parsing
# ---------------------------------------------------------------------------


class TestSpecParsing:
    def test_parses_task_mode_and_checks(self):
        task, mode, checks = rewards.parse_spec({
            "task": "do it", "mode": "weighted",
            "checks": [{"kind": "file_exists", "path": "~/x"}],
        })
        assert task == "do it" and mode == "weighted"
        assert len(checks) == 1 and checks[0].kind == "file_exists"

    def test_defaults(self):
        task, mode, checks = rewards.parse_spec({"checks": [{"kind": "file_exists", "path": "/x"}]})
        assert task == "unnamed task" and mode == "all"
        assert checks[0].required is True and checks[0].weight == 1.0

    def test_rejects_unknown_kind(self):
        with pytest.raises(ValueError, match="unknown check kind"):
            rewards.parse_spec({"checks": [{"kind": "teleport"}]})

    def test_rejects_missing_kind(self):
        with pytest.raises(ValueError, match="missing 'kind'"):
            rewards.parse_spec({"checks": [{"path": "/x"}]})

    def test_rejects_bad_mode(self):
        with pytest.raises(ValueError, match="mode must be"):
            rewards.parse_spec({"mode": "sometimes", "checks": [{"kind": "file_exists", "path": "/x"}]})

    def test_rejects_empty_checks(self):
        with pytest.raises(ValueError, match="non-empty"):
            rewards.parse_spec({"checks": []})

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError):
            rewards.parse_spec("nope")

    def test_expands_home(self):
        _, _, checks = rewards.parse_spec({"checks": [{"kind": "file_exists", "path": "~/x"}]})
        assert not checks[0].args["path"].startswith("~")


# ---------------------------------------------------------------------------
# Reward evaluation
# ---------------------------------------------------------------------------


class TestRewardEvaluation:
    @pytest.mark.asyncio
    async def test_file_checks(self, tmp_path):
        target = tmp_path / "report.txt"
        target.write_text("total: 42\nlines: 3\n", encoding="utf-8")

        spec = {"task": "write report", "checks": [
            {"kind": "file_exists", "path": str(target)},
            {"kind": "file_contains", "path": str(target), "text": "total: 42"},
            {"kind": "file_contains", "path": str(target), "regex": r"^lines: \d+$"},
            {"kind": "file_absent", "path": str(tmp_path / "nope.txt")},
        ]}
        report = await rewards.evaluate(spec)
        assert report.passed
        assert report.reward == 1.0
        assert report.score == 1.0

    @pytest.mark.asyncio
    async def test_failing_check_blocks_binary_reward(self, tmp_path):
        target = tmp_path / "report.txt"
        target.write_text("hello", encoding="utf-8")
        spec = {"task": "t", "checks": [
            {"kind": "file_exists", "path": str(target)},
            {"kind": "file_contains", "path": str(target), "text": "absent-string"},
        ]}
        report = await rewards.evaluate(spec)
        assert not report.passed
        assert report.reward == 0.0
        assert report.score == 0.5          # dense signal still present
        assert len(report.failed()) == 1

    @pytest.mark.asyncio
    async def test_optional_check_does_not_affect_reward(self, tmp_path):
        (tmp_path / "a").write_text("x", encoding="utf-8")
        spec = {"task": "t", "checks": [
            {"kind": "file_exists", "path": str(tmp_path / "a")},
            {"kind": "file_exists", "path": str(tmp_path / "b"), "required": False},
        ]}
        report = await rewards.evaluate(spec)
        assert report.reward == 1.0
        assert len(report.required) == 1

    @pytest.mark.asyncio
    async def test_missing_file_gives_evidence(self, tmp_path):
        spec = {"task": "t", "checks": [{"kind": "file_exists", "path": str(tmp_path / "x")}]}
        report = await rewards.evaluate(spec)
        assert report.results[0].evidence["path"].endswith("x")

    @pytest.mark.asyncio
    async def test_mode_any(self, tmp_path):
        (tmp_path / "a").write_text("x", encoding="utf-8")
        spec = {"task": "t", "mode": "any", "checks": [
            {"kind": "file_exists", "path": str(tmp_path / "a")},
            {"kind": "file_exists", "path": str(tmp_path / "b")},
        ]}
        report = await rewards.evaluate(spec)
        assert report.passed and report.reward == 1.0

    @pytest.mark.asyncio
    async def test_mode_weighted_gives_dense_reward(self, tmp_path):
        (tmp_path / "a").write_text("x", encoding="utf-8")
        spec = {"task": "t", "mode": "weighted", "checks": [
            {"kind": "file_exists", "path": str(tmp_path / "a"), "weight": 3},
            {"kind": "file_exists", "path": str(tmp_path / "b"), "weight": 1},
        ]}
        report = await rewards.evaluate(spec)
        assert report.reward == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_shell_check_captures_exit_and_stdout(self):
        spec = {"task": "t", "checks": [
            {"kind": "shell", "command": "echo hi", "stdout_regex": "^hi$"},
        ]}
        ctx = shell_ctx("rw-shell-ok")
        report = await rewards.evaluate(spec, ctx=ctx)
        assert report.passed
        assert report.results[0].evidence["exit_code"] == 0
        # The command went through the computer, so the safety policy saw it.
        assert ctx.computer.shells == ["echo hi"]

    @pytest.mark.asyncio
    async def test_shell_check_fails_on_wrong_exit(self):
        spec = {"task": "t", "checks": [
            {"kind": "shell", "command": "exit 3", "expect_exit": 0},
        ]}
        report = await rewards.evaluate(spec, ctx=shell_ctx("rw-shell-exit"))
        assert not report.passed
        assert "exit code 3" in report.results[0].detail

    @pytest.mark.asyncio
    async def test_shell_timeout_is_reported(self):
        spec = {"task": "t", "checks": [
            {"kind": "shell", "command": "python -c \"import time; time.sleep(5)\"",
             "timeout": 0.4},
        ]}
        report = await rewards.evaluate(spec, ctx=shell_ctx("rw-shell-timeout"))
        assert not report.passed
        assert "timed out" in report.results[0].detail

    @pytest.mark.asyncio
    async def test_shell_check_refuses_without_a_computer(self):
        """A check must not fall back to spawning a process of its own."""
        spec = {"task": "t", "checks": [{"kind": "shell", "command": "echo hi"}]}
        report = await rewards.evaluate(spec)
        assert not report.passed
        assert "safety policy" in report.results[0].detail

    @pytest.mark.asyncio
    async def test_clipboard_check_reads_the_clipboard(self):
        from opendesk.computer import ClipboardContents, ClipboardEntry

        computer = FakeComputer()
        await computer.clipboard_write(
            ClipboardContents(entries=[ClipboardEntry.from_text("hello world")])
        )
        ctx = ToolContext(session_id="rw-clip", computer=computer)
        spec = {"task": "t", "checks": [{"kind": "clipboard_contains", "text": "world"}]}
        report = await rewards.evaluate(spec, ctx=ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_clipboard_check_fails_cleanly_when_absent(self):
        ctx = ctx_for("rw-clip-empty")
        spec = {"task": "t", "checks": [{"kind": "clipboard_contains", "text": "x"}]}
        report = await rewards.evaluate(spec, ctx=ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_ui_element_check_finds_button(self):
        ctx = ctx_for("rw-ui")
        spec = {"task": "t", "checks": [
            {"kind": "ui_element", "role": "button", "name_regex": "^Save$"},
        ]}
        report = await rewards.evaluate(spec, ctx=ctx)
        assert report.passed
        assert report.results[0].evidence["matches"][0]["name"] == "Save"

    @pytest.mark.asyncio
    async def test_ui_element_absent(self):
        ctx = ctx_for("rw-ui2")
        spec = {"task": "t", "checks": [
            {"kind": "ui_element", "name_regex": "Nonexistent", "present": False},
        ]}
        report = await rewards.evaluate(spec, ctx=ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_app_running(self):
        ctx = ctx_for("rw-app")
        spec = {"task": "t", "checks": [{"kind": "app_running", "name": "fake"}]}
        report = await rewards.evaluate(spec, ctx=ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_evaluation_error_is_contained(self):
        # A check missing its required argument should not explode the sweep.
        spec = {"task": "t", "checks": [{"kind": "file_contains", "path": "/x"}]}
        report = await rewards.evaluate(spec)
        assert not report.passed
        assert "needs 'text' or 'regex'" in report.results[0].detail

    @pytest.mark.asyncio
    async def test_category_breakdown(self, tmp_path):
        (tmp_path / "a").write_text("x", encoding="utf-8")
        spec = {"task": "t", "checks": [
            {"kind": "file_exists", "path": str(tmp_path / "a"), "category": "files"},
            {"kind": "file_exists", "path": str(tmp_path / "b"), "category": "files"},
            {"kind": "file_exists", "path": str(tmp_path / "a"), "category": "other"},
        ]}
        report = await rewards.evaluate(spec)
        cats = report.by_category()
        assert cats["files"]["score"] == 0.5
        assert cats["other"]["score"] == 1.0
        assert report.to_dict()["categories"]["files"]["total"] == 2

    @pytest.mark.asyncio
    async def test_summary_text_marks_pass_and_fail(self, tmp_path):
        spec = {"task": "t", "checks": [
            {"kind": "file_exists", "path": str(tmp_path / "missing")},
        ]}
        report = await rewards.evaluate(spec)
        text = report.summary_text()
        assert "[FAIL]" in text and "[ ]" in text


# ---------------------------------------------------------------------------
# Process rewards
# ---------------------------------------------------------------------------


class TestProcessRewards:
    def test_metrics_from_a_mixed_trajectory(self):
        report = process.score_process([
            entry("ui_action", FP0),          # changed
            entry("ui_action", FP1),          # no effect
            entry("ui_action", FP1),          # changed
            entry("ui_action", FP2, error=True),  # error (last)
        ])
        assert report.total_steps == 4
        assert report.effective_steps == 2
        assert report.no_effect_steps == 1
        assert report.error_steps == 1
        # The last step has no successor, so its effect is unknown and it is
        # left out of the ratio: 2 progressed of 3 judgeable steps.
        assert report.observable_steps == 3
        assert report.efficiency == pytest.approx(2 / 3)

    def test_bookkeeping_calls_are_not_rewarded(self):
        # A screenshot between two clicks is an observation, not a step to be
        # credited or penalised.
        report = process.score_process([
            entry("ui_action", FP0),
            entry("screenshot", FP1),
            entry("ui_action", FP2),
        ])
        assert report.total_steps == 2
        assert report.passive_skipped == 1
        assert [s.action for s in report.steps] == ["ui_action", "ui_action"]

    def test_step_rewards_carry_their_audit_index(self):
        report = process.score_process([
            entry("screenshot", FP0),
            entry("ui_action", FP1),
            entry("ui_action", FP2),
        ])
        assert [s.index for s in report.steps] == [1, 2]

    def test_returns_follow_the_discount_identity(self):
        report = process.score_process([
            entry("ui_action", FP0),
            entry("ui_action", FP1),
            entry("ui_action", FP2),
        ], gamma=0.9)
        g = 0.9
        for i in range(len(report.steps) - 1):
            expected = report.steps[i].reward + g * report.returns[i + 1]
            assert report.returns[i] == pytest.approx(expected)

    def test_terminal_bonus_lands_on_the_last_step(self):
        base = process.score_process([entry("ui_action", FP0)], outcome_reward=0.0)
        win = process.score_process([entry("ui_action", FP0)], outcome_reward=1.0)
        assert win.steps[-1].reward > base.steps[-1].reward
        assert "success" in win.steps[-1].reason

    def test_no_effect_and_errors_are_penalised(self):
        report = process.score_process([
            entry("ui_action", FP0),
            entry("ui_action", FP1),
            entry("ui_action", FP1),               # no effect
            entry("ui_action", FP1, error=True),    # error
        ])
        rewards_by_step = [s.reward for s in report.steps]
        assert rewards_by_step[1] > rewards_by_step[2]
        assert rewards_by_step[1] > rewards_by_step[3]

    def test_loop_steps_are_flagged(self):
        report = process.score_process([
            entry("ui_action", FP0),
            entry("ui_action", FP1),
            entry("ui_action", FP0),
            entry("ui_action", FP1),
        ])
        assert report.loop_steps > 0

    def test_progress_out_of_a_stall_is_not_penalised_as_a_loop(self):
        """A step that finally moves the interface is progress, not a loop.

        Retrying an action that did nothing is a stall; the same action then
        succeeding on that state is the repair.  Loop detection must key on the
        transition, or it charges the repair as a repeat — which is what
        ``-loop_penalty`` did when the key was only (state, action).
        """
        report = process.score_process([
            entry("ui_action", FP0),   # S0 -> S0  no effect
            entry("ui_action", FP0),   # S0 -> S0  no effect, stall repeats
            entry("ui_action", FP0),   # S0 -> S1  finally makes progress
            entry("ui_action", FP1),   # S1 -> end
        ])
        first, second, third, _last = report.steps
        assert first.in_loop is False
        assert second.in_loop is True          # the stall really did repeat
        assert third.in_loop is False          # the repair must not be charged
        assert report.loop_steps == 1
        # progress (1.0) plus step_cost (-0.1), with no spurious loop penalty.
        assert third.reward == pytest.approx(0.9)

    def test_empty_input(self):
        report = process.score_process([])
        assert report.total_steps == 0
        assert report.efficiency == 0.0
        assert report.returns == []

    # -- efficiency must not invert --------------------------------------

    def test_single_step_episode_is_not_reported_as_wasted(self):
        """The most direct possible attempt must not score 0% efficiency.

        The only step has no successor, so its effect is unknown.  Counting it
        as a step that failed to progress read the direct attempt as *worse*
        than a wandering one.
        """
        report = process.score_process([entry("ui_action", FP0)])
        assert report.total_steps == 1
        assert report.observable_steps == 0
        assert report.effective_steps == 0
        assert report.efficiency == 1.0

    def test_direct_attempt_beats_a_wandering_one(self):
        """Efficiency must rank a short successful run above a long detour."""
        direct = process.score_process([entry("ui_action", FP0)])
        detour = process.score_process([
            entry("ui_action", FP0),   # no effect
            entry("ui_action", FP0),   # no effect
            entry("ui_action", FP1),   # progress
            entry("ui_action", FP2),   # progress
        ])
        assert direct.efficiency > detour.efficiency

    def test_all_no_effect_steps_read_as_zero(self):
        report = process.score_process([
            entry("ui_action", FP0),
            entry("ui_action", FP0),
            entry("ui_action", FP0),
        ])
        assert report.effective_steps == 0
        assert report.efficiency == 0.0

    def test_observable_steps_is_serialised(self):
        d = process.score_process([entry("ui_action", FP0)]).to_dict()
        assert d["metrics"]["observable_steps"] == 0
        assert d["metrics"]["efficiency"] == 1.0

    # -- screen-free streams (CLI-first / headless hosts) ---------------

    def test_screen_free_stream_still_yields_step_rewards(self):
        """A CLI-only session must not lose its dense signal.

        Without this, every step is skipped for lack of a fingerprint and the
        report comes back empty — the exact case the hybrid `system` tool is
        meant to encourage.
        """
        report = process.score_process([
            entry("file_write", None),
            entry("file_mkdir", None),
        ], outcome_reward=1.0)
        assert report.total_steps == 2
        assert report.returns != []
        assert report.steps[0].effect == "changed"   # a mutation is progress
        assert report.steps[0].reward > 0
        assert report.steps[-1].reward > report.steps[0].reward  # success bonus

    def test_repeated_identical_command_is_a_no_effect_step(self):
        """Running the same command twice is the CLI analogue of a stalled screen."""
        a = {"tool": "system", "params": {"action": "shell", "command": "echo hi"}}
        b = {"tool": "system", "params": {"action": "shell", "command": "echo bye"}}
        report = process.score_process([
            {"action": "shell", "screen": None, "error": False, "params": a,
             "timestamp": 0.0, "result": None},
            {"action": "shell", "screen": None, "error": False, "params": a,
             "timestamp": 1.0, "result": None},   # verbatim repeat -> no effect
            {"action": "shell", "screen": None, "error": False, "params": b,
             "timestamp": 2.0, "result": None},
        ])
        assert report.steps[0].effect == "changed"
        assert report.steps[1].effect == "same"
        assert report.steps[1].no_effect is True
        assert report.steps[0].reward > report.steps[1].reward

    def test_retrying_a_failed_command_counts_as_progress(self):
        """A retry after failure is a repair, not a repeat."""
        same = {"tool": "system", "params": {"action": "shell", "command": "flaky"}}
        report = process.score_process([
            {"action": "shell", "screen": None, "error": True, "params": same,
             "timestamp": 0.0, "result": None},
            {"action": "shell", "screen": None, "error": False, "params": same,
             "timestamp": 1.0, "result": None},
            {"action": "shell", "screen": None, "error": False, "params": same,
             "timestamp": 2.0, "result": None},
        ], outcome_reward=1.0)
        # The first retry is the repair; the one after it is the stall.
        assert report.steps[1].no_effect is False
        assert report.steps[1].reward > 0

    def test_observation_actions_stay_passive_without_screens(self):
        report = process.score_process([
            entry("screenshot", None),
            entry("ui_action", None),
            entry("clipboard_read", None),
        ])
        assert report.total_steps == 1
        assert report.passive_skipped == 2
        assert report.steps[0].action == "ui_action"

    def test_screen_path_is_preferred_when_fingerprints_exist(self):
        """The fallback must not engage when there is a real state graph."""
        report = process.score_process([
            entry("ui_action", FP0),
            entry("ui_action", FP0),   # no visible change
        ])
        assert report.steps[0].effect == "same"
        assert report.steps[0].no_effect is True

    # -- absolute step indices ------------------------------------------

    def test_index_offset_makes_indices_absolute(self):
        """Scoring a slice must still report positions in the whole log.

        `build_trajectory` matches process rewards to steps by absolute audit
        position.  A slice-relative index therefore attached every reward to the
        wrong step for any episode that was not first in its session — which is
        every attempt in a best-of-N sweep.
        """
        entries = [
            entry("episode_begin", None),          # 0, bookkeeping
            entry("ui_action", FP0),               # 1
            entry("ui_action", FP1),               # 2
        ]
        window = entries[1:]
        report = process.score_process(window, index_offset=1)
        assert [s.index for s in report.steps] == [1, 2]

    def test_index_offset_applies_without_screens_too(self):
        report = process.score_process(
            [entry("file_write", None), entry("file_write", None)],
            index_offset=7,
        )
        assert [s.index for s in report.steps] == [7, 8]

    def test_weights_can_be_overridden(self):
        report = process.score_process(
            [entry("ui_action", FP0), entry("ui_action", FP1)],
            weights={"progress_reward": 100.0},
        )
        assert report.weights["progress_reward"] == 100.0

    def test_serialises(self):
        report = process.score_process([entry("ui_action", FP0), entry("ui_action", FP1)])
        d = report.to_dict()
        assert d["metrics"]["total_steps"] == 2
        assert len(d["steps"]) == 2 and len(d["returns"]) == 2
        assert "Process rewards" in report.summary_text()


# ---------------------------------------------------------------------------
# Goal-state anchoring
# ---------------------------------------------------------------------------


class TestGoalState:
    def test_flatten_anchors_from_objects(self):
        tree = {
            "role": "window", "name": "root", "children": [
                {"role": "button", "name": "Save",
                 "bounds": {"x": 10, "y": 20, "width": 80, "height": 30}},
                {"role": "decorative", "name": "spacer",
                 "bounds": {"x": 0, "y": 0, "width": 5, "height": 5}},
                {"role": "button", "name": "",  # unlabelled — skipped
                 "bounds": {"x": 0, "y": 0, "width": 40, "height": 10}},
            ],
        }
        anchors = goal_state.flatten_anchors(tree, 200, 100)
        assert [a.name for a in anchors] == ["Save"]
        assert anchors[0].cx == pytest.approx(50 / 200)
        assert anchors[0].key == "button|save"

    def test_match_anchors_recall(self):
        goal = [goal_state.Anchor("button", "Save", 0.5, 0.5),
                goal_state.Anchor("button", "Cancel", 0.7, 0.5)]
        current = [goal_state.Anchor("button", "Save", 0.5, 0.5)]
        recall, matched, missing = goal_state._match_anchors(goal, current)
        assert recall == pytest.approx(0.5)
        assert [m["name"] for m in matched] == ["Save"]
        assert [m["name"] for m in missing] == ["Cancel"]

    @pytest.mark.asyncio
    async def test_capture_and_score_reached(self, monkeypatch):
        png = make_png(5)
        monkeypatch.setattr(
            "opendesk.computer.capture.capture_screen",
            lambda region=None: (png, 100, 100),
        )
        session = "goal-reached"
        goal_state.clear_goals(session)
        ctx = ctx_for(session)

        goal = await goal_state.capture_goal("done", ctx, session_id=session)
        assert goal.fingerprint
        assert [a.name for a in goal.anchors] == ["Save"]

        score = await goal_state.score_goal("done", ctx, session_id=session,
                                            current_png=png)
        assert score.reached
        assert score.visual_similarity == pytest.approx(1.0)
        assert score.anchor_recall == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_score_falls_short_on_a_different_screen(self, monkeypatch):
        monkeypatch.setattr(
            "opendesk.computer.capture.capture_screen",
            lambda region=None: (make_png(5), 100, 100),
        )
        session = "goal-miss"
        goal_state.clear_goals(session)
        ctx = ctx_for(session)
        await goal_state.capture_goal("done", ctx, session_id=session)

        score = await goal_state.score_goal(
            "done", ctx, session_id=session, current_png=make_png(99)
        )
        assert not score.reached
        assert score.score < 0.8

    @pytest.mark.asyncio
    async def test_unknown_goal_raises(self):
        with pytest.raises(KeyError):
            await goal_state.score_goal("nope", ctx_for("goal-none"),
                                        session_id="goal-none")

    def test_goal_store_operations(self):
        goal_state.clear_goals("gs-1")
        g = goal_state.GoalState(name="a", fingerprint="ff")
        goal_state._store("gs-1")["a"] = g
        assert goal_state.list_goals("gs-1") == ["a"]
        assert goal_state.get_goal("a", "gs-1") is g
        assert goal_state.delete_goal("a", "gs-1") is True
        assert goal_state.clear_goals("gs-1") == 0


# ---------------------------------------------------------------------------
# Episodes and trajectory export
# ---------------------------------------------------------------------------


class TestTrajectories:
    @pytest.mark.asyncio
    async def test_episode_lifecycle(self):
        clear_sandbox("tr-1")
        sb = get_sandbox("tr-1")
        ep = trajectories.begin_episode("task one", session_id="tr-1", sandbox=sb)
        assert not ep.finished

        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {})
        sb.current_screen = FP1
        await sb.record_action(ActionType.UI_ACTION, {})

        trajectories.end_episode(ep, session_id="tr-1", sandbox=sb,
                                 outcome={"reward": 1.0})
        assert ep.finished
        assert ep.reward == 1.0
        assert ep.end_index is not None

    @pytest.mark.asyncio
    async def test_build_trajectory_steps(self):
        clear_sandbox("tr-2")
        sb = get_sandbox("tr-2")
        ep = trajectories.begin_episode("task two", session_id="tr-2", sandbox=sb)
        for fp in (FP0, FP1, FP2):
            sb.current_screen = fp
            await sb.record_action(ActionType.UI_ACTION, {"action": "click"})
        trajectories.end_episode(ep, session_id="tr-2", sandbox=sb,
                                 outcome={"reward": 0.0})

        traj = trajectories.build_trajectory(ep, entries=sb.export_audit_log())
        assert traj["type"] == "episode"
        assert len(traj["steps"]) == 3
        assert traj["steps"][0]["step"] == 1
        assert traj["steps"][-1]["done"] is True
        assert traj["steps"][0]["observation"]["screen"] == FP0

    @pytest.mark.asyncio
    async def test_export_writes_jsonl_and_images(self, tmp_path):
        from opendesk.computer.observations import clear_store, get_store

        clear_sandbox("tr-3")
        clear_store("tr-3")
        sb = get_sandbox("tr-3")
        store = get_store("tr-3")

        ep = trajectories.begin_episode("task three", session_id="tr-3", sandbox=sb)
        for i, fp in enumerate((FP0, FP1)):
            store.record(make_png(i), width=64, height=48, fingerprint=fp)
            sb.current_screen = fp
            await sb.record_action(ActionType.UI_ACTION, {})
        trajectories.end_episode(ep, session_id="tr-3", sandbox=sb,
                                 outcome={"reward": 1.0, "score": 1.0})

        dest = tmp_path / "run.jsonl"
        proc = process.score_process(sb.export_audit_log(), outcome_reward=1.0)
        manifest = trajectories.export(
            ep, entries=sb.export_audit_log(), store=store,
            process=proc.to_dict(), path=str(dest),
        )
        assert manifest["steps"] == 2
        assert manifest["images"] == 2

        lines = dest.read_text(encoding="utf-8").strip().splitlines()
        header = json.loads(lines[0])
        assert header["type"] == "episode"
        assert header["task"] == "task three"
        assert header["step_count"] == 2
        first = json.loads(lines[1])
        assert first["type"] == "step"
        assert first["observation"]["screenshot"].endswith(".png")
        assert "reward" in first and "return" in first

        image_dir = tmp_path / "run.jsonl_images"
        assert image_dir.is_dir()
        assert len(list(image_dir.glob("*.png"))) == 2

    @pytest.mark.asyncio
    async def test_later_episode_in_a_session_keeps_its_step_rewards(self):
        """Every attempt in a best-of-N sweep must export its own rewards.

        Process rewards are matched to trajectory steps by absolute audit
        position.  When the scorer reported slice-relative indices, every
        episode after the first in a session silently lost all of them — the
        rewards landed on positions the window never looked up, so the exported
        steps came out as ``reward=0.0, return=None``.
        """
        clear_sandbox("tr-idx")
        sb = get_sandbox("tr-idx")

        # A first episode, so the second does not begin at index 0.
        first = trajectories.begin_episode("first", session_id="tr-idx", sandbox=sb)
        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {"action": "click"})
        trajectories.end_episode(first, session_id="tr-idx", sandbox=sb,
                                 outcome={"reward": 0.0})
        assert first.start_index == 0

        second = trajectories.begin_episode("second", session_id="tr-idx", sandbox=sb)
        assert second.start_index > 0
        for fp in (FP0, FP1):
            sb.current_screen = fp
            await sb.record_action(ActionType.UI_ACTION, {"action": "click"})

        proc = process.score_process(
            sb.export_audit_log()[second.start_index:],
            outcome_reward=1.0,
            index_offset=second.start_index,
        )
        trajectories.end_episode(second, session_id="tr-idx", sandbox=sb,
                                 outcome={"reward": 1.0}, process=proc.to_dict())

        traj = trajectories.build_trajectory(
            second, entries=sb.export_audit_log(), process=second.process
        )
        rewards = [s["reward"] for s in traj["steps"]]
        assert all(r != 0.0 for r in rewards), rewards
        assert traj["steps"][-1]["reward"] > 0        # success bonus landed
        assert traj["steps"][-1]["return"] is not None

    @pytest.mark.asyncio
    async def test_export_can_embed_images(self, tmp_path):
        from opendesk.computer.observations import clear_store, get_store
        clear_sandbox("tr-4")
        clear_store("tr-4")
        sb = get_sandbox("tr-4")
        store = get_store("tr-4")
        ep = trajectories.begin_episode("embed", session_id="tr-4", sandbox=sb)
        store.record(make_png(0), fingerprint=FP0)
        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {})
        trajectories.end_episode(ep, session_id="tr-4", sandbox=sb)

        dest = tmp_path / "embed.jsonl"
        manifest = trajectories.export(
            ep, entries=sb.export_audit_log(), store=store,
            path=str(dest), embed_images=True,
        )
        assert manifest["images"] == 1
        assert manifest["image_dir"] is None
        step = json.loads(dest.read_text(encoding="utf-8").splitlines()[1])
        assert step["observation"]["screenshot"].startswith("data:image/png;base64,")

    def test_episode_helpers(self):
        trajectories.clear_episodes("tr-5")
        ep = trajectories.begin_episode("t", session_id="tr-5")
        assert trajectories.get_episode(ep.id, "tr-5") is ep
        assert trajectories.latest_episode("tr-5") is ep
        assert trajectories.list_episodes("tr-5") == [ep]
        assert trajectories.clear_episodes("tr-5") == 1
        assert trajectories.latest_episode("tr-5") is None


# ---------------------------------------------------------------------------
# Preference pairs
# ---------------------------------------------------------------------------


class TestRewardTool:
    @pytest.mark.asyncio
    async def test_begin_check_end_export_flow(self, tmp_path):
        sid = "rt-flow"
        clear_sandbox(sid)
        from opendesk.computer.observations import clear_store

        clear_store(sid)
        ctx = ctx_for(sid)
        reward_tool = RewardTool()

        target = tmp_path / "out.txt"
        spec = {"task": "write out.txt", "checks": [
            {"kind": "file_exists", "path": str(target)},
            {"kind": "file_contains", "path": str(target), "text": "done"},
        ]}

        # begin
        r = await reward_tool.execute(ctx, reward_tool.parse_params(
            {"action": "begin", "task": "write out.txt", "spec": spec}
        ))
        assert not r.error

        # not yet done — check should fail
        r = await reward_tool.execute(ctx, reward_tool.parse_params({"action": "check"}))
        assert "FAIL" in r.title

        # do the work
        sb = get_sandbox(sid)
        sb.current_screen = FP0
        await sb.record_action(ActionType.UI_ACTION, {})
        target.write_text("done\n", encoding="utf-8")
        sb.current_screen = FP1
        await sb.record_action(ActionType.UI_ACTION, {})

        # now it passes
        r = await reward_tool.execute(ctx, reward_tool.parse_params({"action": "check"}))
        assert "PASS" in r.title
        assert r.metadata["reward"] == 1.0

        # end
        r = await reward_tool.execute(ctx, reward_tool.parse_params({"action": "end"}))
        assert not r.error
        assert r.metadata["reward"] == 1.0
        assert r.metadata["process_metrics"]["total_steps"] == 2

    @pytest.mark.asyncio
    async def test_begin_requires_task(self):
        ctx = ctx_for("rt-notask")
        tool = RewardTool()
        r = await tool.execute(ctx, tool.parse_params({"action": "begin"}))
        assert r.error

    @pytest.mark.asyncio
    async def test_begin_rejects_bad_spec(self):
        ctx = ctx_for("rt-badspec")
        tool = RewardTool()
        r = await tool.execute(ctx, tool.parse_params(
            {"action": "begin", "task": "t", "spec": {"checks": [{"kind": "nope"}]}}
        ))
        assert r.error

    @pytest.mark.asyncio
    async def test_end_without_episode(self):
        clear_sandbox("rt-noep")
        trajectories.clear_episodes("rt-noep")
        ctx = ctx_for("rt-noep")
        tool = RewardTool()
        r = await tool.execute(ctx, tool.parse_params({"action": "end"}))
        assert r.error

    @pytest.mark.asyncio
    async def test_double_end_is_refused(self, tmp_path):
        sid = "rt-double"
        clear_sandbox(sid)
        trajectories.clear_episodes(sid)
        ctx = ctx_for(sid)
        tool = RewardTool()
        await tool.execute(ctx, tool.parse_params(
            {"action": "begin", "task": "t",
             "spec": {"checks": [{"kind": "file_exists", "path": str(tmp_path / "a")}]}}
        ))
        first = await tool.execute(ctx, tool.parse_params({"action": "end"}))
        assert not first.error
        second = await tool.execute(ctx, tool.parse_params({"action": "end"}))
        assert second.error and "already closed" in second.output

    @pytest.mark.asyncio
    async def test_goal_capture_list_score(self, monkeypatch):
        monkeypatch.setattr(
            "opendesk.computer.capture.capture_screen",
            lambda region=None: (make_png(7), 100, 100),
        )
        sid = "rt-goal"
        goal_state.clear_goals(sid)
        ctx = ctx_for(sid)
        tool = RewardTool()

        r = await tool.execute(ctx, tool.parse_params(
            {"action": "goal_capture", "goal": "done"}
        ))
        assert not r.error
        assert r.metadata["anchors"]

        r = await tool.execute(ctx, tool.parse_params({"action": "goal_list"}))
        assert "done" in r.output

        r = await tool.execute(ctx, tool.parse_params(
            {"action": "goal_score", "goal": "done"}
        ))
        assert "REACHED" in r.output

    @pytest.mark.asyncio
    async def test_episodes_listing(self):
        sid = "rt-eps"
        clear_sandbox(sid)
        trajectories.clear_episodes(sid)
        ctx = ctx_for(sid)
        tool = RewardTool()
        await tool.execute(ctx, tool.parse_params({"action": "begin", "task": "alpha"}))
        r = await tool.execute(ctx, tool.parse_params({"action": "episodes"}))
        assert "alpha" in r.output


class TestUiElementValueAssertions:
    """``ui_element`` with a value is what makes a reward *verifiable*.

    "The Total field reads 300" is a statement about the task.  "The screen
    changed" is not.
    """

    @staticmethod
    def ctx(session: str, tree) -> ToolContext:
        return ToolContext(session_id=session, computer=TreeComputer(tree))

    @pytest.mark.asyncio
    async def test_value_regex_matches_a_field(self):
        ctx = self.ctx("uiv-1", ui_tree(
            ui_node("AXStaticText", "Total"),
            ui_node("AXTextField", "Total", value="300"),
        ))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "role": "textfield", "value_regex": r"^300$"},
        ]}, ctx=ctx)
        assert report.passed
        assert report.results[0].evidence["matches"][0]["value"] == "300"

    @pytest.mark.asyncio
    async def test_a_stale_value_fails(self):
        ctx = self.ctx("uiv-2", ui_tree(ui_node("AXTextField", "Total", value="100")))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "role": "textfield", "value_regex": r"^300$"},
        ]}, ctx=ctx)
        assert not report.passed
        assert "no matching element" in report.results[0].detail
        # The evidence says what was looked for, so a failure is diagnosable.
        assert report.results[0].evidence["value_regex"] == "^300$"

    @pytest.mark.asyncio
    async def test_value_equals_is_an_exact_comparison(self):
        ctx = self.ctx("uiv-3", ui_tree(ui_node("AXTextField", "Total", value="300")))
        ok = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "value_equals": "300"},
        ]}, ctx=ctx)
        assert ok.passed
        partial_match = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "value_equals": "30"},
        ]}, ctx=ctx)
        assert not partial_match.passed

    @pytest.mark.asyncio
    async def test_role_and_value_combine(self):
        ctx = self.ctx("uiv-4", ui_tree(ui_node("AXTextField", "Total", value="300")))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "role": "button", "value_regex": "300"},
        ]}, ctx=ctx)
        assert not report.passed

    @pytest.mark.asyncio
    async def test_content_regex_reaches_either_field(self):
        ctx = self.ctx("uiv-5", ui_tree(ui_node("AXStaticText", "Total: 300")))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "content_regex": r"Total: 3\d\d"},
        ]}, ctx=ctx)
        assert report.passed

    @pytest.mark.asyncio
    async def test_name_only_matching_still_works(self):
        """The pre-existing behaviour must not regress."""
        ctx = ctx_for("uiv-6")
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_element", "role": "button", "name_regex": "^Save$"},
        ]}, ctx=ctx)
        assert report.passed


class TestUiChangedCheck:
    """``ui_changed`` is the semantic counterpart of ``screen_changed``."""

    @staticmethod
    def seed(session: str, before_tree, after_tree):
        from opendesk.computer.a11y import ui_snapshot
        from opendesk.computer.observations import clear_store, get_store

        clear_store(session)
        store = get_store(session)
        store.record(make_png(1), width=64, height=48, fingerprint="aa",
                     ui_snapshot=ui_snapshot(before_tree))
        store.record(make_png(2), width=64, height=48, fingerprint="ab",
                     ui_snapshot=ui_snapshot(after_tree))

    def frame(self, total: str, clock: str = "09:41:00"):
        return ui_tree(
            ui_node("AXMenuBar", "", children=[ui_node("AXStaticText", clock)]),
            ui_node("AXStaticText", total),
        )

    @pytest.mark.asyncio
    async def test_a_glyph_edit_is_detected(self):
        sid = "uic-1"
        self.seed(sid, self.frame("Total: 100"), self.frame("Total: 150"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert report.passed
        assert report.results[0].evidence["modified"] == [
            "[AXStaticText] 'Total: 100' \u2192 'Total: 150'"
        ]

    @pytest.mark.asyncio
    async def test_a_clock_tick_alone_is_not_a_change(self):
        """Pixels cannot make this call; content can.

        Ambient roles are pruned by default, so this needs no configuration: a
        check that fired here would be a verifiable predicate reporting a change
        that never happened.
        """
        sid = "uic-2"
        self.seed(sid, self.frame("Total: 100", "09:41:00"),
                  self.frame("Total: 100", "09:41:01"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert not report.passed
        assert report.results[0].evidence["modified"] == []

    @pytest.mark.asyncio
    async def test_the_clock_is_still_visible_when_explicitly_asked_for(self):
        """Pruning is a default, not a blindfold.

        ``ignore_roles: []`` means "compare everything", which is what a task
        that genuinely cares about a status readout would pass.
        """
        sid = "uic-2b"
        self.seed(sid, self.frame("Total: 100", "09:41:00"),
                  self.frame("Total: 100", "09:41:01"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0, "ignore_roles": []},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert report.passed
        assert report.results[0].evidence["modified"] == [
            "[AXStaticText] '09:41:00' \u2192 '09:41:01'"
        ]

    @pytest.mark.asyncio
    async def test_a_real_edit_is_not_hidden_by_the_default_pruning(self):
        """The default must not be so eager that it swallows the signal.

        Ignoring the menu bar drops the clock with it; the field being edited is
        not in the menu bar and must still register.
        """
        sid = "uic-2c"
        self.seed(sid, self.frame("Total: 100", "09:41:00"),
                  self.frame("Total: 150", "09:41:01"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert report.passed
        assert report.results[0].evidence["content_changes"] == 1
        assert report.results[0].evidence["ignored_roles"]

    @pytest.mark.asyncio
    async def test_the_evidence_says_what_was_ignored(self):
        """A verdict is only auditable if it records what it compared."""
        sid = "uic-2d"
        self.seed(sid, self.frame("Total: 100"), self.frame("Total: 100"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert "menubar" in report.results[0].evidence["ignored_roles"]

    @pytest.mark.asyncio
    async def test_ignoring_the_clock_does_not_hide_a_real_edit(self):
        sid = "uic-3"
        self.seed(sid, self.frame("Total: 100", "09:41:00"),
                  self.frame("Total: 150", "09:41:01"))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0, "ignore_roles": ["menubar"]},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert report.passed
        assert report.results[0].evidence["content_changes"] == 1
    @pytest.mark.asyncio
    async def test_an_added_dialog_is_a_change(self):
        sid = "uic-4"
        self.seed(sid, ui_tree(ui_node("AXStaticText", "Idle")),
                  ui_tree(ui_node("AXStaticText", "Idle"),
                          ui_node("AXSheet", "Confirm")))
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert report.passed
        assert any("Confirm" in d for d in report.results[0].evidence["added"])

    @pytest.mark.asyncio
    async def test_a_missing_snapshot_says_so_instead_of_guessing(self):
        """A silent pass or fail here would be worse than an honest refusal."""
        from opendesk.computer.observations import clear_store, get_store

        sid = "uic-5"
        clear_store(sid)
        store = get_store(sid)
        store.record(make_png(1), width=64, height=48)      # no tree captured
        store.record(make_png(2), width=64, height=48)
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": 0},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert not report.passed
        assert "tree=true" in report.results[0].detail

    @pytest.mark.asyncio
    async def test_unknown_reference_fails_cleanly(self):
        sid = "uic-6"
        from opendesk.computer.observations import clear_store

        clear_store(sid)
        report = await rewards.evaluate({"task": "t", "checks": [
            {"kind": "ui_changed", "ref": "previous"},
        ]}, ctx=ctx_for(sid), session_id=sid)
        assert not report.passed


# ---------------------------------------------------------------------------
# Semantic state identity in the state graph
# ---------------------------------------------------------------------------


class TestSemanticStateIdentity:
    """A content digest sees an edited glyph; a perceptual hash does not."""

    U0, U1, U2 = "aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"

    @pytest.mark.asyncio
    async def test_recorded_actions_carry_the_current_digest(self):
        """The digest reaches the audit log through the sandbox, like ``screen``."""
        sid = "sem-stamp"
        clear_sandbox(sid)
        sandbox = get_sandbox(sid)

        sandbox.current_ui = self.U0
        first = await sandbox.record_action(ActionType.UI_ACTION, {"a": 1})
        sandbox.current_ui = self.U1
        second = await sandbox.record_action(ActionType.UI_ACTION, {"a": 2})

        assert first.ui == self.U0
        assert second.ui == self.U1
        assert [e["ui"] for e in sandbox.export_audit_log()] == [self.U0, self.U1]

    @pytest.mark.asyncio
    async def test_an_action_recorded_before_any_read_carries_nothing(self):
        sid = "sem-stamp-2"
        clear_sandbox(sid)
        entry_ = await get_sandbox(sid).record_action(ActionType.UI_ACTION, {"a": 1})
        assert entry_.ui is None
        assert "ui" not in entry_.to_dict()

    @pytest.mark.asyncio
    async def test_the_digest_reaches_the_graph_through_the_audit_log(self):
        sid = "sem-stamp-3"
        clear_sandbox(sid)
        sandbox = get_sandbox(sid)
        for digest in (self.U0, self.U1):
            sandbox.current_ui = digest
            await sandbox.record_action(ActionType.UI_ACTION, {"step": digest})

        report = diagnostics.diagnose(sandbox.export_audit_log())
        assert report.identity == "ui"
        assert report.state_count == 2
        assert [s["effect"] for s in report.steps] == ["changed", "none"]

    def test_auto_uses_content_when_every_action_has_it(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0),
            ui_entry("ui_action", self.U1),
        ])
        assert report.identity == "ui"
        assert report.state_count == 2

    def test_auto_falls_back_to_screens_when_content_is_partial(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0, screen=FP0),
            ui_entry("ui_action", None, screen=FP1),
        ])
        assert report.identity == "screen"
        assert report.state_count == 2

    def test_auto_falls_back_when_nothing_carries_content(self):
        report = diagnostics.diagnose([
            entry("ui_action", FP0), entry("ui_action", FP1),
        ])
        assert report.identity == "screen"

    def test_explicit_identity_is_honoured(self):
        entries = [ui_entry("ui_action", self.U0), ui_entry("ui_action", self.U1)]
        assert diagnostics.diagnose(entries, identity="screen").identity == "screen"
        assert diagnostics.diagnose(entries, identity="ui").identity == "ui"

    def test_content_sees_a_glyph_edit_that_screens_would_merge(self):
        """The whole point: same layout, different content, two states."""
        glyph_edit = [
            ui_entry("ui_action", self.U0, screen=FP0),
            ui_entry("ui_action", self.U1, screen=FP0),   # identical pixels
        ]
        semantic = diagnostics.diagnose(glyph_edit)
        assert semantic.identity == "ui"
        assert semantic.state_count == 2
        assert [s["effect"] for s in semantic.steps] == ["changed", "none"]

        # The same log read by pixels is blind to it — which is the limitation
        # the content digest exists to remove.
        by_pixels = diagnostics.diagnose(glyph_edit, identity="screen")
        assert by_pixels.state_count == 1
        assert [s["effect"] for s in by_pixels.steps] == ["same", "none"]

    def test_identical_content_is_one_state(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0),
            ui_entry("ui_action", self.U0),
            ui_entry("ui_action", self.U0),
        ])
        assert report.state_count == 1
        assert report.nodes["S0"].visits == 3

    def test_a_clock_tick_is_not_a_new_state_once_ignored(self):
        """Digests are taken with the clock excluded, so a tick is a non-event."""
        from opendesk.computer.a11y import content_hash

        def frame(clock: str):
            return ui_tree(
                ui_node("AXMenuBar", "", children=[ui_node("AXStaticText", clock)]),
                ui_node("AXStaticText", "Total: 100"),
            )

        quiet = [content_hash(frame(c), ignore_roles="menubar")
                 for c in ("09:41:00", "09:41:01", "09:41:02")]
        report = diagnostics.diagnose([ui_entry("ui_action", d) for d in quiet])
        assert report.state_count == 1

    def test_summary_mentions_what_states_were_grouped_by(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0), ui_entry("ui_action", self.U1),
        ])
        assert "content digests" in report.summary_text()

        by_pixels = diagnostics.diagnose([
            entry("ui_action", FP0), entry("ui_action", FP1),
        ])
        assert "tolerance" in by_pixels.summary_text()

    def test_identity_is_reported_in_the_dict(self):
        report = diagnostics.diagnose([ui_entry("ui_action", self.U0)])
        assert report.as_dict()["metrics"]["identity"] == "ui"

    def test_entries_without_content_are_counted_as_skipped(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0),
            ui_entry("ui_action", None),
        ], identity="ui")
        assert report.skipped == 1
        assert report.step_count == 1

    def test_skipped_note_names_the_identity_used(self):
        report = diagnostics.diagnose([
            ui_entry("ui_action", self.U0), ui_entry("ui_action", None),
        ], identity="ui")
        assert "accessibility digest" in report.summary_text()


class TestProcessSignalSource:
    """A silent downgrade to a weaker signal used to be invisible."""

    def test_reports_the_fallback_when_there_is_nothing_to_observe(self):
        report = process.score_process([
            {"action": "system", "screen": None, "ui": None, "error": False,
             "timestamp": 0.0, "params": {"command": "ls"}, "result": "ok"},
            {"action": "system", "screen": None, "ui": None, "error": False,
             "timestamp": 0.0, "params": {"command": "pwd"}, "result": "/"},
        ])
        assert report.signal_source == "action"
        assert report.to_dict()["metrics"]["signal_source"] == "action"

    def test_reports_screens_when_only_fingerprints_exist(self):
        report = process.score_process([
            entry("ui_action", FP0), entry("ui_action", FP1),
        ])
        assert report.signal_source == "screen"

    def test_reports_content_when_digests_exist(self):
        report = process.score_process([
            ui_entry("ui_action", "aaaaaaaaaaaa"),
            ui_entry("ui_action", "bbbbbbbbbbbb"),
        ])
        assert report.signal_source == "ui"
        assert report.effective_steps == 1

    def test_content_digests_give_a_cli_free_session_real_effects(self):
        """No screenshots, but trees were read — effects are observed, not guessed."""
        report = process.score_process([
            ui_entry("ui_action", "aaaaaaaaaaaa"),
            ui_entry("ui_action", "aaaaaaaaaaaa"),   # this action changed nothing
            ui_entry("ui_action", "cccccccccccc"),
        ])
        assert report.signal_source == "ui"
        assert report.no_effect_steps >= 1
