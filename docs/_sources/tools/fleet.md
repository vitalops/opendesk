# `fleet` — One Call, Many Machines

Run one tool call on several paired peers in parallel. You get one result section per peer and a one-line summary. Use it to check a whole lab of machines, roll a change out to every build box, or find out which machine has an app open.

```python
from opendesk.tools.fleet import FleetTool
tool = FleetTool()
```

Pair the peers first (see [Remote setup](../remote/setup.md)). `fleet` uses the same trusted peers, descriptions and cached connections as ordinary `peer=` calls.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `peers` | list \| string | — | Peer names (list or comma-separated), or `all` for every trusted peer. Add `local` to include this machine. |
| `match` | string \| list | null | Keep only peers whose description or name contains **all** these words (case-insensitive). Descriptions come from `opendesk describe` / `opendesk peers describe`. |
| `tool` | string | — | Inner tool: `script`, `screenshot`, `app`, `clipboard`, `ui`, `ocr`, `mouse`, `keyboard` |
| `params` | object | `{}` | The inner tool's arguments (without `peer`) |
| `concurrency` | int | `4` | How many peers run at once (1–32) |
| `timeout` | number | `120` | Seconds per peer, including connecting |
| `include_images` | bool | `false` | Attach image results (for example screenshots) as `<peer>-<file>`. Otherwise images are only noted in the text. |

Rules:

- `fleet` cannot run inside `fleet`.
- Only tools that can run on a peer are accepted. Local-only tools like `browser`, `memory` and `learn` are refused.
- Requested names that aren't paired are listed under *Skipped*.
- The result is an error only when **no** peer succeeded. Partial failures appear in the per-peer sections and in the summary.

## Output

```
Fleet: script on 3 peer(s) — 2 ok, 1 error (1.4s)

== build-mac: ok (0.6s) ==
Exit code: 0  (0.41s, shell on darwin)
--- stdout ---
Already up to date.

== build-linux: ok (0.9s) ==
Exit code: 0  (0.70s, shell on linux)
--- stdout ---
Updating 3f2a1c0..9b7e4d2

== build-win: ERROR (1.4s) ==
Could not connect to peer 'build-win': connection refused
```

Each peer's section is capped at 4,000 characters.

## Ask Claude

> "Take a screenshot of every lab machine"

> "Run `git pull` in ~/code/api on all the build boxes"

> "Which of my machines have Xcode open?"

> "Check free disk space on every peer described as 'render'"

> "Copy this text to the clipboard on the mini and the desktop"

---

## SDK examples

From MCP the dispatcher hands the session and registry to the tool. In your own code, pass them yourself, or let `FleetTool` open a temporary session from `ctx.metadata["opendesk_home"]` (default `~/.opendesk`):

```python
from opendesk.integrations.mcp_session import MCPSession
from opendesk.registry import create_registry
from opendesk.tools.base import ToolContext
from opendesk.tools.fleet import FleetTool

session = MCPSession()
tool = FleetTool(session=session, registry=create_registry())
params = FleetTool.Params

result = await tool.execute(ToolContext(), params(
    peers="all",
    match="build",
    tool="script",
    params={"action": "shell", "code": "cd ~/code/api && git pull"},
    concurrency=8,
))
print(result.output)
print(result.metadata["ok"], result.metadata["failed"])
await session.aclose()
```

From the CLI:

```bash
opendesk fleet run --peers all --tool script \
  --params '{"action": "shell", "code": "uptime"}'

opendesk fleet run --peers mini,desktop --tool screenshot --save-images ./shots
opendesk fleet run --peers all --match "build mac" --tool app --params '{"action": "list"}'
```

The CLI exits with a non-zero status when no peer succeeded.

!!! note
    `fleet` is Python-only for now. The JS SDK's MCP server doesn't offer it yet. From JS, loop over peers with `peer` on each call.

Every fleet call is recorded in the caller's audit log as `fleet`. The inner tool also records its own entry in each peer's `mcp-<peer>` session.

---

Next: [audit →](audit.md)
