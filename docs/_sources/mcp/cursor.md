# Cursor & VS Code

## Cursor

Create or edit `.cursor/mcp.json` in your project root (or `~/.cursor/mcp.json` globally).

### Python (via uv)

```json
{
  "mcpServers": {
    "opendesk": {
      "command": "uvx",
      "args": ["--from", "opendesk", "opendesk-mcp"]
    }
  }
}
```

### JavaScript / TypeScript (via npx)

```json
{
  "mcpServers": {
    "opendesk": {
      "command": "npx",
      "args": ["-y", "-p", "@vitalops/opendesk-sdk", "opendesk-js-mcp"]
    }
  }
}
```

## VS Code

Create `.vscode/mcp.json` in your workspace (or run **MCP: Add Server** from the command palette).

### Python (via uv)

```json
{
  "servers": {
    "opendesk": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "opendesk", "opendesk-mcp"]
    }
  }
}
```

### JavaScript / TypeScript (via npx)

```json
{
  "servers": {
    "opendesk": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "-p", "@vitalops/opendesk-sdk", "opendesk-js-mcp"]
    }
  }
}
```

If you pip-installed OpenDesk, `"command": "opendesk-mcp"` with no args works too.

## Permissions

On macOS, grant Accessibility and Screen Recording to **Cursor** or **Visual Studio Code**, then quit and reopen it.
`opendesk check --open` (or `uvx opendesk check --open`) opens the right pane.
See [Permissions](../getting-started/permissions.md).

---

Next up: [Continue →](continue.md)
