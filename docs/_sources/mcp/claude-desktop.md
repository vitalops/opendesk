# Claude Desktop

## One-click bundle

Download `opendesk-<version>.mcpb` from [GitHub Releases](https://github.com/vitalops/opendesk/releases)
and double-click it (or drag it onto Claude Desktop's **Settings → Extensions** page). The bundle uses the
MCPB `uv` runtime: it ships the OpenDesk source and Claude Desktop installs the Python dependencies on first
launch, so no separate Python or `pip install` is needed.

## Config file

Edit `claude_desktop_config.json`:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

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

If you pip-installed OpenDesk instead, use `"command": "opendesk-mcp"` (or its full path inside a virtualenv,
e.g. `/path/to/venv/bin/opendesk-mcp`). Claude Desktop doesn't read your shell's `PATH`, so give the full path
to `uvx` if it isn't found (`which uvx`).

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

Restart Claude Desktop. The tools appear under the tools menu.

## Permissions

On macOS, grant Accessibility and Screen Recording to **Claude** itself (System Settings → Privacy & Security),
then quit and reopen Claude Desktop. `opendesk check --open` (or `uvx opendesk check --open`) opens the right pane.
See [Permissions](../getting-started/permissions.md).

---

Next up: [Cursor & VS Code →](cursor.md)
