# OpenDesk for macOS

OpenDesk opens in **My workspace**, with everyday requests for exploring folders,
checking open apps, understanding the current screen, and recalling earlier work.
Choose a folder, type a request, and press **Help me**. Preferences contains access
controls. Technical configuration and provider choices are not part of this UI.

Build and setup details are in [the developer guide](LOCAL_MODELS.md).
The following describes retained legacy components, which are no longer exposed
in the workspace navigation or menus.

## Two ways to talk to Claude

OpenDesk supports two auth modes, picked in Settings → Sign-in method.

1. **Claude Subscription** (default, recommended) — OpenDesk drives the
   `claude` CLI under the hood. Your Pro / Max / Team plan handles auth
   and billing. Zero API-key management. OpenDesk registers itself as an
   MCP server (`opendesk-mcp`) so Claude Code can call every OpenDesk tool.

2. **API Key** — Drop in an `sk-ant-…` key (stored in the macOS Keychain)
   and OpenDesk talks to the Anthropic Messages API directly with the
   `computer_20250124` tool. Per-token billing.

Switching between modes is a single click; the chat composer routes
through whichever engine is active.

## What's inside

| Section | What it does |
|---------|--------------|
| **Overview** | Status cards, live screenshot preview, quick actions, feature grid. |
| **Computer Use** | Chat with Claude. It sees the screen, takes actions, you watch the loop. |
| **Tools** | Manually invoke every OpenDesk tool — screenshot, mouse, keyboard, app, clipboard, OCR, UI. |
| **Workflows** | Record & replay routines via the `learn` tool. |
| **Schedules** | Cron-style schedules for any prompt or workflow. |
| **Remote Peers** | Discover, pair (6-digit code, X25519) and inspect peers. |
| **Activity** | Searchable audit log of every tool call this session. |
| **Settings** | Sign-in method picker, Claude Code setup wizard or Keychain API key, model picker, permissions, advanced. |

The app never bakes in any credentials. Subscription auth lives in
Claude Code's own store; API keys go to the macOS Keychain.

## Requirements

* macOS 14 (Sonoma) or newer — built for macOS 26 (Tahoe) too
* Swift 5.9+ toolchain (`swift --version`) — comes with Xcode or Command Line Tools
* Python 3.10+ with `opendesk` importable (see "Python setup" below)

## Build

```bash
cd macos
./build.sh            # → build/OpenDesk.app  (release)
./build.sh debug      # debug build
./build.sh open       # build + open
```

The script:

1. Runs `swift build -c release`
2. Assembles `build/OpenDesk.app/Contents/{MacOS,Resources,Info.plist}`
3. Bundles the Python bridge under `Resources/bridge/opendesk_bridge.py`
4. Ad-hoc codesigns so it launches without quarantine pain

Open the bundle in Finder or run:

```bash
open build/OpenDesk.app
```

## Python setup

OpenDesk's Python side needs to be importable. Two options the app supports:

1. **System install** — `pip install 'opendesk[core,mcp]'` into any Python 3.10+.
   The bridge will pick it up.

2. **Source tree** — point Settings → Advanced → "OpenDesk source root" at the
   repo's `python/` directory. The bridge sets `PYTHONPATH` and uses your local
   checkout. This is great for development.

Auto-detected Python paths (in order):

```
$pythonPath (user-set in Settings)
~/mambaforge/envs/py3.10/bin/python
~/mambaforge/bin/python3
/opt/homebrew/bin/python3
/usr/local/bin/python3
/usr/bin/python3
```

## macOS permissions

On first launch, grant:

* **Accessibility** — needed for mouse, keyboard and accessibility-tree UI control.
* **Screen Recording** — needed for screenshots.

Settings → Permissions has one-click "Open System Settings" buttons.

## Architecture

### Subscription mode (default)

```
SwiftUI App  ──▶  claude -p "<prompt>"
                   --mcp-config opendesk-mcp-config.json
                   --output-format stream-json
                          │
                          ├── NDJSON events ──▶ chat UI (streamed)
                          │
                          └── tool_use ──▶ opendesk-mcp (MCP server)
                                              │
                                              └── OpenDesk Python registry
```

Claude Code handles auth, model selection (`--model`), tool dispatch,
and even the agentic loop. OpenDesk's only responsibility is to expose
its tools as an MCP server (which it already does — `opendesk-mcp`
ships with the Python package).

### API-key mode

```
SwiftUI App  ──[stdin JSON]──▶  python opendesk_bridge.py  ──▶  opendesk registry
     │                                                            │
     │                                                            └─▶ tool result + base64 PNG
     ▼
Anthropic Messages API
   model: claude-opus-4-7 (default) | sonnet-4-6 | haiku-4-5
   tool: computer_20250124
   header: anthropic-beta: computer-use-2025-01-24
```

Every Claude computer-use call (`screenshot`, `left_click`, `type`, `key`, …)
is translated by `ClaudeService.swift` into an OpenDesk tool call, executed,
and the result returned as a `tool_result` block. The loop continues until
`stop_reason == "end_turn"` or `maxLoopSteps` is reached.

## Repo layout

```
macos/
├── Package.swift              # SPM executable target
├── build.sh                   # → build/OpenDesk.app
├── AppBundle/Info.plist       # macOS bundle plist (perms, identifier, …)
└── Sources/OpenDesk/
    ├── OpenDeskApp.swift      # @main entry, commands
    ├── Theme/Theme.swift      # palette, gradients, card style
    ├── Views/                 # each section of the UI
    ├── Services/              # ClaudeService, OpenDeskBridge, Keychain, Perms
    └── Resources/bridge/
        └── opendesk_bridge.py # Swift ↔ opendesk Python bridge
```

## Notes

* No telemetry. No remote calls except the Anthropic Messages API (and only
  when you press Send).
* The API key lives in the Keychain under service `ai.opendesk.macos`,
  account `anthropic_api_key`. You can revoke it any time from Keychain Access.
* `LSUIElement` is `false`, so the app appears in the Dock and ⌘-Tab.
