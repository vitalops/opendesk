# `browser` — Chrome / Edge / Brave over DevTools

Drive a Chromium-family browser through the [Chrome DevTools Protocol](https://chromedevtools.github.io/devtools-protocol/) instead of pixels. The agent reads the page as text plus an accessibility snapshot, then clicks elements by reference. This is faster and much more reliable than screenshot → OCR → mouse for anything inside a web page.

```python
from opendesk.tools.browser import BrowserTool
tool = BrowserTool()          # needs `websockets` (pip install 'opendesk[remote]')
```

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
const client = new OpenDeskClient();
await client.browser({ action: "launch", url: "https://example.com" });
```

Supported: Google Chrome, Chromium, Microsoft Edge, Brave. The binary is found automatically. To use a specific one, pass `browser` (`chrome`, `chromium`, `edge`, `brave`, or a full path) or set `$OPENDESK_BROWSER`.

## Actions

| Action | Parameters | Description |
|--------|-----------|-------------|
| `launch` | `browser`, `port`, `headless`, `url`, `profile_dir` | Start a browser with `--remote-debugging-port` and a **dedicated profile** |
| `attach` | `port` | Connect to a browser already started with `--remote-debugging-port` |
| `tabs` | — | List tabs: index, id, title, url (`*` marks the current one) |
| `open` | `url` | Open a new tab and make it current |
| `navigate` | `url`, `tab` | Load a URL and wait for the load event |
| `read` | `tab`, `max_chars` | Title, URL, visible text, and an accessibility snapshot with refs (`e1`, `e2`, …) |
| `click` | `ref` \| `selector` \| `text` | Click an element: by ref from `read`, by CSS selector, or by its visible text |
| `type` | `text`, `ref` \| `selector`, `clear`, `submit` | Type into a field (or the focused element); `submit` presses Enter |
| `wait_for` | `selector` \| `text`, `timeout` | Wait until something appears |
| `screenshot` | `full_page` | PNG of the tab, returned as an image |
| `eval` | `expression` | Run a JavaScript expression and return its JSON value |
| `close_tab` | `tab` | Close the current or given tab |

`tab` accepts an index from `tabs`, a target id (or its prefix), or text that appears in the tab's title or URL. The default is the current tab.

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | — | One of the actions above |
| `url` | string | null | URL for `launch` / `open` / `navigate` |
| `port` | int | `9222` | DevTools port for `launch` / `attach` |
| `browser` | string | first found | `chrome`, `chromium`, `edge`, `brave`, or a binary path |
| `headless` | bool | `false` | `launch` without a window |
| `profile_dir` | string | `<home>/browser-profile` | Profile override; must be empty or created by opendesk |
| `tab` | int \| string | current | Which tab to act on |
| `ref` | string | null | Element ref from the latest `read`, e.g. `e12` |
| `selector` | string | null | CSS selector |
| `text` | string | null | Visible text (`click`, `wait_for`) or text to type (`type`) |
| `expression` | string | null | JavaScript for `eval` |
| `clear` | bool | `false` | `type`: empty the field first |
| `submit` | bool | `false` | `type`: press Enter afterwards |
| `full_page` | bool | `false` | `screenshot`: capture the whole page |
| `max_chars` | int | `8000` | `read`: visible-text budget |
| `timeout` | number | `15` | Seconds for `wait_for`, page loads and `launch` |

The JS SDK uses camelCase for the multi-word ones (`profileDir`, `fullPage`, `maxChars`) and also accepts the snake_case names.

## What `read` returns

```
Title: Sign in
URL: https://example.com/login

--- visible text (212 chars) ---
Sign in
Email
Password
Forgot password?

--- accessibility snapshot (6 refs; use ref=eN with click/type) ---
[e1] RootWebArea "Sign in" (focused)
  [e2] heading "Sign in"
  [e3] textbox "Email"
  [e4] textbox "Password"
  [e5] button "Continue"
  [e6] link "Forgot password?"
```

Refs belong to the latest `read` of that tab. After the page changes, call `read` again.

`click` scrolls the element into view and sends a real mouse press and release at its centre. If another element covers that point, or the element has no size, it falls back to a DOM `element.click()`, and the result says which was used.

## Profiles and safety

- `launch` always passes `--user-data-dir`. By default that is `~/.opendesk/browser-profile`, so cookies and logins stay separate from the user's everyday browser. The tool marks that directory as its own, and it refuses any directory that already has content but no marker, so it can't take over a real profile by accident.
- If the port already has a DevTools endpoint that opendesk didn't start, `launch` refuses and suggests `attach`.
- `attach` connects to any browser you started with `--remote-debugging-port`. Use it on a profile you are willing to automate.
- Every action is recorded in the session audit log as `browser`.

!!! note "Local-only in v1"
    `browser` always runs on the machine hosting the opendesk process. The MCP server does not add a `peer` field to it and does not route it to paired peers, in either SDK. To drive a browser on another machine, run `script` there or use the GUI tools with `peer`.

## Ask Claude

> "Open Hacker News and tell me the top 5 stories"

> "Log into the staging dashboard and download last week's report"

> "Fill in this form with my shipping address"

> "Wait for the build page to say 'Succeeded', then screenshot it"

> "What's the price of the first result on this page?"

---

## SDK examples

```python
params = BrowserTool.Params

await tool.execute(ctx, params(action="launch", url="https://news.ycombinator.com"))
page = await tool.execute(ctx, params(action="read"))
print(page.output)                     # text + [eN] refs

await tool.execute(ctx, params(action="click", text="new"))
await tool.execute(ctx, params(action="wait_for", selector=".athing"))
titles = await tool.execute(ctx, params(
    action="eval",
    expression="[...document.querySelectorAll('.titleline a')].slice(0,5).map(a => a.textContent)",
))

await tool.execute(ctx, params(action="type", selector="input[name=q]", text="opendesk", submit=True))
shot = await tool.execute(ctx, params(action="screenshot", full_page=True))
open("page.png", "wb").write(shot.attachments[0].content)
```

```typescript
await client.browser({ action: "attach", port: 9222 });
const page = await client.browser({ action: "read" });
await client.browser({ action: "click", ref: "e5" });
await client.browser({ action: "type", ref: "e3", text: "me@example.com", clear: true });
const shot = await client.browser({ action: "screenshot", fullPage: true });
```

To shut down a browser you launched, call `close_browser_session(session_id)` in Python or `closeBrowserSession(sessionId)` in JS.

---

Next: [fleet →](fleet.md)
