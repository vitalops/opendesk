# Python Quickstart

## Install

```bash
pip install opendesk
```

This includes the MCP server and local computer use. The `core` and `mcp` extras are kept as aliases, so `pip install 'opendesk[core,mcp]'` still works.

Register the MCP server with Claude Code globally:

```bash
opendesk install
```

To remove:

```bash
opendesk uninstall
```

No install at all? With [uv](https://docs.astral.sh/uv/) you can run the server directly:

```bash
uvx opendesk mcp                          # or: uvx --from opendesk opendesk-mcp
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
```

On macOS, grant permissions first: `opendesk check --open` (see [Permissions](permissions.md)).

## Try it via Claude

Once registered, open Claude Code and ask:

> "Take a screenshot and describe what's on my screen"

> "Open Safari and go to google.com"

> "Click the first button you see"

> "Show me the audit log"

> "Replay everything you just did"

Claude calls the tools automatically — no code needed.

---

## SDK examples

### 1. Take a screenshot

```python
import asyncio
from opendesk import create_registry, allow_all_context

async def main():
    registry = create_registry()
    ctx = allow_all_context()

    screenshot = registry.get("screenshot")
    result = await screenshot.execute(ctx, screenshot.Params(marks=True))

    png = result.attachments[0].content
    with open("screenshot.png", "wb") as f:
        f.write(png)
    print(result.output)

asyncio.run(main())
```

## 2. Click a button by name

```python
ui = registry.get("ui")
await ui.execute(ctx, ui.Params(action="click", app="TextEdit", title="File"))
```

## 3. Type text

```python
kb = registry.get("keyboard")
await kb.execute(ctx, kb.Params(action="type", text="Hello, World! 🌍"))
await kb.execute(ctx, kb.Params(action="press", key="enter"))
```

## 4. Full agentic loop

```python
import anthropic
from opendesk.integrations.claude_code import ClaudeCodeAdapter
from opendesk.registry import create_registry

client = anthropic.Anthropic()
adapter = ClaudeCodeAdapter(create_registry())

messages = [{"role": "user", "content": "Open TextEdit, type 'Hello', save the file."}]
result = await adapter.run_loop(
    client=client,
    model="claude-opus-4-6",
    messages=messages,
    system="You are a computer use agent. Use the ui tool first. Mouse is a last resort.",
)
```

## 5. Permission modes

```python
from opendesk.tools.base import allow_all_context, interactive_context, ToolContext, PermissionDeniedError

ctx = allow_all_context()    # approve everything automatically
ctx = interactive_context()  # prompt in terminal before each action

async def my_policy(tool: str, argument: str, description: str) -> None:
    if tool == "app":
        raise PermissionDeniedError("App launching is restricted.")

ctx = ToolContext(session_id="safe", permission_handler=my_policy)
```

## 6. Restrict the sandbox

```python
from opendesk.computer.sandbox import configure_sandbox
from opendesk.tools.base import ToolContext

configure_sandbox(
    session_id="restricted",
    allowed_apps=["Firefox", "Terminal"],
    screen_region=(0, 0, 1280, 800),
)
ctx = ToolContext(session_id="restricted")
```

---

## Next steps

- [Tools reference](../tools/index.md) — full parameter docs for every tool
- [Integrations](../integrations/index.md) — MCP, OpenAI, LangChain, Vercel AI SDK
- [Architecture](../architecture/index.md) — how the layers fit together
