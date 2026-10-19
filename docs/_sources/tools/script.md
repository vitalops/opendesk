# `script` — Shell, AppleScript, JXA & PowerShell

The fast path of computer use. Many desktop tasks don't need to *see* anything: reading a file, flipping a `defaults` key, asking Finder for its selection, querying the registry. One script call replaces a dozen screenshot → click round-trips and gives the same answer every time.

```python
from opendesk.tools.script import ScriptTool
tool = ScriptTool()
```

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
const client = new OpenDeskClient();
await client.script({ action: "shell", code: "ls ~/Desktop" });
```

## Routing rule

The tool description tells the agent:

1. **`script`** first, when the task doesn't need visual interaction: files, CLIs (`git`, `curl`, `ffmpeg`), macOS `defaults` / `open` / `mdfind`, an app's AppleScript dictionary (Finder, Mail, Safari, Music, System Events), Windows PowerShell / WMI / registry.
2. **[`ui`](ui.md)** (accessibility) when it does.
3. **[`mouse`](mouse.md)** only when neither works.

## Actions

| Action | Runs as | Platforms |
|--------|---------|-----------|
| `shell` | `/bin/sh -c <code>` (macOS / Linux), `cmd.exe /d /s /c <code>` (Windows) | all |
| `applescript` | `osascript -e <code>` | macOS |
| `jxa` | `osascript -l JavaScript -e <code>` | macOS |
| `powershell` | `powershell.exe -EncodedCommand …` (Windows), `pwsh` elsewhere if installed | Windows (+ pwsh) |

Asking for `applescript` or `jxa` on Windows or Linux returns a clear error instead of running anything.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | — | `shell`, `applescript`, `jxa`, or `powershell` |
| `code` | string | — | The command or script source |
| `timeout` | number | `60` | Seconds before the process is killed (max `600`) |
| `cwd` | string | null | Working directory |
| `peer` | string | default peer | (MCP) run on a paired machine instead |

The result reports the exit code, stdout and stderr. A non-zero exit code is flagged as an error so the agent notices. Output over 16,000 characters per stream is cut down to its first and last parts, with a note saying how much was left out.

## Ask Claude

> "How much free disk space do I have?"

> "Turn on 'show all file extensions' in Finder"

> "What's the title of every open Safari tab?"

> "List the 10 biggest files in ~/Downloads"

> "Which Windows services are set to start automatically?" (PowerShell)

> "Run `git pull` in ~/code/api on the build-mac peer"

---

## SDK examples

```python
params = ScriptTool.Params

# Shell
r = await tool.execute(ctx, params(action="shell", code="df -h /", timeout=10))
print(r.output)        # Exit code: 0 … --- stdout --- …

# AppleScript (macOS) — app dictionaries beat clicking menus
await tool.execute(ctx, params(
    action="applescript",
    code='tell application "Finder" to get name of every window',
))

# JXA (macOS)
await tool.execute(ctx, params(
    action="jxa",
    code="Application('Safari').windows[0].tabs.name()",
))

# PowerShell (Windows)
await tool.execute(ctx, params(
    action="powershell",
    code="Get-Service | Where-Object StartType -eq Automatic | Select -First 5",
))
```

```typescript
const r = await client.script({ action: "jxa", code: "Application('Music').currentTrack.name()" });
console.log(r.output, r.metadata.returncode);
```

## Remote peers

In Python the tool calls `ctx.computer.exec(argv)`, so it runs on whichever [`Computer`](../architecture/layers.md) the context holds. From MCP, pass `peer` to run on a paired machine. The remote's policy still gates `process.exec`. With `serve --approve console`, the operator is asked before each script runs. Shell, AppleScript and JXA source is passed in argv, so the approval prompt and the remote audit log show it. PowerShell is passed as `-EncodedCommand`, so they show base64 instead. The JS MCP server forwards `script` to the peer's tool dispatcher the same way.

Every call is recorded in the session audit log as `script`: the code (first 1,000 characters), the working directory, the timeout and the exit code. See [`audit`](audit.md).

!!! warning
    `script` runs arbitrary code with the user's privileges. Use a permission handler (`interactive_context()` in Python, `permissionHandler` in JS) when you don't fully trust the agent. Your handler gets the action and a preview of the code.

---

Next: [browser →](browser.md)
