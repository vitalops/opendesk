"""Verifiable rewards — machine-checkable success criteria for a task.

This is the RLVR (reinforcement-learning-with-verifiable-rewards) half of the
learning layer: for a computer-use task, declare what "done" means as a list of
predicates that can be checked against the live machine, then score a run
against them.

Every predicate is decided by *observing state* — a file on disk, a shell exit
code, an element in the accessibility tree, a screenshot — never by asking a
model.  That is what makes the reward verifiable: the same task scored twice
gives the same answer, and a reviewer can see the evidence behind each verdict.

A reward spec is plain data::

    {
      "task": "Write a 3-line report to report.txt",
      "mode": "all",                 # "all" | "any" | "weighted"
      "checks": [
        {"kind": "file_exists", "path": "~/report.txt"},
        {"kind": "file_contains", "path": "~/report.txt", "regex": "^total:"},
        {"kind": "shell", "command": "wc -l < ~/report.txt", "stdout_regex": "^3$"},
        {"kind": "screen_matches", "goal": "done", "category": "ui", "weight": 0.5}
      ]
    }

Reward semantics
----------------
``reward``  binary — ``1.0`` when every *required* check passes (RLVR signal)
``score``   dense — weighted fraction of required checks that passed
``mode``    ``all`` (default) → binary reward; ``any`` → reward if one passes;
            ``weighted`` → reward equals the dense score

Optional checks (``required: false``) are evaluated and reported but never
affect the reward — useful for diagnostics.

Supported check kinds
---------------------
``file_exists``, ``file_absent``, ``file_contains``, ``shell``,
``clipboard_contains``, ``clipboard_equals``, ``app_running``, ``ui_element``,
``ui_changed``, ``screen_matches``, ``screen_changed``

``ui_element`` accepts ``value_regex`` / ``value_equals`` in addition to
``role`` / ``name_regex``, which is what makes a reward *verifiable* rather than
merely visual: "the Total field reads 300" is a statement about the task, while
"the screen changed" is not.  ``ui_changed`` is the semantic counterpart of
``screen_changed`` — it compares accessibility content, so an edited glyph
counts and a ticking clock does not.

``screen_changed`` accepts an optional ``ignore_regions`` list of ``[x, y, w, h]``
boxes to exclude from the comparison — ambient churn such as a ticking clock or
a taskbar is real pixel change that says nothing about the task.  Derive the
boxes with :func:`opendesk.computer.capture.regions_for_roles` instead of
hardcoding them.
"""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

#: Check kinds this module knows how to evaluate.
CHECK_KINDS = frozenset({
    "file_exists", "file_absent", "file_contains", "shell",
    "clipboard_contains", "clipboard_equals", "app_running",
    "ui_element", "ui_changed", "screen_matches", "screen_changed",
})


@dataclass
class Check:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)
    required: bool = True
    weight: float = 1.0
    category: str = "task"
    label: Optional[str] = None

    @property
    def target(self) -> str:
        if self.label:
            return self.label
        a = self.args
        if "path" in a:
            return f"{self.kind}({a['path']})"
        if "command" in a:
            return f"shell({a['command'][:60]})"
        if "goal" in a:
            return f"screen_matches({a['goal']})"
        return self.kind

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Check":
        d = dict(d)
        kind = d.pop("kind", None)
        if not kind:
            raise ValueError("check is missing 'kind'")
        kind = str(kind)
        if kind not in CHECK_KINDS:
            raise ValueError(
                f"unknown check kind {kind!r}; supported: {sorted(CHECK_KINDS)}"
            )
        required = bool(d.pop("required", True))
        weight = float(d.pop("weight", 1.0))
        category = str(d.pop("category", "task"))
        label = d.pop("label", None)
        if "path" in d and isinstance(d["path"], str):
            d["path"] = os.path.expanduser(d["path"])
        return cls(kind=kind, args=d, required=required, weight=weight,
                   category=category, label=label)


@dataclass
class CheckResult:
    check: Check
    passed: bool
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.check.kind

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.check.kind,
            "target": self.check.target,
            "category": self.check.category,
            "required": self.check.required,
            "weight": self.check.weight,
            "passed": self.passed,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass
class RewardReport:
    """The outcome of scoring a run against a reward spec."""

    task: str
    mode: str
    results: list[CheckResult] = field(default_factory=list)

    # -- aggregation ----------------------------------------------------

    @property
    def required(self) -> list[CheckResult]:
        return [r for r in self.results if r.check.required]

    @property
    def passed(self) -> bool:
        req = self.required
        if not req:
            return True
        if self.mode == "any":
            return any(r.passed for r in req)
        return all(r.passed for r in req)

    @property
    def reward(self) -> float:
        """Binary reward — the signal an RLVR loop optimises."""
        if self.mode == "weighted":
            return self.score
        return 1.0 if self.passed else 0.0

    @property
    def score(self) -> float:
        """Dense score — weighted fraction of required checks passed."""
        req = self.required
        if not req:
            return 1.0
        total = sum(r.check.weight for r in req)
        if total <= 0:
            return 0.0
        return sum(r.check.weight for r in req if r.passed) / total

    def by_category(self) -> dict[str, dict[str, Any]]:
        """Coarse (category) → fine (per-check) breakdown."""
        out: dict[str, dict[str, Any]] = {}
        for r in self.results:
            bucket = out.setdefault(
                r.check.category, {"passed": 0, "total": 0, "checks": []}
            )
            bucket["total"] += 1
            bucket["passed"] += int(r.passed)
            bucket["checks"].append(r.to_dict())
        for bucket in out.values():
            bucket["score"] = (
                bucket["passed"] / bucket["total"] if bucket["total"] else 0.0
            )
        return out

    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if not r.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "mode": self.mode,
            "reward": round(self.reward, 4),
            "score": round(self.score, 4),
            "passed": self.passed,
            "required_total": len(self.required),
            "required_passed": sum(1 for r in self.required if r.passed),
            "checks": [r.to_dict() for r in self.results],
            "categories": {
                k: {"score": round(v["score"], 4),
                    "passed": v["passed"], "total": v["total"]}
                for k, v in self.by_category().items()
            },
        }

    def summary_text(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        lines = [
            f"[{mark}] {self.task}",
            f"  reward={self.reward:.2f}  score={self.score:.0%}  "
            f"({sum(1 for r in self.required if r.passed)}/{len(self.required)} required checks)",
        ]
        for r in self.results:
            box = "x" if r.passed else " "
            tag = "" if r.check.required else "  (optional)"
            lines.append(f"  [{box}] {r.check.target}{tag}")
            if not r.passed and r.detail:
                lines.append(f"       → {r.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Spec parsing
# ---------------------------------------------------------------------------

def parse_checks(raw: Any) -> list[Check]:
    """Validate a list of raw check dicts.

    Shared by the task's reward spec and by an agent's own assertions, because
    both are the same thing: a machine-checkable predicate over observable state.
    """
    if not isinstance(raw, list) or not raw:
        raise ValueError("needs a non-empty 'checks' list")
    return [Check.from_dict(c) for c in raw]


def parse_spec(spec: dict[str, Any]) -> tuple[str, str, list[Check]]:
    """Validate a reward spec and return ``(task, mode, checks)``."""
    if not isinstance(spec, dict):
        raise ValueError("reward spec must be a dict")
    task = str(spec.get("task") or "unnamed task")
    mode = str(spec.get("mode") or "all").lower()
    if mode not in ("all", "any", "weighted"):
        raise ValueError(f"mode must be 'all', 'any' or 'weighted', got {mode!r}")
    raw = spec.get("checks")
    if not isinstance(raw, list) or not raw:
        raise ValueError("reward spec needs a non-empty 'checks' list")
    # Delegate the rest: an unknown kind must keep reporting *which* kind, so
    # wrapping the whole call would turn a precise error into a vague one.
    return task, mode, parse_checks(raw)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

async def run_checks(
    checks: list[Check],
    *,
    ctx: Any = None,
    session_id: str = "default",
) -> list[CheckResult]:
    """Evaluate a list of checks in order, one result each.

    Every check is isolated: one that raises becomes a failed result rather than
    taking the rest of the list down with it.  A reward is a report, and a report
    that omits half its checks because the third one hit an edge case is worse
    than one that says the third one errored.
    """
    return [await _run_check(check, ctx, session_id) for check in checks]


async def evaluate(
    spec: dict[str, Any],
    *,
    ctx: Any = None,
    session_id: str = "default",
) -> RewardReport:
    """Evaluate a reward spec against the current machine state."""
    task, mode, checks = parse_spec(spec)
    return RewardReport(
        task=task, mode=mode,
        results=await run_checks(checks, ctx=ctx, session_id=session_id),
    )


async def _run_check(check: Check, ctx: Any, session_id: str) -> CheckResult:
    handler = _HANDLERS.get(check.kind)
    if handler is None:  # pragma: no cover - guarded by Check.from_dict
        return CheckResult(check, False, f"no evaluator for {check.kind!r}")
    try:
        return await handler(check, ctx, session_id)
    except Exception as exc:
        return CheckResult(check, False, f"evaluation error: {exc}")


def _ok(check: Check, detail: str = "", **evidence: Any) -> CheckResult:
    return CheckResult(check, True, detail, evidence)


def _no(check: Check, detail: str, **evidence: Any) -> CheckResult:
    return CheckResult(check, False, detail, evidence)


# -- filesystem ---------------------------------------------------------

async def _file_exists(check: Check, ctx: Any, sid: str) -> CheckResult:
    path = check.args["path"]
    if os.path.isfile(path):
        return _ok(check, f"{path} exists", path=path, bytes=os.path.getsize(path))
    if os.path.isdir(path):
        return _no(check, f"{path} is a directory, not a file", path=path)
    return _no(check, f"{path} does not exist", path=path)


async def _file_absent(check: Check, ctx: Any, sid: str) -> CheckResult:
    path = check.args["path"]
    if os.path.exists(path):
        return _no(check, f"{path} still exists", path=path)
    return _ok(check, f"{path} is absent", path=path)


async def _file_contains(check: Check, ctx: Any, sid: str) -> CheckResult:
    path = check.args["path"]
    needle = check.args.get("text")
    pattern = check.args.get("regex")
    if needle is None and pattern is None:
        return _no(check, "file_contains needs 'text' or 'regex'")
    if not os.path.isfile(path):
        return _no(check, f"{path} does not exist", path=path)

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
    except OSError as exc:
        return _no(check, f"cannot read {path}: {exc}", path=path)

    if pattern is not None:
        try:
            m = re.search(str(pattern), content, re.MULTILINE)
        except re.error as exc:
            return _no(check, f"invalid regex {pattern!r}: {exc}")
        if m:
            return _ok(check, f"/{pattern}/ matched {m.group(0)[:40]!r}",
                       path=path, match=m.group(0)[:200])
        return _no(check, f"/{pattern}/ not found in {path}", path=path,
                   size=len(content))

    if str(needle) in content:
        return _ok(check, f"found {str(needle)!r}", path=path)
    return _no(check, f"{str(needle)!r} not found in {path}", path=path,
               size=len(content))


# -- shell --------------------------------------------------------------

async def _shell(check: Check, ctx: Any, sid: str) -> CheckResult:
    command = str(check.args["command"])
    expect_exit = int(check.args.get("expect_exit", 0))
    stdout_regex = check.args.get("stdout_regex")
    stderr_regex = check.args.get("stderr_regex")
    timeout = float(check.args.get("timeout", 30))

    computer = getattr(ctx, "computer", None) if ctx is not None else None
    if computer is None:
        return _no(
            check,
            "no computer on this context, so the command cannot run through "
            "its safety policy",
            command=command,
        )

    # A check is not the place to bypass the safety engine: the same command
    # sent as a step goes through risk tiers and approval, and one run from a
    # reward must not be the exception.  On the local computer this is the same
    # subprocess the check used to spawn itself; on a remote one it is the
    # peer's shell, which is where the task actually happened.
    try:
        done = await computer.shell(command, timeout=timeout)
    except asyncio.TimeoutError:
        return _no(check, f"command timed out after {timeout:g}s", command=command)
    except Exception as exc:
        return _no(check, f"could not run command: {exc}", command=command)

    # Normalise CRLF so `^...$` regexes behave the same on Windows and POSIX.
    out = (done.stdout_text() if hasattr(done, "stdout_text") else str(getattr(done, "stdout", "")))
    err = (done.stderr_text() if hasattr(done, "stderr_text") else str(getattr(done, "stderr", "")))
    out = out.replace("\r\n", "\n")
    err = err.replace("\r\n", "\n")
    exit_code = getattr(done, "returncode", None)
    evidence = {
        "command": command,
        "exit_code": exit_code,
        "stdout": out[:2000],
        "stderr": err[:2000],
    }

    if exit_code != expect_exit:
        return _no(check, f"exit code {exit_code}, expected {expect_exit}", **evidence)

    if stdout_regex is not None:
        if not re.search(str(stdout_regex), out, re.MULTILINE):
            return _no(check, f"stdout did not match /{stdout_regex}/", **evidence)
    if stderr_regex is not None:
        if not re.search(str(stderr_regex), err, re.MULTILINE):
            return _no(check, f"stderr did not match /{stderr_regex}/", **evidence)

    return _ok(check, f"exit {exit_code}", **evidence)


# -- clipboard ----------------------------------------------------------

async def _clipboard_text(ctx: Any) -> Optional[str]:
    if ctx is None or getattr(ctx, "computer", None) is None:
        return None
    computer = ctx.computer
    for attr in ("clipboard_text", "clipboard_read"):
        fn = getattr(computer, attr, None)
        if fn is None:
            continue
        try:
            value = await fn()
        except Exception:
            continue
        if isinstance(value, str):
            return value
        text = getattr(value, "text", None)
        if callable(text):
            try:
                text = text()
            except Exception:
                text = None
        if isinstance(text, str):
            return text
    return None


async def _clipboard_contains(check: Check, ctx: Any, sid: str) -> CheckResult:
    text = await _clipboard_text(ctx)
    if text is None:
        return _no(check, "clipboard is not available in this environment")
    needle = str(check.args.get("text", ""))
    if needle in text:
        return _ok(check, f"clipboard contains {needle[:40]!r}", length=len(text))
    return _no(check, f"clipboard does not contain {needle[:40]!r}",
               clipboard=text[:500])


async def _clipboard_equals(check: Check, ctx: Any, sid: str) -> CheckResult:
    text = await _clipboard_text(ctx)
    if text is None:
        return _no(check, "clipboard is not available in this environment")
    expected = str(check.args.get("text", ""))
    if text.strip() == expected.strip():
        return _ok(check, "clipboard matches", length=len(text))
    return _no(check, f"clipboard is {text[:80]!r}, expected {expected[:80]!r}",
               clipboard=text[:500])


# -- applications -------------------------------------------------------

async def _app_running(check: Check, ctx: Any, sid: str) -> CheckResult:
    if ctx is None or getattr(ctx, "computer", None) is None:
        return _no(check, "no computer available")
    try:
        apps = await ctx.computer.list_apps()
    except Exception as exc:
        return _no(check, f"could not list applications: {exc}")

    needle = str(check.args.get("name", "")).lower()
    if needle in [str(a).lower() for a in apps]:
        return _ok(check, f"{needle!r} is running", apps=list(apps)[:50])
    matched = [a for a in apps if needle in str(a).lower()]
    if matched:
        return _ok(check, f"{matched[0]!r} matches", apps=list(apps)[:50])
    return _no(check, f"no running application matches {needle!r}",
               apps=list(apps)[:50])


# -- UI tree ------------------------------------------------------------

async def _ui_element(check: Check, ctx: Any, sid: str) -> CheckResult:
    if ctx is None or getattr(ctx, "computer", None) is None:
        return _no(check, "no computer available")
    role = check.args.get("role")
    name_regex = check.args.get("name_regex")
    value_regex = check.args.get("value_regex")
    value_equals = check.args.get("value_equals")
    if value_equals is None:
        value_equals = check.args.get("value")
    content_regex = check.args.get("content_regex")
    present = bool(check.args.get("present", True))

    try:
        tree = await ctx.computer.ui_tree()
    except Exception as exc:
        return _no(check, f"could not read accessibility tree: {exc}")

    from opendesk.computer.a11y import flatten_nodes

    # Each criterion is optional and they combine with AND, so a spec can be as
    # loose as "a Save button exists" or as tight as "the Total field reads 300".
    role_needle = str(role).lower() if role else None
    name_re = re.compile(str(name_regex), re.IGNORECASE) if name_regex is not None else None
    value_re = re.compile(str(value_regex), re.IGNORECASE) if value_regex is not None else None
    content_re = re.compile(str(content_regex), re.IGNORECASE) if content_regex is not None else None

    found: list[dict[str, Any]] = []
    for node in flatten_nodes(tree):
        if role_needle and role_needle not in node.role.lower():
            continue
        if name_re is not None and not name_re.search(node.name):
            continue
        if value_re is not None and not value_re.search(node.value):
            continue
        if value_equals is not None and node.value != str(value_equals):
            continue
        if content_re is not None and not content_re.search(node.content):
            continue
        found.append({
            "role": node.role,
            "name": node.name[:80],
            "value": node.value[:80],
            "content": node.content[:80],
        })

    looked_for = {
        k: v for k, v in (
            ("role", role), ("name_regex", name_regex),
            ("value_regex", value_regex), ("value", value_equals),
            ("content_regex", content_regex),
        ) if v is not None
    }
    if present:
        if found:
            return _ok(check, f"found {len(found)} matching element(s)",
                       matches=found[:10])
        return _no(check, "no matching element in the accessibility tree",
                   **looked_for)
    if found:
        return _no(check, f"element is still present ({found[0]})", matches=found[:10])
    return _ok(check, "element is absent", **looked_for)


async def _ui_changed(check: Check, ctx: Any, sid: str) -> CheckResult:
    """Did the accessibility content change since the reference?

    The semantic counterpart of :func:`_screen_changed`.  Comparing pixels
    cannot separate a useful edit from ambient churn — a ticking clock and a
    one-glyph change are both a few dozen pixels — but comparing *content* can,
    because one is a string that changed and the other is not.

    The reference comes from the observation memory, so capturing with
    ``tree=true`` is what populates it; without that the check says so rather
    than guessing.
    """
    ref = check.args.get("ref", "previous")
    try:
        from opendesk.computer.observations import get_store

        store = get_store(sid)
        obs = store.resolve(ref)
        if obs is None:
            return _no(check, f"no stored observation matches {ref!r}")
        current = store.latest()
        if current is None or current.index == obs.index:
            return _no(check, "no newer observation to compare against",
                       reference=obs.index)
    except Exception as exc:
        return _no(check, f"could not read observation memory: {exc}")

    if obs.ui_snapshot is None or current.ui_snapshot is None:
        missing = [
            f"#{o.index}" for o in (obs, current) if o.ui_snapshot is None
        ]
        return _no(
            check,
            f"no accessibility content recorded for observation(s) "
            f"{', '.join(missing)} — capture with tree=true to enable this check",
            reference=obs.index, current=current.index,
        )

    from opendesk.computer.a11y import AMBIENT_ROLES, diff_snapshots, filter_snapshot

    # Ambient furniture is pruned by default, as it is everywhere else the
    # content identity is used.  This check answers "did the content change", so
    # a menu-bar clock ticking must not count — otherwise a verifiable predicate
    # reports a change that never happened.  Pass ``ignore_roles: []`` to
    # compare everything.
    ignore_roles = check.args.get("ignore_roles", AMBIENT_ROLES)
    try:
        diff = diff_snapshots(
            filter_snapshot(obs.ui_snapshot, ignore_roles),
            filter_snapshot(current.ui_snapshot, ignore_roles),
        )
    except Exception as exc:
        return _no(check, f"could not compare accessibility content: {exc}")

    evidence = {
        "reference": obs.index,
        "current": current.index,
        "content_changes": diff.content_changes,
        "ignored_roles": list(ignore_roles) if ignore_roles else [],
        "matched": diff.matched,
        "modified": [c.describe() for c in diff.modified[:10]],
        "added": [c.describe() for c in diff.added[:10]],
        "removed": [c.describe() for c in diff.removed[:10]],
        "moved": [c.describe() for c in diff.moved[:10]],
    }
    if diff.changed:
        return _ok(check, diff.summary(), **evidence)
    return _no(check, "accessibility content is unchanged since the reference",
               **evidence)


# -- screens ------------------------------------------------------------

async def _screen_matches(check: Check, ctx: Any, sid: str) -> CheckResult:
    goal_name = str(check.args["goal"])
    min_similarity = float(check.args.get("min_similarity", 0.80))
    try:
        from opendesk.learning.goal_state import score_goal

        score = await score_goal(
            goal_name, ctx, session_id=sid, min_similarity=min_similarity
        )
    except KeyError as exc:
        return _no(check, str(exc))
    except Exception as exc:
        return _no(check, f"could not score goal: {exc}")

    evidence = score.to_dict()
    if score.reached:
        return _ok(check, f"reached goal {goal_name!r} ({score.detail})", **evidence)
    return _no(check, f"not at goal {goal_name!r} ({score.detail})", **evidence)


async def _screen_changed(check: Check, ctx: Any, sid: str) -> CheckResult:
    ref = check.args.get("ref", "previous")
    try:
        from opendesk.computer.observations import get_store

        store = get_store(sid)
        obs = store.resolve(ref)
        if obs is None:
            return _no(check, f"no stored observation matches {ref!r}")
        current = store.latest()
        if current is None or current.index == obs.index:
            return _no(check, "no newer observation to compare against",
                       reference=obs.index)

        from functools import partial

        from opendesk.computer.capture import diff_screenshots

        # `ignore_regions` lets a spec exclude ambient churn (a clock, a
        # taskbar) whose pixels genuinely change but which carries no signal
        # about the task.
        regions = check.args.get("ignore_regions")
        loop = asyncio.get_event_loop()
        diff = await loop.run_in_executor(
            None, partial(diff_screenshots, obs.png, current.png,
                          ignore_regions=regions)
        )
    except Exception as exc:
        return _no(check, f"could not compare screens: {exc}")

    changed = bool(diff.get("changed"))
    evidence = {
        "reference": obs.index,
        "current": current.index,
        "change_fraction": diff.get("change_fraction"),
        "changed_pixels": diff.get("changed_pixels"),
        "suppressed_pixels": diff.get("suppressed_pixels"),
        "ignored_regions": diff.get("ignored_regions"),
    }
    if changed:
        return _ok(check, diff.get("summary", "changed"), **evidence)
    return _no(check, "screen is unchanged since the reference", **evidence)


_HANDLERS = {
    "file_exists": _file_exists,
    "file_absent": _file_absent,
    "file_contains": _file_contains,
    "shell": _shell,
    "clipboard_contains": _clipboard_contains,
    "clipboard_equals": _clipboard_equals,
    "app_running": _app_running,
    "ui_element": _ui_element,
    "ui_changed": _ui_changed,
    "screen_matches": _screen_matches,
    "screen_changed": _screen_changed,
}
