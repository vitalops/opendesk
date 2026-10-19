# Scheduler

## Ask Claude

> "Schedule a task called daily-backup to run every day at 9am"

> "Schedule expense-report to run every Friday at 5pm"

> "List my scheduled tasks"

> "Run the daily-backup task now"

> "Remove the hourly-check schedule"

Claude adds, lists, and removes schedules. Start the daemon separately so they actually run:

```bash
opendesk scheduler start
```

---

## Start the background runner

Schedules are saved to disk but only execute when the daemon is running:

```bash
opendesk scheduler start
```

To list schedules without starting the daemon:

```bash
opendesk scheduler list
```

`replay <name>` tasks run the task's [compiled program](compiled-replay.md) first, with no LLM and no API key. They fall back to an LLM only when there is no program or it stops at a step.

Natural-language tasks, and replay fallbacks, need Claude: either the Anthropic API, or headless Claude Code (`claude -p`, using your subscription login) when no API key is set and the `claude` CLI is installed:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENDESK_MODEL=claude-sonnet-4-6  # optional, this is the default
opendesk scheduler start
```

---

## Timing formats

| Format | Example | Meaning |
|--------|---------|---------|
| Interval | `every 30m` | Every 30 minutes |
| Interval | `every 2h` | Every 2 hours |
| Interval | `every 1d` | Every day |
| Daily | `every day at 09:00` | Daily at 9am |
| Weekly | `every friday at 17:00` | Every Friday at 5pm |
| Weekly | `every monday at 8am` | Every Monday at 8am |
| Cron | `0 17 * * 5` | Raw cron expression |

---

## Installation

```bash
pip install 'opendesk[learn]'     # recording and replay (pynput)
pip install 'opendesk[schedule]'  # scheduled tasks (apscheduler)
pip install 'opendesk[all]'       # everything
```

---

## Storage

Procedures: `.opendesk/learned/<name>.json`  
Schedules: `.opendesk/schedules.json`

Both are plain JSON — you can edit, share, or version-control them.

---

## Platform support

| Feature | macOS | Linux | Windows |
|---------|-------|-------|---------|
| Recording | ✓ | ✓ | ✓ |
| Accessibility context (optional) | atomacos | pyatspi | pywinauto |
| Replay | ✓ | ✓ | ✓ |
| Scheduling | ✓ | ✓ | ✓ |

---

That's the full automation system. If you want to run tasks on a remote machine, check out [Remote Computer Use →](../remote/index.md)
