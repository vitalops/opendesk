"""RewardTool — define, check, and record verifiable task rewards.

This is the entry point to the learning layer's environment side.  It lets an
agent declare what "done" means for a task as machine-checkable predicates,
score a run against them, and close the run as an episode that can be exported
as training data.

Nothing here calls a model: every verdict is backed by observable state (files,
shell exit codes, the accessibility tree, screenshots), which is what makes the
reward verifiable.

Typical loop::

    reward(action="goal_capture", goal="done")          # optional reference
    reward(action="begin", task="Export the invoice",
           spec={"checks": [{"kind": "file_exists", "path": "~/invoice.pdf"}]})
    … do the work …
    reward(action="end")                                # scores and closes
"""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import Field

from opendesk.tools.base import Tool, ToolContext, ToolResult


class RewardTool(Tool):
    """Verifiable rewards, goal-state anchoring, and episode bookkeeping."""

    name = "reward"
    title = "Verifiable Task Reward"
    annotations = {
        "readOnlyHint": False, "destructiveHint": False,
        "idempotentHint": True, "openWorldHint": True,
    }
    description = (
        "Define and check machine-verifiable success criteria for a task, and "
        "close the run as an exportable episode.\n\n"
        "  action='begin'        — start an episode (task, optional reward spec)\n"
        "  action='check'        — evaluate the reward spec against the live machine\n"
        "  action='assert'       — declare what you believe is true right now\n"
        "  action='assertions'   — how many of your claims held\n"
        "  action='end'          — score the episode and attach process rewards\n"
        "  action='goal_capture' — record the current screen as a goal state\n"
        "  action='goal_score'   — score the current screen against a goal state\n"
        "  action='goal_list'    — list recorded goal states\n"
        "  action='episodes'     — list episodes recorded this session\n\n"
        "Reward specs are data, not code. Supported check kinds: file_exists, "
        "file_absent, file_contains, shell, clipboard_contains, clipboard_equals, "
        "app_running, ui_element (with value_regex / value_equals / content_regex), "
        "ui_changed, screen_matches, screen_changed.\n\n"
        "Every judgement is backed by observed state, so a reward can be "
        "re-checked and audited — no model is consulted."
    )

    class Params(Tool.Params):
        action: Literal[
            "begin", "check", "assert", "assertions", "end", "goal_capture",
            "goal_score", "goal_list", "episodes",
        ] = Field(default="check", description="What to do.")

        task: Optional[str] = Field(
            default=None, description="Task description, for action='begin'."
        )
        episode_id: Optional[str] = Field(
            default=None,
            description="Episode to act on. Defaults to the latest open episode.",
        )
        spec: Optional[dict[str, Any]] = Field(
            default=None,
            description=(
                "Reward spec: {'task': str, 'mode': 'all'|'any'|'weighted', "
                "'checks': [...]}. Required for 'check' unless the episode has one."
            ),
        )
        goal: Optional[str] = Field(
            default=None,
            description="Goal-state name, for goal_capture / goal_score / begin.",
        )
        name: Optional[str] = Field(
            default=None,
            description=(
                "Assertion name, for action='assert'. Short and stable — it is "
                "how the claim appears in a trajectory, e.g. 'invoice downloaded'."
            ),
        )
        claim: Optional[str] = Field(
            default=None,
            description=(
                "For action='assert': the claim in your own words, recorded "
                "verbatim for a reader. Never parsed."
            ),
        )
        checks: Optional[list[dict[str, Any]]] = Field(
            default=None,
            description=(
                "For action='assert': the machine-checkable expectation behind "
                "the claim, as a list of checks (same kinds as 'spec'). Required "
                "— an assertion you cannot be wrong about is not one."
            ),
        )
        meta: Optional[dict[str, Any]] = Field(
            default=None, description="Arbitrary metadata to attach to the episode."
        )
        min_similarity: float = Field(
            default=0.80, ge=0.0, le=1.0,
            description="For goal_score: visual similarity required to count as reached.",
        )
        gamma: float = Field(
            default=0.95, ge=0.0, le=1.0,
            description="For action='end': discount factor for process returns.",
        )

    async def execute(self, ctx: ToolContext, params: "RewardTool.Params") -> ToolResult:
        handler = {
            "begin": self._begin,
            "check": self._check,
            "assert": self._assert,
            "assertions": self._assertions,
            "end": self._end,
            "goal_capture": self._goal_capture,
            "goal_score": self._goal_score,
            "goal_list": self._goal_list,
            "episodes": self._episodes,
        }[params.action]
        return await handler(ctx, params)

    # ------------------------------------------------------------------

    async def _begin(self, ctx, params) -> ToolResult:
        from opendesk.computer.sandbox import get_sandbox
        from opendesk.learning.trajectories import begin_episode

        if not params.task:
            return ToolResult(
                title="Reward begin",
                output="action='begin' needs a 'task' describing what is being attempted.",
                error=True,
            )

        if params.spec is not None:
            from opendesk.learning.rewards import parse_spec

            try:
                parse_spec(params.spec)
            except ValueError as exc:
                return ToolResult(
                    title="Reward begin", output=f"Invalid reward spec: {exc}", error=True
                )

        ep = begin_episode(
            params.task,
            session_id=ctx.session_id,
            sandbox=get_sandbox(ctx.session_id),
            goal=params.goal,
            spec=params.spec,
            meta=params.meta,
        )
        await self._audit(ctx, "episode_begin", {"task": params.task}, ep.id)
        return ToolResult(
            title=f"Episode {ep.id}",
            output=(
                f"Started episode {ep.id} — {params.task}\n"
                + (f"  goal state: {params.goal}\n" if params.goal else "")
                + (f"  reward spec: {len(params.spec.get('checks', []))} check(s)\n"
                   if params.spec else "  (no reward spec yet)\n")
                + "  Do the work, then call reward(action='end') to score it."
            ),
            metadata={"episode_id": ep.id},
        )

    async def _check(self, ctx, params) -> ToolResult:
        from opendesk.learning.rewards import evaluate
        from opendesk.learning.trajectories import get_episode, latest_episode

        spec = params.spec
        if spec is None:
            ep = (
                get_episode(params.episode_id, ctx.session_id)
                if params.episode_id else latest_episode(ctx.session_id)
            )
            spec = ep.spec if ep else None
        if spec is None:
            return ToolResult(
                title="Reward check",
                output=(
                    "No reward spec given and no episode carries one. Pass "
                    "'spec' with a 'checks' list."
                ),
                error=True,
            )

        try:
            report = await evaluate(spec, ctx=ctx, session_id=ctx.session_id)
        except ValueError as exc:
            return ToolResult(
                title="Reward check", output=f"Invalid reward spec: {exc}", error=True
            )

        await self._audit(
            ctx, "reward_check", {"task": report.task},
            f"reward={report.reward} score={report.score}",
        )
        return ToolResult(
            title=f"Reward {'PASS' if report.passed else 'FAIL'}",
            output=report.summary_text(),
            metadata=report.to_dict(),
        )

    async def _end(self, ctx, params) -> ToolResult:
        from opendesk.computer.sandbox import get_sandbox
        from opendesk.learning.assertions import for_episode, recheck
        from opendesk.learning.process import score_process
        from opendesk.learning.rewards import evaluate
        from opendesk.learning.trajectories import end_episode, get_episode, latest_episode

        ep = (
            get_episode(params.episode_id, ctx.session_id)
            if params.episode_id else latest_episode(ctx.session_id)
        )
        if ep is None:
            return ToolResult(
                title="Reward end",
                output="No episode to close. Call reward(action='begin', task=...) first.",
                error=True,
            )
        if ep.finished:
            return ToolResult(
                title="Reward end",
                output=(
                    f"Episode {ep.id} is already closed "
                    f"(reward={ep.reward}). Start a new one with action='begin'."
                ),
                error=True,
            )

        outcome: Optional[dict[str, Any]] = None
        if ep.spec is not None:
            scored = await evaluate(ep.spec, ctx=ctx, session_id=ctx.session_id)
            outcome = scored.to_dict()

        sandbox = get_sandbox(ctx.session_id)
        outcome_reward = float(outcome.get("reward", 0.0)) if outcome else 0.0
        # Score only this episode's slice, but report positions relative to the
        # whole log: `build_trajectory` matches process rewards to steps by
        # absolute audit position, so a slice-relative index silently attaches
        # every reward to the wrong step whenever the episode is not the first
        # in its session — i.e. on every best-of-N run.
        proc = score_process(
            sandbox.export_audit_log()[ep.start_index:],
            outcome_reward=outcome_reward,
            gamma=params.gamma,
            index_offset=ep.start_index,
        )

        # Re-check the agent's own claims against the closing state.  A claim
        # that held when made and does not hold now is a regression the terminal
        # reward cannot see — the agent declared success and later broke it.
        from opendesk.learning.assertions import AssertionReport

        await recheck(session_id=ctx.session_id, ctx=ctx, episode_id=ep.id)
        claims = for_episode(ep.id, ctx.session_id)
        scoped = (
            AssertionReport(session_id=ctx.session_id, assertions=claims).to_dict()
            if claims else None
        )

        end_episode(
            ep, session_id=ctx.session_id, sandbox=sandbox,
            outcome=outcome, process=proc.to_dict(), assertions=scoped,
        )
        await self._audit(
            ctx, "episode_end", {"episode": ep.id},
            f"reward={outcome_reward} steps={proc.total_steps}",
        )

        lines = [f"Closed episode {ep.id} — {ep.task}"]
        if outcome:
            mark = "PASS" if outcome.get("passed") else "FAIL"
            lines.append(
                f"  outcome: [{mark}] reward={outcome['reward']:.2f}  "
                f"score={outcome['score']:.0%}  "
                f"({outcome['required_passed']}/{outcome['required_total']} required checks)"
            )
            for c in outcome.get("checks", []):
                if not c["passed"]:
                    lines.append(f"    [ ] {c['target']} — {c['detail']}")
        else:
            lines.append("  outcome: (no reward spec — recorded without a reward)")
        lines.append(
            f"  process: {proc.total_steps} step(s), efficiency {proc.efficiency:.0%}, "
            f"{proc.no_effect_steps} no-effect, {proc.error_steps} error(s), "
            f"return {proc.returns[0]:+.2f}" if proc.returns else ""
        )
        lines = [ln for ln in lines if ln]
        if claims:
            lines.append(
                f"  claims: {len(claims)} declared, "
                f"{scoped['metrics']['held']} held, "
                f"{scoped['metrics']['regressed']} regressed "
                f"(precision {scoped['metrics']['precision']:.0%})"
            )
            for a in claims:
                lines.append("    " + a.describe().replace("\n", "\n    "))
        lines.append(
            "\n  Export the recorded trajectory with rollout(action='export')."
        )
        return ToolResult(
            title=f"Episode closed — reward {outcome_reward:.0f}",
            output="\n".join(lines),
            metadata={
                "episode_id": ep.id,
                "reward": outcome_reward,
                "outcome": outcome,
                "process_metrics": proc.to_dict()["metrics"],
                "assertions": scoped,
            },
        )

    async def _assert(self, ctx, params) -> ToolResult:
        """Record what the agent believes is true, and check it immediately.

        The verdict comes back in the same call rather than at episode end, so a
        belief that does not hold is something the agent can act on instead of a
        post-mortem surprise.
        """
        from opendesk.computer.sandbox import get_sandbox
        from opendesk.learning.assertions import declare
        from opendesk.learning.trajectories import get_episode, latest_episode

        if not params.name:
            return ToolResult(
                title="Assertion",
                output="action='assert' needs a 'name' for the claim.",
                error=True,
            )
        if not params.checks:
            return ToolResult(
                title="Assertion",
                output=(
                    "action='assert' needs 'checks' — the machine-checkable "
                    "expectation behind the claim. A claim nothing can falsify "
                    "is not an assertion; use the note for free text, not this."
                ),
                error=True,
            )

        ep = (
            get_episode(params.episode_id, ctx.session_id)
            if params.episode_id else latest_episode(ctx.session_id)
        )
        try:
            assertion = await declare(
                params.name,
                checks=params.checks,
                ctx=ctx,
                session_id=ctx.session_id,
                claim=params.claim or "",
                index=len(get_sandbox(ctx.session_id).audit_log),
                episode_id=ep.id if ep else None,
            )
        except ValueError as exc:
            return ToolResult(
                title="Assertion",
                output=f"Invalid assertion checks: {exc}",
                error=True,
            )

        await self._audit(
            ctx, "assertion", {"name": assertion.name, "claim": assertion.claim},
            f"held={assertion.held} index={assertion.index}",
        )

        verdict = "HOLDS" if assertion.held else "DOES NOT HOLD"
        lines = [f"{verdict}: {assertion.name}"]
        if assertion.claim:
            lines.append(f"  claim: “{assertion.claim}”")
        for r in assertion.results:
            mark = "x" if r.passed else " "
            lines.append(f"  [{mark}] {r.check.target} — {r.detail}")
        if not assertion.held:
            lines.append(
                "\n  The state does not match the claim. Fix it before continuing — "
                "this verdict is recorded either way, and re-checked when the "
                "episode closes."
            )
        lines.append(
            "\n  Note: an assertion is a report of belief, not a reward. It does "
            "not score the task or add to the return."
        )
        return ToolResult(
            title=f"Assertion {'holds' if assertion.held else 'does not hold'}: {assertion.name}",
            output="\n".join(lines),
            metadata=assertion.to_dict(),
        )

    async def _assertions(self, ctx, params) -> ToolResult:
        from opendesk.learning.assertions import report

        rep = report(ctx.session_id)
        await self._audit(
            ctx, "assertions", {},
            f"declared={rep.declared} precision={rep.precision:.2f}",
        )
        return ToolResult(
            title=f"Assertions ({rep.declared})",
            output=rep.summary_text(),
            metadata=rep.to_dict(),
        )

    async def _goal_capture(self, ctx, params) -> ToolResult:
        from opendesk.learning.goal_state import capture_goal

        if not params.goal:
            return ToolResult(
                title="Goal capture",
                output="action='goal_capture' needs a 'goal' name.",
                error=True,
            )
        goal = await capture_goal(
            params.goal, ctx, session_id=ctx.session_id, meta=params.meta
        )
        await self._audit(
            ctx, "goal_capture", {"goal": params.goal},
            f"{len(goal.anchors)} anchors",
        )
        return ToolResult(
            title=f"Goal {goal.name!r} captured",
            output=(
                f"Recorded goal state {goal.name!r} — {goal.width}x{goal.height}, "
                f"{len(goal.anchors)} labelled element(s) anchored.\n"
                f"  screen fingerprint: {goal.fingerprint[:12]}\n"
                "  Score a later state against it with "
                "reward(action='goal_score', goal=...)."
            ),
            metadata=goal.to_dict(),
        )

    async def _goal_score(self, ctx, params) -> ToolResult:
        from opendesk.learning.goal_state import score_goal

        if not params.goal:
            return ToolResult(
                title="Goal score",
                output="action='goal_score' needs a 'goal' name.",
                error=True,
            )
        try:
            score = await score_goal(
                params.goal, ctx, session_id=ctx.session_id,
                min_similarity=params.min_similarity,
            )
        except KeyError as exc:
            return ToolResult(title="Goal score", output=str(exc), error=True)

        await self._audit(
            ctx, "goal_score", {"goal": params.goal}, f"score={score.score:.3f}"
        )
        lines = [
            f"Goal {score.goal!r}: {'REACHED' if score.reached else 'not reached'}",
            f"  score {score.score:.1%} (threshold {score.threshold:.0%})",
            f"  {score.detail}",
        ]
        if score.missing:
            missing = ", ".join(f"{m['role']} “{m['name']}”" for m in score.missing[:8])
            lines.append(f"  missing elements: {missing}")
        return ToolResult(
            title=f"Goal score {score.score:.0%}",
            output="\n".join(lines),
            metadata=score.to_dict(),
        )

    async def _goal_list(self, ctx, params) -> ToolResult:
        from opendesk.learning.goal_state import get_goal, list_goals

        names = list_goals(ctx.session_id)
        if not names:
            return ToolResult(
                title="Goal states",
                output="No goal states recorded. Use reward(action='goal_capture', goal=...).",
            )
        lines = [f"{len(names)} goal state(s):"]
        for n in names:
            g = get_goal(n, ctx.session_id)
            lines.append(
                f"  {n!r} — {g.width}x{g.height}, {len(g.anchors)} anchor(s), "
                f"screen {g.fingerprint[:8]}"
            )
        return ToolResult(title="Goal states", output="\n".join(lines),
                          metadata={"goals": names})

    async def _episodes(self, ctx, params) -> ToolResult:
        from opendesk.learning.trajectories import list_episodes

        eps = list_episodes(ctx.session_id)
        if not eps:
            return ToolResult(
                title="Episodes",
                output="No episodes recorded. Start one with reward(action='begin').",
            )
        lines = [f"{len(eps)} episode(s) in session {ctx.session_id!r}:\n"]
        for ep in eps:
            status = "closed" if ep.finished else "open"
            rew = f"reward={ep.reward:.0f}" if ep.reward is not None else "reward=—"
            lines.append(
                f"  [{status}] {ep.id}  {rew}  {ep.task[:60]}"
            )
        return ToolResult(
            title=f"Episodes ({len(eps)})",
            output="\n".join(lines),
            metadata={"episodes": [e.to_dict() for e in eps]},
        )

    # ------------------------------------------------------------------

    @staticmethod
    async def _audit(ctx, action: str, params: dict, result: str) -> None:
        try:
            from opendesk.computer.sandbox import ActionType, get_sandbox

            await get_sandbox(ctx.session_id).record_action(
                ActionType(action), params=params, result=result
            )
        except Exception:
            pass
