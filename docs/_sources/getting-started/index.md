# Getting Started

Pick your language and follow the quickstart:

| | Python | JavaScript / TypeScript |
|---|---|---|
| Package | `opendesk` (PyPI) | `@vitalops/opendesk-sdk` (npm) |
| Install | `pip install opendesk` | `npm install @vitalops/opendesk-sdk` |
| Run the MCP server without installing | `uvx opendesk mcp` | `npx -y @vitalops/opendesk-sdk` |
| MCP register (Claude Code) | `claude mcp add opendesk -- uvx --from opendesk opendesk-mcp` | `npx opendesk-js install` |
| Requires | Python 3.10+ (or [uv](https://docs.astral.sh/uv/)) | Node.js 18+ |

`pip install opendesk` includes the MCP server and local computer use (screen capture, mouse, keyboard). The old `core` and `mcp` extras still work but no longer add anything.

- [Python quickstart](python.md)
- [JavaScript / TypeScript quickstart](javascript.md)
- [Permissions](permissions.md): on macOS, run `opendesk check --open` before the first session

---

## Try it immediately via Claude

Once installed and registered, open Claude Code and ask:

> "Take a screenshot and tell me what's on my screen"

> "Open TextEdit and type hello world"

> "What apps are running?"

> "Click the Save button"

No code needed — Claude calls the tools automatically.
