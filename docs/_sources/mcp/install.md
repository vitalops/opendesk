# Install

You can run the MCP server without installing anything, or install the package once.

## Zero install

```bash
uvx opendesk mcp                        # Python, needs uv
uvx --from opendesk opendesk-mcp        # same server, explicit script name
npx -y @vitalops/opendesk-sdk           # JavaScript, needs Node.js 18+
```

MCP clients run these commands for you; see the per-client pages below for the exact config.

## Python

```bash
pip install opendesk
```

The base package includes the MCP server and local computer use. The `core` and `mcp` extras still exist as
aliases, so `pip install 'opendesk[core,mcp]'` keeps working.

Verify:

```bash
opendesk-mcp --version
opendesk mcp --help          # same server via the main CLI
```

## JavaScript / TypeScript

```bash
npm install @vitalops/opendesk-sdk
npx opendesk-js-mcp          # or: npx opendesk-sdk
```

## Permissions

On macOS, grant Accessibility and Screen Recording to the app that runs the server before the first call:

```bash
opendesk check --open        # or: uvx opendesk check --open
```

Details: [Permissions](../getting-started/permissions.md).

---

Next: register with your client — [Claude Code](claude-code.md) · [Claude Desktop](claude-desktop.md) · [Cursor & VS Code](cursor.md) · [Continue](continue.md)
