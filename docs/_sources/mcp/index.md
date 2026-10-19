# MCP Integration

MCP (Model Context Protocol) is how AI clients like Claude Code, Claude Desktop, Cursor, VS Code and Continue
connect to external capabilities. OpenDesk ships as an MCP server: register it once with your client and
every conversation can see and control the desktop.

Quickest start (Claude Code, needs [uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
```

---

## How it works

```
Your AI client (Claude Code / Claude Desktop / Cursor / VS Code)
       |
       | MCP over stdio (or streamable HTTP)
       v
  opendesk-mcp  <-- the server this package installs
       |
       +-- computer-use tools  (screenshot, ui, mouse, keyboard, app, clipboard, ocr)
       +-- automation tools    (learn, schedule, audit)
       +-- screen memory       (memory, memory_manage)
       +-- peer admin tools    (opendesk_peers, opendesk_use, ...)
```

The LLM decides when to call a tool, calls it, gets the result (including PNG screenshots),
and continues. You never write tool-calling code yourself.

---

## What the LLM sees

| Tool | When the LLM uses it |
|------|---------------------|
| `screenshot` | "Let me see what's on the screen" (read-only; `marks=true` numbers interactive elements) |
| `ui` | "Click the Save button" (finds it via the accessibility tree, no coordinates) |
| `mouse` | Last resort for canvas areas with no accessible elements |
| `keyboard` | "Type this text into the field" |
| `app` | "Open Terminal" / "List running apps" |
| `clipboard` | "Copy this to clipboard" / "What did I copy?" |
| `ocr` | "Read the text in that region" (read-only) |
| `learn` | Record a workflow once, replay it later |
| `schedule` | Run a task or learned workflow on a timer |
| `audit` | Show the session audit log, replay a session |
| `memory` | Search what was on screen earlier (read-only) |
| `memory_manage` | Pause capture, edit the deny list, change retention, delete history |

Session admin tools for [remote machines](../remote/mcp.md):

| Tool | Purpose |
|------|---------|
| `opendesk_peers` | List this machine and the paired peers |
| `opendesk_discover` | Find OpenDesk peers on the LAN (mDNS) |
| `opendesk_use` | Set the default target for later calls |
| `opendesk_status` | Current default peer and open connections |
| `opendesk_describe` | What a peer is for and what it can access |
| `opendesk_capabilities` | What a peer's backend can do |
| `opendesk_disconnect` | Close a cached remote connection |

Computer-use tools also accept an optional `peer` argument to run a single call on another machine.

Every tool carries a `title` and MCP annotations (`readOnlyHint`, `destructiveHint`, …), failures come back
with `isError: true`, and the server sends `instructions` that teach the agent the preferred order:
`ui` first, then `screenshot(marks=true)`, then `mouse`. See [Advanced](advanced.md#what-the-server-tells-the-agent).

---

## Ask Claude

Once connected, just describe what you want in plain English:

> "Take a screenshot and tell me what's on my screen"

> "Click the Save button in TextEdit"

> "Open Spotify"

> "Type hello world into the active window"

> "What text is in that dialog box?"

> "Show me the audit log"

> "What was the error I saw in the terminal on Tuesday?"

Claude decides which tool to call, calls it, and responds with the result — you never write any code.

---

## Setup

1. [Install](install.md) (or skip it and use `uvx` / `npx`)
2. Grant [permissions](../getting-started/permissions.md) on macOS: `opendesk check --open`
3. Register with your client: [Claude Code](claude-code.md) · [Claude Desktop](claude-desktop.md) · [Cursor & VS Code](cursor.md) · [Continue](continue.md)
