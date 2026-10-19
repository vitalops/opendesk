# Automation — Learn, Replay & Schedule

opendesk lets you record any desktop workflow, replay it on demand, and schedule it to run automatically. All three features work together as one system.

## How it works

```
Record a task once  →  opendesk captures clicks, keys, and screenshots
                    →  Agent summarizes into a reusable procedure JSON
                    →  Saved to .opendesk/learned/<name>.json
                    →  Replay anytime — agent re-executes using live tools
                    →  Schedule it — runs automatically on a timer
```

## Ask Claude

> "Watch me fill out this form and remember it as expense-report"

> "Replay the expense-report task"

> "Schedule expense-report to run every Friday at 5pm"

> "What tasks have you learned?"

> "List my schedules"

---

## Guides

- [In Claude Code](claude-code.md) — record, replay, and schedule via natural language
- [Python API](python-api.md) — `learn` and `schedule` tool usage
- [Scheduler](scheduler.md) — background daemon, timing formats, storage, platform support
- [Compiled replay](compiled-replay.md) — deterministic, LLM-free `learn run` with postconditions, self-heal and `patch`
