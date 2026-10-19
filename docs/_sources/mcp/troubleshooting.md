# Troubleshooting

Start with the permission check on macOS:

```bash
opendesk check --open        # or: uvx opendesk check --open
```

---

**Screenshots are black, or capture fails on macOS**

Grant **Screen Recording** to the app that runs OpenDesk: Claude Desktop, your terminal app for Claude Code,
Cursor or VS Code. Then quit and reopen that app. See [Permissions](../getting-started/permissions.md).

---

**Mouse/keyboard actions do nothing, or AppleScript errors `-1719` / `-1002` on macOS**

Grant **Accessibility** to the app that runs OpenDesk (same list as above), then restart it.
Tool errors caused by missing permissions end with this fix and are returned with `isError: true`.

---

**`opendesk-mcp` not found**

Use the zero-install form, which doesn't depend on your `PATH` or virtualenv:

```json
{ "command": "uvx", "args": ["--from", "opendesk", "opendesk-mcp"] }
```

If you prefer a pip install, run `pip install opendesk` and point the client at the full path of
`opendesk-mcp` inside that environment (`which opendesk-mcp`). GUI apps like Claude Desktop don't read your
shell's `PATH`, so give the full path to `uvx` too if needed (`which uvx`).

---

**`uvx` keeps running an old version**

uv caches tool environments. Force a refresh, or pin the version you want:

```bash
uvx --refresh --from opendesk opendesk-mcp
uvx --from 'opendesk==0.3.0' opendesk-mcp
```

---

**Tools appear but calls fail with `ImportError`**

Older releases needed the `core` / `mcp` extras. Upgrade: `pip install -U opendesk` (the base package now
includes them). Remote control still needs `pip install 'opendesk[remote]'`.

---

**HTTP transport returns 401 or 421**

401: send `Authorization: Bearer <token>`; the token is printed on start and stored in `~/.opendesk/mcp-token`.
421: the `Host` header isn't a loopback name; connect via `127.0.0.1` or `localhost`. See [Advanced](advanced.md).

---

Everything working? Explore [Integrations →](../integrations/index.md) to wire OpenDesk into your preferred agent framework, or browse the [Tools reference →](../tools/index.md) for full parameter docs.
