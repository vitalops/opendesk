# CLI Reference

All commands accept `--home DIR` to override the identity / trusted-peers
location (default `~/.opendesk`).

## Controlled machine

```
opendesk-js pair        [--port N] [--code XXXXXX] [--timeout S] [--no-mdns]
opendesk-js serve       [--port N] [--host H] [--no-mdns] [--approve {auto|console}]
opendesk-js sessions                       # show the active controller (0 or 1)
opendesk-js disconnect                     # cooperative eviction of active controller
opendesk-js unpair NAME                    # revoke trust (+ disconnect if active)
opendesk-js describe [TEXT] [--clear]      # read/set/clear this machine's broadcast description
opendesk-js audit       [--date Y-M-D] [--peer NAME] [--limit N] [--follow]
```

## Controller

```
opendesk-js discover    [--timeout S]
opendesk-js pair-with   HOST CODE [--port N] [--name NAME]
opendesk-js connect     [PEER]
opendesk-js peers       [list]
opendesk-js peers       default [NAME | --clear]
opendesk-js peers       rename  NAME NEW-NAME
opendesk-js peers       remove  NAME
opendesk-js peers       describe NAME [TEXT] [--clear]
opendesk-js unpair      NAME
```

## Shared

```
opendesk-js install     [--scope {user|project}]
opendesk-js uninstall
opendesk-js mcp                            # run MCP server over stdio
```

## Screen memory

```
opendesk-js memory start [--interval N]            run the capture daemon (Ctrl-C to stop)
opendesk-js memory status                          daemon / storage / config
opendesk-js memory pause [30m|2h]                  pause (optionally for a duration)
opendesk-js memory resume
opendesk-js memory search "<query>" [--since ..] [--until ..] [--app ..] [--limit N]
opendesk-js memory timeline [--since ..] [--app ..]
opendesk-js memory show <id>
opendesk-js memory deny [list|add <pattern>|remove <pattern>]
opendesk-js memory config [--interval N] [--cap MB] [--retention DAYS] [--hotkey '<ctrl>+<alt>+m']
opendesk-js memory clear [--before <when>] [--app ..] [--yes]
opendesk-js memory install-service | uninstall-service
```

See [tools/memory](../tools/memory.md) for the full reference.

---

Next: [Concurrency →](concurrency.md) — the single-controller policy and how to hand off between machines.
