# Claude Code

## One command (Python server via uv)

```bash
claude mcp add opendesk -- uvx --from opendesk opendesk-mcp
```

Add `--scope user` to make it available in every project. Verify and remove:

```bash
claude mcp list
claude mcp remove opendesk
```

## Plugin

The OpenDesk plugin bundles the MCP server with a skill that teaches Claude the workflow, permission setup,
safety rules, peers and screen memory:

```bash
claude plugin marketplace add vitalops/opendesk
claude plugin install opendesk@opendesk
```

Or inside a session: `/plugin marketplace add vitalops/opendesk`, then `/plugin install opendesk@opendesk`.

## Already pip-installed

```bash
pip install opendesk
opendesk install            # registers opendesk-mcp from this environment
opendesk uninstall          # to remove
```

## JavaScript / TypeScript

```bash
claude mcp add opendesk -- npx -y -p @vitalops/opendesk-sdk opendesk-js-mcp
```

Or with a local install:

```bash
npm install @vitalops/opendesk-sdk
npx opendesk-js install
npx opendesk-js uninstall   # to remove
```

## Permissions

On macOS, grant Accessibility and Screen Recording to **your terminal app** (Terminal, iTerm2, Ghostty, Warp, …),
then restart it. `opendesk check --open` (or `uvx opendesk check --open`) opens the right pane.
See [Permissions](../getting-started/permissions.md).

---

Now start a conversation in Claude Code and ask:
> "Take a screenshot and tell me what's on my screen."

Claude will call the `screenshot` tool, receive the PNG, and describe it.

---

Next up: [Claude Desktop →](claude-desktop.md)
