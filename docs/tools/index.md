# Tools Reference

All tools share the same interface: `await tool.execute(ctx, params) -> ToolResult`.

**Tool priority rule:** scripts / APIs when no visual interaction is needed → `ui` → `screenshot(marks=True)` → `mouse` with image dimensions.

| Tool | Kind | Description |
|---|---|---|
| [`script`](script.md) | acts | Run a script or API call when the task needs no GUI |
| [`ui`](ui.md) | acts | Accessibility-based UI interaction — click by name, type, read values |
| [`screenshot`](screenshot.md) | read-only | Screen capture with optional Set-of-Marks overlay |
| [`mouse`](mouse.md) | acts | Pixel-level mouse control with HiDPI coordinate translation |
| [`keyboard`](keyboard.md) | acts | Type text, press keys, send hotkeys |
| [`app`](app.md) | acts | Open, close, focus, and list applications |
| [`clipboard`](clipboard.md) | changes state | Read and write clipboard text |
| [`ocr`](ocr.md) | read-only | Extract text from any screen region |
| [`browser`](browser.md) | acts | Drive a web browser through its automation interface |
| [`audit`](audit.md) | acts (replay) | Read the session audit log, replay a session |
| [`learn`](learn.md) | acts | Record and replay desktop workflows |
| `schedule` | acts | Run a task or learned workflow on a timer (see [Scheduler](../automation/scheduler.md)) |
| [`memory`](memory.md) | read-only | Screen memory — search a local, OCR'd history of what was on screen |
| [`memory_manage`](memory.md) | acts | Pause / resume capture, deny list, config, delete history |
| [`reward`](reward.md) | acts | Declare and check machine-verifiable success criteria |
| [`diagnose`](diagnose.md) | read-only | Where a session's actions looped, stalled or had no effect |
| [`fleet`](fleet.md) | acts | Run a task across several paired machines |

**Kind** mirrors the MCP annotations each tool declares: *read-only* tools set `readOnlyHint: true`;
*acts* tools set `destructiveHint: true` because they change the desktop or stored data; `clipboard` changes
state but is marked non-destructive. Every tool also has a human-readable `title`. MCP clients use these hints to
decide what to confirm with you. The peer admin tools (`opendesk_*`) are listed in [MCP](../mcp/index.md).

---

## ToolResult

All tools return:

```python
@dataclass
class ToolResult:
    title: str           # short human-readable label
    output: str          # text returned to the LLM
    error: bool          # True if the action failed
    attachments: list[Attachment]  # binary files (screenshots, etc.)
    metadata: dict       # extra data for programmatic consumers
```

`Attachment`:

```python
@dataclass
class Attachment:
    filename: str
    content: bytes
    media_type: str      # e.g. "image/png"

    def to_base64(self) -> str: ...
```

---

Start with the primary interaction tool: [ui →](ui.md)
