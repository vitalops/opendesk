# JavaScript / TypeScript Quickstart

No Python required. All desktop automation runs natively in Node.js.

## Install

```bash
npm install @vitalops/opendesk-sdk
```

Register with Claude Code:

```bash
npx opendesk-js install
npx opendesk-js uninstall   # to remove
```

Or run the MCP server without installing anything:

```bash
npx -y @vitalops/opendesk-sdk            # runs the `opendesk-sdk` bin (the MCP server over stdio)
npx -y -p @vitalops/opendesk-sdk opendesk-js-mcp   # same server, explicit bin name
```

On macOS, grant Accessibility and Screen Recording to the app that runs the server first (see [Permissions](permissions.md)).

## Try it via Claude

Once registered, open Claude Code and ask:

> "Take a screenshot and describe what's on my screen"

> "Open Safari and go to google.com"

> "Click the first button you see"

> "Show me the audit log"

> "Replay everything you just did"

Claude calls the tools automatically — no code needed.

---

## SDK examples

### 1. Take a screenshot

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";

const client = new OpenDeskClient();
const result = await client.screenshot({ marks: true });
console.log(result.output);
```

## 2. Click a button by name

```typescript
await client.ui({ action: "click", app: "TextEdit", title: "File" });
```

## 3. Type text

```typescript
await client.keyboard({ action: "type", text: "Hello from JS" });
await client.keyboard({ action: "press", key: "enter" });
```

## 4. Full agentic loop (Vercel AI SDK)

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
import { generateText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";

const client = new OpenDeskClient();
const shot = await client.screenshot({ marks: true });

const { text } = await generateText({
  model: anthropic("claude-opus-4-6"),
  messages: [
    {
      role: "user",
      content: [
        { type: "text", text: "Click the most prominent button on screen." },
        { type: "image", image: shot.attachments[0].content },
      ],
    },
  ],
});
```

## 5. Native MCP server (Node.js)

```typescript
import { createMcpServer } from "@vitalops/opendesk-sdk";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = createMcpServer();
await server.connect(new StdioServerTransport());
```

## 6. Custom session or permission handler

```typescript
const client = new OpenDeskClient({
  sessionId: "my-session",
  permissionHandler: async (tool, action, description) => {
    console.log(`Allow: ${description}`);
  },
});
```

---

## Next steps

- [Tools reference](../tools/index.md) — full parameter docs for every tool (same for Python and JS)
- [Integrations](../integrations/javascript.md) — Vercel AI SDK, LangChain.js, and more
- [Remote computer use (JS)](../remote-js/index.md) — control another machine over LAN
