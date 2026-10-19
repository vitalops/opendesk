# Compiled replay — deterministic `learn` programs

`learn(action="replay")` hands a natural-language procedure to an agent, which re-plans every step with an LLM. That adapts well but is slow, costs tokens, and needs an API key or a Claude login.

A **compiled program** is the same learned task turned into a fixed list of tool calls that target UI elements by **semantic identity** (app, role, title, accessibility identifier), not pixel coordinates. Each step can carry a **postcondition** that is checked after it runs. `learn(action="run")` executes the program with **no LLM**. If a step can't be completed, the run stops and returns a **self-heal** result so an agent can finish the task and then fix the program.

```
record / do the task once ──► learn(stop) or learn(save_session)
                                     │
                     <name>.json (NL procedure)  +  <name>.program.json (compiled)
                                     │
                         learn(run) ── ok ──► done (no LLM, no API key)
                                     │
                                  failed step
                                     ▼
          self-heal: failed step + reason + screenshot + remaining steps + NL procedure
                                     ▼
                agent finishes the task ──► learn(patch) ──► next run passes
```

## Ask Claude

> "Remember what you just did as `export-report`." → `learn(action="save_session", task_name="export-report")`

> "Run export-report." → `learn(action="run", task_name="export-report")`

> "Show me the compiled steps for export-report." → `learn(action="show", ...)`

> "That step targets the wrong button. Patch it to click 'Export…'." → `learn(action="patch", ...)`

---

## Files

```
<project>/.opendesk/learned/
  export-report.json             # NL procedure (learn save / replay)
  export-report.program.json     # compiled program (learn compile / run / patch)
  export-report.trajectory.json  # raw recording, no screenshots (written by learn stop)
```

`learn(action="list")` shows only procedures and tags the compiled ones with `[compiled]`.

## Program format

```json
{
  "name": "export-report",
  "version": 1,
  "description": "Export the weekly report as PDF",
  "source": "trajectory",
  "steps": [
    {"id": "s1", "tool": "app", "params": {"action": "open", "name": "Numbers"},
     "target": {"app": "Numbers"},
     "postcondition": {"kind": "app_frontmost", "value": "Numbers"}, "wait_ms": 500},
    {"id": "s2", "tool": "ui", "params": {"action": "click_menu", "menu": "File", "menu_item": "Export To"},
     "target": {"app": "Numbers"}, "wait_ms": 300},
    {"id": "s3", "tool": "ui", "params": {"action": "click"},
     "target": {"app": "Numbers", "role": "AXButton", "title": "PDF", "identifier": "export-pdf"},
     "postcondition": {"kind": "window_title_contains", "value": "Export", "timeout_ms": 5000},
     "wait_ms": 300}
  ]
}
```

| Field | Meaning |
|---|---|
| `id` | Stable step id (`s1`, `s2`, …). Ids are never renumbered, so self-heal output and patches keep pointing at the right step. |
| `tool` | `ui`, `keyboard`, `app`, `mouse`, `clipboard`, or `wait`. |
| `params` | That tool's parameters. For `ui` steps the app, role and title come from `target`. |
| `target` | `app`, `role`, `title`, `identifier`, and optional `ref`. |
| `postcondition` | `app_frontmost`, `window_title_contains`, `element_exists` (a string title or a target-like dict), or `text_visible`. `timeout_ms` defaults to 5000. |
| `wait_ms` | Pause after the action, before the postcondition is checked. |
| `note` | Free text. The compiler uses it to flag brittle steps, such as coordinate fallbacks. |

### How targets are resolved

`ui click`, `mouse` clicks with an element target, and `ui get_value` look the element up in `computer.ui_tree(app=target.app)`. Lookup is retried until `resolve_timeout_ms` (default 5 s) runs out, in this order:

1. **`ref`**: used when a node carries the same ref (as `UIElement.ref` or `metadata["ref"]`) **and** that node still matches the role and title. Stale refs are ignored rather than trusted.
2. **`identifier`**: the accessibility identifier (`AXIdentifier`, UIA AutomationId, `metadata["identifier"]`).
3. **Role plus exact title**, then **role plus substring title**. Matching is case-insensitive, and `AXButton`, `button` and `push button` all count as the same role. If several elements match, one that can be clicked wins.

Clicks use the native accessibility action when the backend has one, and otherwise click the centre of the element's bounds. Other steps, such as typing, pressing keys and app actions, go through the normal tools, so permissions and the audit log behave as usual.

### Postconditions

| Kind | Checked against |
|---|---|
| `app_frontmost` | `computer.focused_window().app_name` |
| `window_title_contains` | The focused window title, falling back to the UI-tree window name |
| `element_exists` | A target lookup in the UI tree |
| `text_visible` | Element names and values in the UI tree, with one OCR attempt at the deadline as a fallback |

Each postcondition is polled every 250 ms until `timeout_ms` runs out.

---

## Where programs come from

### 1. A recording (`learn start` → `learn stop`)

The recorder captures accessibility context (app, window, role, title, identifier) for every click and keystroke. `learn(stop)` saves the trajectory without screenshots and **compiles a program automatically**. The compiler:

* adds an `app open`/`focus` step with an `app_frontmost` check whenever the frontmost app changes
* turns clicks on identified elements into `ui click` steps, and double or right clicks into `mouse` steps that still target the element
* uses the window title seen at the *next* event as the step's `window_title_contains` postcondition
* turns typed text into `ui type` and shortcuts into `ui press_key` with modifiers
* keeps clicks with no accessibility info as `mouse` coordinate steps and flags them in `note` (patch these)

To re-compile later, call `learn(action="compile", task_name=...)`.

### 2. The current session (`learn save_session`)

Every input tool records `replay_params` in the session audit log. `learn(action="save_session", task_name=...)` compiles them:

* `ui` actions become `ui` steps with app, role and title moved into `target`
* `app open/focus` steps get an `app_frontmost` check
* keyboard, mouse and clipboard actions are kept
* reads (screenshots, OCR, `get_tree`) and failed actions are dropped

If the task has no NL procedure yet, a basic one is written next to the program.

### 3. Written by the agent

`learn(action="compile", task_name=..., program='[ ...steps... ]')` validates and saves a program the agent wrote itself, for example from an NL procedure.

---

## Running

```python
from opendesk.tools.automation import LearnTool
tool = LearnTool()
P = LearnTool.Params

result = await tool.execute(ctx, P(action="run", task_name="export-report"))
if result.error:                      # self-heal needed
    heal = result.metadata["self_heal"]
    heal["failed_step"], heal["reason"], heal["remaining_steps"], heal["procedure"]
    result.attachments[0]             # screenshot at the moment of failure
```

`start_at="s4"` resumes a partial run.

### Self-heal

On failure, `run` returns `error=True` with:

* **failed step**: the full JSON for the step
* **reason**: for example `target not found after 5000 ms: no element matching [AXButton] 'PDF' in Numbers` or `postcondition window_title_contains='Export' not met within 5000 ms (window title is 'Report.numbers')`
* **screenshot**: attached as an image
* **remaining steps**: the steps after the failed one
* **NL procedure**: the original goal and steps

The text output tells the agent to finish the task with its normal tools, then repair the program:

```python
await tool.execute(ctx, P(action="patch", task_name="export-report", step_id="s3",
                          step='{"tool":"ui","params":{"action":"click"},'
                               '"target":{"app":"Numbers","role":"button","title":"Export…"}}'))
```

Patch modes are `replace` (the default when `step_id` is given), `insert_before`, `insert_after`, `append` (the default without `step_id`), and `delete`.

---

## Scheduler

`schedule(action="add", task="replay export-report", ...)` now runs the compiled program first, with no LLM and no API key. The scheduler falls back to an LLM only when:

* there is no compiled program, or
* the program stops at a step. The LLM then gets the NL procedure **plus the self-heal context** and is told to continue from the failed step instead of starting over.

The LLM fallback uses `ANTHROPIC_API_KEY` when it is set. Otherwise it uses headless Claude Code (`claude -p`, on your subscription login) if the `claude` CLI is installed.

## Learn regression in the eval harness

`opendesk eval run learn-regression --project .` runs every compiled program in `./.opendesk/learned/` deterministically and reports which ones still pass their postconditions. See [Evaluation](../eval.md).
