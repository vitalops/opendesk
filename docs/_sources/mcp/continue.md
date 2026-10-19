# Continue (VS Code / JetBrains)

Add a server under `mcpServers` in your Continue config (`.continue/config.yaml`, or `config.json` in older versions).

## Python (via uv)

```yaml
mcpServers:
  - name: opendesk
    command: uvx
    args: ["--from", "opendesk", "opendesk-mcp"]
```

## JavaScript / TypeScript (via npx)

```yaml
mcpServers:
  - name: opendesk
    command: npx
    args: ["-y", "-p", "@vitalops/opendesk-sdk", "opendesk-js-mcp"]
```

If you pip-installed OpenDesk, `command: opendesk-mcp` with no args works too.

On macOS, grant Accessibility and Screen Recording to the editor that runs Continue
(see [Permissions](../getting-started/permissions.md)).

---

## Any other MCP client

The pattern is always the same: run `uvx --from opendesk opendesk-mcp` (or `npx -y -p @vitalops/opendesk-sdk opendesk-js-mcp`)
over stdio. Clients that only speak HTTP can use the [streamable HTTP transport](advanced.md#streamable-http-transport).
OpenDesk follows the MCP spec, so it works with any compliant client.

---

Need a custom permission policy, HTTP transport or want to embed the server in your own process? See [Advanced →](advanced.md)
