# Permissions

Run the permission check before your first session:

```bash
opendesk check --open        # pip install
uvx opendesk check --open    # no install, via uv
```

It reports which permissions are missing and opens the right System Settings pane. Without `--open` it only prints the report.

---

## macOS

macOS gates desktop control behind two privacy permissions:

| Permission | Needed for |
|---|---|
| **Accessibility** | Mouse and keyboard input, the `ui` tool (accessibility API), app control |
| **Screen Recording** | `screenshot`, `ocr`, Set-of-Marks, screen memory |

Grant **both** to **the app that runs OpenDesk**, not to OpenDesk itself:

| You use OpenDesk from | Grant the permissions to |
|---|---|
| Claude Desktop (the `.mcpb` bundle or a `claude_desktop_config.json` entry) | Claude |
| Claude Code | Your terminal app: Terminal, iTerm2, Ghostty, Warp, … |
| Cursor | Cursor |
| VS Code (Copilot agent mode, Claude Code extension) | Visual Studio Code |
| A controlled machine running `opendesk serve` | The terminal (or Python binary) that runs `serve`; for the login service, the Python the service launches |

Steps:

1. Open **System Settings → Privacy & Security → Accessibility** and turn the app on. If it isn't listed, click **+** and add it.
2. Do the same under **Privacy & Security → Screen Recording**.
3. **Quit and reopen the app.** macOS only applies the change to new processes.

`opendesk check --open` jumps straight to the first missing pane.

## Linux

No permission prompts, but the accessibility and clipboard tools need system packages:

```bash
sudo apt install xclip xdotool python3-pyatspi
```

`python3-pyatspi` provides AT-SPI2 for the `ui` tool. Screen capture and input work best under X11; on Wayland, most compositors block global screen capture and synthetic input, so log in to an X11 session (or use XWayland apps) if screenshots come back empty or clicks are ignored.

## Windows

Nothing to set up. OpenDesk uses UI Automation and Win32 input, which need no extra permissions. To control elevated (admin) windows, run the MCP client elevated too.

---

## Troubleshooting

| Symptom | Missing permission |
|---|---|
| Screenshots are black, show only the wallpaper, or capture fails | Screen Recording |
| Clicks and typing are silently ignored | Accessibility |
| AppleScript errors `-1719` ("not allowed assistive access") or `-1002` | Accessibility |
| Granted, but still failing | The app wasn't restarted, or the permission went to a different app than the one launching OpenDesk |

When a tool fails for one of these reasons, its error message now ends with the fix: which app needs the permission and the `opendesk check --open` command. The MCP server also returns these failures with `isError: true`, so the agent can stop and tell you instead of retrying blindly.
