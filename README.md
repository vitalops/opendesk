<div align="center">

# OpenDesk

**OpenDesk by VitalOps — open-source computer-use MCP server that lets AI agents see and control macOS, Windows and Linux desktops, locally or across paired machines.**

Screenshots, accessibility-based UI actions, mouse and keyboard, OCR, workflow recording, scheduling, **screen memory**, and remote machine control, all from natural language.

**macOS · Linux · Windows**

[![PyPI](https://img.shields.io/pypi/v/opendesk?label=pypi%20opendesk)](https://pypi.org/project/opendesk/)
[![npm](https://img.shields.io/npm/v/@vitalops/opendesk-sdk?label=npm%20opendesk-sdk)](https://www.npmjs.com/package/@vitalops/opendesk-sdk)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-vitalops.ai-blue)](https://vitalops.ai/opendesk/docs/)

<sub>Not affiliated with the openDesk office suite.</sub>

</div>

---

<table>
<tr>
<td align="center" width="33%">

https://github.com/user-attachments/assets/5a6fab31-9f53-4ddb-9efb-17f0afe97844

<b>Single Machine Demo</b><br>Screenshot, click, type, navigate — all from natural language.
</td>
<td align="center" width="33%">

https://github.com/user-attachments/assets/629cf31b-12ab-4913-bc03-963f1cfbd682

<b>Control Multiple Machines</b><br>Drive remote desktops over encrypted WebSocket — same tools, same agent.
</td>
<td align="center" width="33%">

https://github.com/user-attachments/assets/659c9e30-e8f6-4a5a-ab81-0fa7ccaf8fb8

<b>UI Testing</b><br>Test a full web app — navigate, create, verify — with zero selectors.
</td>
</tr>
</table>

---

<div align="center">

### 🧠 New: Screen memory

**Your agent remembers what was on your screen, and nothing leaves your machine.**

</div>

<table>
<tr>
<td width="33%" valign="top">

**1 · It captures**<br>
Whenever you switch apps or windows, OpenDesk reads the window's text (accessibility tree, or local OCR) and keeps it with an encrypted thumbnail.

</td>
<td width="33%" valign="top">

**2 · You ask**<br>
*"What error did I see in the terminal on Tuesday?"*<br>
*"Find the invoice number I had open last week."*

</td>
<td width="33%" valign="top">

**3 · Any agent recalls it**<br>
Claude Code, Claude Desktop, Cursor, VS Code or any MCP client calls the `memory` tool and answers from your history.

</td>
</tr>
</table>

<p align="center">
🔒 Local SQLite index &nbsp;·&nbsp; 🔐 Encrypted at rest &nbsp;·&nbsp; 🙈 Secrets redacted &nbsp;·&nbsp; 🚫 Per-app deny list &nbsp;·&nbsp; ⏸ Pause hotkey &nbsp;·&nbsp; 🗑 Storage cap
</p>

```bash
pip install 'opendesk[memory]'
opendesk memory start        # then ask your agent about anything you've seen
```

<p align="center"><a href="#screen-memory"><b>How screen memory works →</b></a></p>

---

## Install

OpenDesk runs as an MCP server for Claude Code, Claude Desktop, Cursor, VS Code, Windsurf, Continue or any other MCP client. The commands below need [uv](https://docs.astral.sh/uv/) (Python) or Node.js 18+; nothing else has to be installed first.

**Claude Code**, one command:

```bash
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
```

**Claude Code plugin** (MCP server plus a skill that teaches Claude the workflow):

```bash
claude plugin marketplace add vitalops/opendesk
claude plugin install opendesk@opendesk
```

**Claude Desktop**: download `opendesk-<version>.mcpb` from [Releases](https://github.com/vitalops/opendesk/releases) and double-click it, or add the JSON below to `claude_desktop_config.json`.

**Cursor** (`~/.cursor/mcp.json`), Claude Desktop, Windsurf, Continue:

```json
{
  "mcpServers": {
    "opendesk": { "command": "uvx", "args": ["--from", "opendesk", "opendesk-mcp"] }
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "opendesk": { "type": "stdio", "command": "uvx", "args": ["--from", "opendesk", "opendesk-mcp"] }
  }
}
```

**No Python?** Use the Node.js server instead, in any of the configs above:

```json
{ "command": "npx", "args": ["-y", "-p", "@vitalops/opendesk-sdk", "opendesk-js-mcp"] }
```

**Remote clients** can use streamable HTTP with bearer-token auth: `uvx opendesk mcp --transport http --port 8765` ([details](docs/mcp/advanced.md)).

> **macOS:** run `uvx opendesk check --open`, then grant **Accessibility** and **Screen Recording** to the app that runs OpenDesk (Claude Desktop, your terminal for Claude Code, Cursor or VS Code) and restart that app. See [permissions](#system-permissions).

### SDKs

| Language | Location | Package | Install |
|----------|----------|---------|---------|
| Python 3.10+ | [`python/`](python/) | `opendesk` (PyPI) | `pip install opendesk` |
| JavaScript / TypeScript | [`js/`](js/) | `@vitalops/opendesk-sdk` (npm) | `npm install @vitalops/opendesk-sdk` |

`pip install opendesk` includes the MCP server and local computer use; `opendesk install` registers it with Claude Code (`npx opendesk-js install` for the JS server).

Once connected, try:

```
Take a screenshot of my screen
Click the Chrome icon
Open Spotify and play lo-fi beats
Show me the audit log
Replay everything from this session
What was the error I saw in the terminal on Tuesday?
```

---

## SDK usage

Use opendesk programmatically in your own agent or app.

### Python

```python
from opendesk import create_registry, allow_all_context

registry = create_registry()
ctx = allow_all_context()

result = await registry.get("screenshot").execute(ctx, ...)
```

### JavaScript / TypeScript

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";

const client = new OpenDeskClient();
await client.screenshot({ marks: true });
await client.ui({ action: "click", app: "Safari", title: "Go" });
```

---

## Architecture

opendesk is built in independently-importable layers:

```
┌──────────────────────────────────────────────────────────────┐
│  Integrations   MCP  ·  Claude Code  ·  OpenAI  ·  LangChain │
├──────────────────────────────────────────────────────────────┤
│  Tools          screenshot · mouse · keyboard · ui ·         │
│                 clipboard · ocr · learn · schedule · audit · │
│                 memory · memory_manage                       │
├──────────────────────────────────────────────────────────────┤
│  Computer       LocalComputer  ·  RemoteComputer  (ABC)      │
├──────────────────────────────────────────────────────────────┤
│  Remote         server · client · discovery (mDNS)           │
├──────────────────────────────────────────────────────────────┤
│  Protocol       frames · codec (msgpack) · peer · transports │
│                 auth (X25519 + AEAD, pairing)                │
└──────────────────────────────────────────────────────────────┘
```

| Layer | What it does |
|-------|-------------|
| **Computer** | The capability surface of a computer (observe / act / subscribe). `LocalComputer` drives the local machine; `RemoteComputer` forwards every call over the wire to a paired peer. Tools and integrations target this ABC — they never know whether the machine is local or remote. |
| **Tools** | One class per capability, agent-friendly Pydantic schemas. Calls into the active `Computer` on the `ToolContext`. |
| **Integrations** | Thin adapters for MCP, Anthropic, OpenAI, LangChain — add one tool, get all four. |
| **Remote** | `opendesk serve` / `opendesk pair`, mDNS discovery, client helper. |
| **Protocol** | Five-frame wire protocol (msgpack binary, no base64 ever), WebSocket transport, mutual X25519 + ChaCha20-Poly1305 auth and encryption. |
| **Automation** | `learn` + `schedule` backed by pynput recording, JSON storage, APScheduler daemon. |
| **Memory** | `opendesk memory start` captures on app/window switches (plus an idle fallback), reads text from the accessibility tree or local OCR, redacts secrets, and indexes text + encrypted thumbnails in SQLite/FTS5. Per-app deny list, pause hotkey, storage cap with rolling deletion. Nothing leaves the machine. |

Full details → [docs/architecture](docs/architecture/index.md)

---

## Tools

| Tool | What it does |
|------|-------------|
| `screenshot` | Capture the screen with numbered boxes on every clickable element (Set-of-Marks) |
| `ui` | Click and type by element name or `[ref]` — no coordinates, no cursor movement |
| `mouse` | Pixel-level mouse control for anything `ui` can't reach |
| `keyboard` | Type text, press keys, send hotkeys |
| `app` | Open, close, and focus applications |
| `clipboard` | Read and write the system clipboard |
| `ocr` | Extract text from any region of the screen |
| `script` | Shell, AppleScript/JXA or PowerShell — skip the GUI when a task doesn't need it |
| `browser` | Drive Chrome/Edge/Brave over the DevTools protocol: read pages, click, type, eval |
| `learn` | Record a workflow once, replay it anytime |
| `schedule` | Run any task or learned procedure on a timer |
| `audit` | Show the session audit log, replay a session |
| **`memory`** 🧠 | **Screen memory** (read-only): recall anything that was on screen, fully local (`opendesk memory start`) |
| `memory_manage` | Pause capture, edit the deny list, change retention, delete history |
| `fleet` | Run one tool call on several paired machines in parallel |
| `opendesk_*` | Pick and inspect paired remote machines (`opendesk_peers`, `opendesk_use`, …) |

Every tool carries an MCP `title` and `readOnlyHint` / `destructiveHint` annotations, so clients can auto-approve read-only calls and ask before actions.

Full reference → [docs/tools](docs/tools/index.md)

---

## Automation

Record a task once, replay it forever, or put it on a schedule.

**Record**
```
"Start recording task expense-form"
```
Perform the workflow yourself. The agent captures every click, keystroke, and screenshot.

**Replay**
```
"Stop recording"
"Replay expense-form"
```
The agent re-executes using the current screen state — no hardcoded coordinates.

**Compiled replay.** Each recording (or a successful session, via `learn(action="save_session")`) also compiles into a program that targets UI elements by app, role and title, with a check after each step. `learn(action="run")` replays it with **no LLM calls**; if a step fails, it stops and hands the agent the remaining steps to finish and `patch`. Scheduled replays use the compiled program first, so they run without an API key. → [docs/automation/compiled-replay.md](docs/automation/compiled-replay.md)

**Schedule**
```
"Every morning at 9am, open my email in Chrome, take a screenshot, and summarize what's there"
"Schedule expense-form every friday at 5pm"
```
```bash
opendesk scheduler start
```

Supported timing: `every 30m` · `every 2h` · `every day at 09:00` · `every friday at 17:00` · raw cron

Full guide → [docs/automation](docs/automation/index.md)

---

## Screen memory

> [!TIP]
> **A searchable, fully local history of what was on your screen** — like Rewind or Recall, but open source, cross-platform, and callable by any agent.

```bash
# Python
pip install 'opendesk[memory]'
opendesk memory start            # or: opendesk memory install-service (run at login)

# JavaScript / TypeScript
npm install @vitalops/opendesk-sdk
npx opendesk-js memory start     # or: npx opendesk-js memory install-service
```

The daemon captures the screen whenever you switch apps or windows (plus an idle fallback), reads the window's text from the **accessibility tree** or with local OCR **on your machine**, redacts secrets, and stores the text plus an **encrypted** thumbnail in `~/.opendesk/memory`. Agents search it with the read-only `memory` tool; `memory_manage` pauses capture or deletes history. Then ask:

```
"What was the error message I saw in the terminal on Tuesday?"
"Find the invoice number I had open last week"
"Show me every time I opened that dashboard this month"
```

- **Fully local index** — SQLite + FTS5, no upload, no telemetry.
- **Encrypted at rest** — thumbnails are AES-GCM encrypted with a key in the OS keychain; text encryption with an exact-word blind index is one flag away (`opendesk memory config --encrypt-text on`).
- **Secret redaction** — API keys, tokens, card numbers and `password:` pairs are scrubbed before anything is written; private-browsing windows are skipped.
- **Per-app deny list** — password managers excluded by default; `opendesk memory deny add "bank"` matches app names and window titles.
- **Pause hotkey** — `Cmd/Ctrl+Shift+Alt+P`, or `opendesk memory pause 2h`.
- **Storage cap with rolling deletion** — default 2 GB / 30 days; oldest frames go first.
- **Export** — `opendesk memory export --format html` writes a decrypted, browsable copy (also `json` / `csv`) to a folder you choose.

Full reference → [docs/tools/memory.md](docs/tools/memory.md)

---

## Safety

Every tool call from an agent passes through a local safety guard before it touches the desktop.

- **Risk tiers** — each tool and action is classified; the `standard` preset allows reads and ordinary input, and asks before high-risk actions such as `script` shell commands or `browser` eval. `strict` asks before anything that acts. Add your own allow / confirm / block rules per tool, app or peer.
- **Approvals** — asked in the MCP client when it supports elicitation, otherwise in a native OS dialog.
- **Kill switch and take-over** — `opendesk stop` refuses every agent call immediately, on this machine and from paired controllers; `opendesk takeover` / `handback` lets you drive for a while.
- **Untrusted screen content** — text read off the screen is wrapped as data, scanned for prompt injection, and a hit makes input actions require approval for a while.
- **Tamper-evident audit** — every call is written to a hash-chained log; `opendesk audit verify` checks it.
- **Secrets the model never sees** — store a password with `opendesk secrets set NAME`; the agent types `{{secret:NAME}}` and OpenDesk fills it in from the OS keychain after you approve, redacting it everywhere.

```bash
opendesk policy preset strict    # ask before anything that acts
opendesk stop                    # halt the agent now
opendesk audit verify            # check the audit chain
```

Full guide → [docs/safety.md](docs/safety.md)

---

## Evaluation

`opendesk eval` runs task suites against a real desktop and reports success, turns, time and cost: a macOS smoke suite, a prompt-injection suite, and regression checks for compiled workflows. Backends hold the model constant so you can compare OpenDesk's tools with the API's native computer tool. An OSWorld adapter is included.

```bash
opendesk eval run macos-smoke --dry-run   # show exactly what would run
opendesk eval run injection --repeat 3    # uses Claude Code on your subscription
```

Full guide → [docs/eval.md](docs/eval.md)

---

## Remote computer use

Control another machine from your agent — same tools, same MCP server, the
`Computer` abstraction just lives on the other end of an encrypted WebSocket.

**On the machine being controlled** (one time):

```bash
pip install 'opendesk[remote]'
opendesk pair        # prints a 6-digit code, listens
```

**On the controller** (one time):

```bash
pip install 'opendesk[remote]'
opendesk discover                          # list opendesk peers on the LAN
opendesk pair-with <host> <code> --name mini
```

**After pairing**, the controlled machine runs the long-lived server:

```bash
opendesk serve            # accepts paired peers only
```

…and the controller drives it through the existing MCP server (Claude Code,
Claude Desktop, Cursor — anything that speaks MCP). The agent gets new admin
tools — `opendesk_peers`, `opendesk_use`, `opendesk_status` — and every
existing tool accepts an optional `peer:` argument:

```
screenshot                       → controls the local machine
screenshot peer=mini             → controls the paired remote
opendesk_use mini                → make mini the default for this session
screenshot                       → [on mini] ...
```

With exactly one paired peer the agent doesn't have to specify anything —
it becomes the implicit default. With multiple, the agent must pick
explicitly (no silent fallback).

**One controller at a time.** Pair as many machines as you like, but only
one drives the desktop at a time — a second peer trying to connect while
one is active gets a clean `BUSY` error. Same peer reconnecting bumps
the previous session (no waiting out a stale TCP). Two ways to free the
slot from the controlled machine:

- `opendesk disconnect` — **cooperative**. Server asks the controller to
  leave via a `session.evicted` PUSH; a cooperative client (the in-tree
  `RemoteComputer`) suppresses its auto-reconnect and raises
  `SessionEvicted`. Trust is preserved.
- `opendesk unpair <name>` — **enforced**. Revokes trust + closes the
  session; next reconnect fails authentication.

**Security model:** pairing exchanges long-lived X25519 keypairs via a 6-digit
code-authenticated handshake (PBKDF2-stretched, ~CPU-month to brute force).
Subsequent connections use mutual static-key authentication. Every frame is
ChaCha20-Poly1305 AEAD-encrypted with per-direction counters. No CA-signed
certificates required — the keys ARE the trust.

Full guide → [docs/remote](docs/remote/index.md)

---

## Installation options

```bash
uvx opendesk mcp                         # run the MCP server without installing anything
pip install opendesk                     # MCP server + local computer use (screen capture, mouse, keyboard)
pip install 'opendesk[remote]'           # + control another machine over LAN
pip install 'opendesk[learn]'            # + task recording and replay
pip install 'opendesk[learn,schedule]'   # + scheduled tasks
pip install 'opendesk[memory]'           # + screen memory (searchable desktop history)
pip install 'opendesk[all]'              # everything
```

The `core` and `mcp` extras from earlier versions still work; they are now part of the base install.

---

## Platform support

| Feature | macOS | Linux | Windows |
|---------|:-----:|:-----:|:-------:|
| Screenshot | ✓ | ✓ | ✓ |
| Mouse & keyboard | ✓ | ✓ | ✓ |
| UI element access | AppleScript | AT-SPI2 | UI Automation |
| Clipboard | pbcopy/pbpaste | xclip/xsel | pyperclip |
| OCR | Vision / tesseract | tesseract | WinRT / tesseract |
| App control | `open -a` | `xdg-open` | `start` |
| Task recording | ✓ | ✓ | ✓ |
| Scheduled tasks | ✓ | ✓ | ✓ |
| Remote control (LAN) | ✓ | ✓ | ✓ |
| LAN discovery (mDNS) | ✓ | ✓ | ✓ |

---

## System permissions

### macOS

```bash
opendesk check --open        # or: uvx opendesk check --open
```

It reports what is missing and opens the right System Settings pane. Grant **Accessibility** (mouse, keyboard, UI actions) and **Screen Recording** (screenshots, OCR) to **the app that runs OpenDesk**:

- **Claude Desktop** when you use the `.mcpb` bundle or `claude_desktop_config.json`
- **your terminal** (Terminal, iTerm2, Ghostty, …) for Claude Code
- **Cursor** or **VS Code** when they launch the server

Then quit and reopen that app. When a permission is missing, tool errors say so and point back to `opendesk check --open`.

### Linux
```bash
sudo apt install xclip xdotool python3-atspi
```

### Windows
No extra permissions needed — opendesk uses Win32 APIs by default.

See [docs/getting-started/permissions.md](docs/getting-started/permissions.md) for the full setup guide.

---

## Integrations

### Claude Code
```bash
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
# or, after `pip install opendesk`:
opendesk install        # registers opendesk-mcp globally
opendesk uninstall      # removes the registration
```

### Claude Desktop

Add to your config file:
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "opendesk": { "command": "uvx", "args": ["--from", "opendesk", "opendesk-mcp"] }
  }
}
```

Or install the one-click `.mcpb` bundle from [Releases](https://github.com/vitalops/opendesk/releases).

### Python API

```python
import asyncio
from opendesk import create_registry, allow_all_context

async def main():
    registry = create_registry()
    ctx = allow_all_context()

    result = await registry.get("screenshot").execute(
        ctx, registry.get("screenshot").Params(marks=True)
    )
    print(result.output)

asyncio.run(main())
```

Works with Anthropic SDK, OpenAI, and LangChain — see [docs/integrations](docs/integrations/index.md)

### On-device models (Ollama, LM Studio, vLLM, llama.cpp)

OpenDesk also includes a bounded local agent for all registered tools, including
screen memory and computer use. On Apple Silicon, run from this checkout:

```sh
pip install -e './python[local,memory]'
opendesk agent 'Open Calculator, then list apps to verify it is running' \
  --model mlx-community/Qwen2.5-3B-Instruct-4bit --tools app --allow-actions
```

Python supports direct MLX text/vision inference; both Python and JavaScript can
use a loopback inference server. Scheduled tasks and evaluations can select local
backends too. See [local model setup](docs/integrations/local.md) and
[measured results and limitations](docs/integrations/local-results.md).

Any OpenAI-compatible local server works out of the box:

```python
from openai import OpenAI
from opendesk.integrations.openai_compat import OpenAIAdapter

client = OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
adapter = OpenAIAdapter()
result = await adapter.run_loop(client, model="qwen2.5:72b", messages=messages)
```

---

## Citation

If you use OpenDesk in your research or project, please cite it:

```bibtex
@software{opendesk,
  author  = {Abraham, Abhigith Neil and Rahman, Fariz and Rahman, Fadil},
  title   = {opendesk: Open Desktop Automation Framework},
  year    = {2026},
  url     = {https://github.com/vitalops/opendesk},
  version = {0.3.0},
  license = {MIT}
}
```

A `CITATION.cff` is included — GitHub's "Cite this repository" button will pick it up automatically.

---

## Documentation

- Docs: <https://vitalops.ai/opendesk/docs/>
- For LLMs and coding agents: [`llms.txt`](llms.txt), [`AGENTS.md`](AGENTS.md)
- MCP Registry entry: [`server.json`](server.json) (`io.github.vitalops/opendesk`)
- Privacy: [`PRIVACY.md`](PRIVACY.md)

---

## License

MIT
