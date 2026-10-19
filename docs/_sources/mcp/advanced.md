# Advanced: HTTP Transport, In-process Server & Restrictions

## Streamable HTTP transport

stdio is the default. For clients that connect over HTTP, or to run the server in one process and connect
from another, start it with the streamable HTTP transport:

```bash
opendesk-mcp --transport http --host 127.0.0.1 --port 8765
opendesk mcp --http --port 8765                  # same thing via the main CLI
uvx opendesk mcp --http --port 8765              # no install
opendesk-js mcp --http --port 8765               # JavaScript server
```

The endpoint is `http://127.0.0.1:8765/mcp`.

**Bearer auth is on by default.** Every request must send `Authorization: Bearer <token>`. The token is taken from:

1. `--token <value>`
2. else `$OPENDESK_MCP_TOKEN`
3. else generated once and stored in `~/.opendesk/mcp-token` (mode 0600), then reused

The server prints the token on start.

Safety rules:

- `--no-auth` disables the token, and is only accepted on loopback addresses (`127.0.0.1`, `::1`, `localhost`).
- Binding to a non-loopback address (e.g. `--host 0.0.0.0`) refuses to start without auth and prints a warning:
  anyone with the token controls this desktop. Prefer [paired remote peers](../remote/index.md), which are end-to-end encrypted.
- On loopback binds, requests with a foreign `Host` or `Origin` header are rejected (DNS-rebinding protection).

Client config:

```json
{
  "mcpServers": {
    "opendesk": {
      "type": "http",
      "url": "http://127.0.0.1:8765/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Claude Code:

```bash
claude mcp add --transport http opendesk http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $(cat ~/.opendesk/mcp-token)"
```

---

## What the server tells the agent

**Titles and annotations.** Every tool has a human-readable `title` and MCP annotations so clients can decide
what needs confirmation:

| Hint | Meaning | Tools |
|------|---------|-------|
| `readOnlyHint: true` | Only observes | `screenshot`, `ocr`, `memory`, `opendesk_peers`, `opendesk_status`, `opendesk_describe`, `opendesk_capabilities`, `opendesk_discover` |
| `destructiveHint: true` | Acts on the desktop or deletes data | `mouse`, `keyboard`, `app`, `ui`, `learn`, `schedule`, `audit` (replay), `memory_manage` |
| `destructiveHint: false` | Changes state, safely | `clipboard`; `opendesk_use` and `opendesk_disconnect` (also `idempotentHint: true`) |
| `openWorldHint: true` | Touches the real desktop or network | the input tools, `opendesk_discover`, `opendesk_capabilities` |

**Errors.** Failed calls (tool errors, invalid arguments, unknown tools or peers, denied permissions, exceptions)
return `isError: true` with an `ERROR: …` message. Missing macOS permissions include the fix
(which app needs Accessibility / Screen Recording, and `opendesk check --open`).

**Instructions.** On initialize the server sends `instructions` describing the preferred workflow:

1. If no visual interaction is needed, use scripts or APIs instead of the GUI.
2. `ui` (accessibility API): inspect the tree, act on elements by name.
3. `screenshot(marks=true)` when the tree isn't enough.
4. `mouse` / `keyboard` as a last resort, with coordinates scaled from the latest screenshot.
5. Verify each state-changing step with a fresh screenshot.

It also covers remote peers (`opendesk_peers`, `opendesk_use`, the `peer` argument), screen memory
(`memory` to search, `memory_manage` to control), and safety: some actions may need user approval, denied calls
must not be retried, and the user's kill switch halts everything.

---

## Running the MCP server in Python

If you need to embed the server in your own process or customize permissions:

```python
import asyncio
from mcp.server.stdio import stdio_server
from opendesk.integrations.mcp import create_mcp_server
from opendesk.registry import create_registry
from opendesk.tools.base import PermissionDeniedError

# Custom permission policy: block any app launch
async def my_policy(tool: str, argument: str, description: str) -> None:
    if tool == "app" and "open" in argument:
        raise PermissionDeniedError("App launching is disabled in this session.")

server = create_mcp_server(registry=create_registry(), permission_handler=my_policy)

async def main():
    async with stdio_server() as (r, w):
        await server.run(r, w, server.create_initialization_options())

asyncio.run(main())
```

A denied action comes back to the agent as an `isError: true` result.

To serve it over HTTP instead, wrap it with `opendesk.integrations.mcp_http.build_http_app(server, token=...)`
and run the returned ASGI app with uvicorn.

---

## Restricting what the agent can do

Lock down the sandbox before starting the server. MCP calls on the local machine use the session id `mcp-local`:

```python
from opendesk.computer.sandbox import configure_sandbox

# Only allow Safari and Terminal; only act within the left half of the screen
configure_sandbox(
    session_id="mcp-local",
    allowed_apps=["Safari", "Terminal"],
    screen_region=(0, 0, 1280, 1600),
)

server = create_mcp_server()
```

All screenshots and mouse clicks outside `(0,0,1280,1600)` will be rejected with an error
the LLM sees, so it knows to stay in bounds.

---

## Audit log

Every action is recorded in the session sandbox:

```python
from opendesk.computer.sandbox import get_sandbox

sandbox = get_sandbox("mcp-local")
print(sandbox.summary())
# session=mcp-local | 12 actions: 3x screenshot, 4x ui_action, 2x keyboard_type, 3x mouse_click

log = sandbox.export_audit_log()
# [{"id": "...", "timestamp": 1234567890.0, "action": "screenshot", "params": {...}, ...}, ...]
```

The agent can read the same log with the `audit` tool.

### Custom permission handler with MCP

```python
from opendesk.tools.base import PermissionDeniedError

BLOCKED_APPS = {"System Settings", "Keychain Access"}

async def policy(tool: str, argument: str, description: str) -> None:
    for blocked in BLOCKED_APPS:
        if blocked.lower() in argument.lower():
            raise PermissionDeniedError(f"Blocked: {blocked}")

server = create_mcp_server(permission_handler=policy)
```

---

Something not working? Check the [Troubleshooting guide →](troubleshooting.md)
