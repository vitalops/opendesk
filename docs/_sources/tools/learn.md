# `learn` — Record and Replay Tasks

```python
from opendesk.tools.learn import LearnTool
tool = LearnTool()
```

Requires `pip install 'opendesk[learn]'` (installs `pynput`).

## Actions

| Action | Parameters | Description |
|--------|-----------|-------------|
| `start` | `task_name` | Begin recording mouse, keyboard, and screenshots globally |
| `stop` | — | Stop recording; returns trajectory summary and screenshots |
| `save` | `task_name`, `procedure` | Save a procedure JSON string to `.opendesk/learned/` |
| `replay` | `task_name` | Load a procedure and return step-by-step replay instructions |
| `list` | — | List all saved procedures in the current directory (`[compiled]` marks tasks with a program) |
| `compile` | `task_name`, `source?`, `program?`, `description?` | Build `<name>.program.json` from the recorded trajectory, from this session (`source="session"`), or from program JSON you supply |
| `save_session` | `task_name`, `description?`, `session_id?` | Compile this session's audited actions into a program (and a basic procedure if none exists) |
| `run` | `task_name`, `start_at?` | Execute the compiled program deterministically, with no LLM, and verify postconditions. On failure, returns a self-heal result with the failed step, reason, screenshot, remaining steps and NL procedure |
| `patch` | `task_name`, `step_id?`, `step`, `mode?` | Replace, insert or delete one program step (`replace`, `insert_before`, `insert_after`, `append`, `delete`) |
| `show` | `task_name` | Print the compiled program |

## Ask Claude

**Recording a workflow:**
> "Watch me fill out this form and remember it as 'expense-report'"

Claude will call `learn(start)`, wait for you to perform the task, then call `learn(stop)` and summarize what it saw.

**Replaying a saved workflow:**
> "Replay the expense-report task"
> "Run the fill-form procedure again"

**Listing saved workflows:**
> "What tasks have you learned?"
> "Show me all saved procedures"

!!! note
    `learn` + `replay` teaches Claude to re-execute a workflow using *current screen state* — it adapts to the environment rather than replaying raw coordinates. For exact action-by-action replay of a session, use [`audit(action='replay')`](audit.md) instead.

---

## SDK examples

```python
params = LearnTool.Params

# Start recording
await tool.execute(ctx, params(action="start", task_name="fill-form"))

# ... user performs the task ...

# Stop and review trajectory
result = await tool.execute(ctx, params(action="stop"))
print(result.output)

# Save procedure (JSON string)
import json
procedure = json.dumps({
    "task_name": "fill-form",
    "description": "Fill and submit the expense form",
    "steps": ["Open the form", "Fill in fields", "Click Submit"],
    "procedure": "Navigate to the form application. Fill each required field. Submit."
})
await tool.execute(ctx, params(action="save", task_name="fill-form", procedure=procedure))

# Replay
result = await tool.execute(ctx, params(action="replay", task_name="fill-form"))
print(result.output)  # step-by-step instructions for the agent

# List all
result = await tool.execute(ctx, params(action="list"))
print(result.output)
```

For deterministic, LLM-free replay (`compile`, `save_session`, `run`, `patch`, `show`) see [Compiled replay](../automation/compiled-replay.md).

See [Automation](../automation/index.md) for the full guide including scheduling, storage format, and platform support.
