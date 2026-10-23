# OpenDesk

**OpenDesk by VitalOps** — open-source computer-use MCP server that lets AI agents see and control macOS, Windows and Linux desktops, locally or across paired machines. Works with any MCP client (Claude Code, Claude Desktop, Cursor, VS Code, Continue) and any AI framework (Anthropic SDK, OpenAI, LangChain). Not to be confused with the openDesk office suite.

Quick install (Claude Code, needs [uv](https://docs.astral.sh/uv/)):

```bash
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
```

On macOS, run `opendesk check --open` (or `uvx opendesk check --open`) and grant Accessibility and Screen Recording to the app that runs OpenDesk. Other clients: see [MCP](mcp/index.md).

```{toctree}
:maxdepth: 2
:caption: Getting Started

getting-started/index
getting-started/python
getting-started/javascript
getting-started/permissions
```

```{toctree}
:maxdepth: 2
:caption: MCP

mcp/index
mcp/install
mcp/claude-code
mcp/claude-desktop
mcp/cursor
mcp/continue
mcp/advanced
mcp/troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Integrations

integrations/index
integrations/anthropic
integrations/openai
integrations/langchain
integrations/javascript
integrations/custom
```

```{toctree}
:maxdepth: 2
:caption: Tools

tools/index
tools/ui
tools/screenshot
tools/mouse
tools/keyboard
tools/app
tools/clipboard
tools/ocr
tools/audit
tools/learn
tools/memory
tools/script
tools/browser
tools/fleet
tools/reward
tools/diagnose
```

```{toctree}
:maxdepth: 2
:caption: Safety & Evaluation

safety
eval
```

```{toctree}
:maxdepth: 2
:caption: Automation

automation/index
automation/claude-code
automation/python-api
automation/scheduler
automation/compiled-replay
```

```{toctree}
:maxdepth: 2
:caption: Architecture

architecture/index
architecture/layers
architecture/accessibility
architecture/learning
architecture/protocol-layer
architecture/remote-layer
architecture/data-flow
architecture/custom-tools
architecture/native-helper
```

```{toctree}
:maxdepth: 2
:caption: Protocol

protocol/index
protocol/transport
protocol/encryption
protocol/pairing
protocol/auth
protocol/frames
protocol/session
protocol/discovery
```

```{toctree}
:maxdepth: 2
:caption: Remote — Python

remote/index
remote/setup
remote/running
remote/mcp
remote/security
remote/cli
remote/service
remote/concurrency
remote/programmatic
remote/troubleshooting
```

```{toctree}
:maxdepth: 2
:caption: Remote — JS/TS

remote-js/index
remote-js/setup
remote-js/running
remote-js/mcp
remote-js/audit
remote-js/security
remote-js/cli
remote-js/concurrency
remote-js/programmatic
remote-js/troubleshooting
```
