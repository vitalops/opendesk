# JavaScript / TypeScript SDK

The `@vitalops/opendesk-sdk` npm package provides a fully native Node.js SDK — no Python required.
All desktop automation runs directly in Node.js using native platform APIs.

## Install

```bash
npm install @vitalops/opendesk-sdk
```

## Claude Code / Claude Desktop

```bash
npx opendesk-js install        # register native MCP server
npx opendesk-js uninstall      # remove
```

Claude Desktop config:

```json
{
  "mcpServers": {
    "opendesk": {
      "command": "node",
      "args": ["/path/to/node_modules/@vitalops/opendesk-sdk/bin/opendesk-mcp.js"]
    }
  }
}
```

## Programmatic usage

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";

const client = new OpenDeskClient();

await client.screenshot({ marks: true });
await client.ui({ action: "click", app: "Safari", title: "Go" });
await client.keyboard({ action: "type", text: "Hello" });

// Screen memory (after `npx opendesk-js memory start`)
await client.memory({ action: "search", query: "invoice", since: "last week" });
```

## Native MCP server

```typescript
import { createMcpServer } from "@vitalops/opendesk-sdk";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = createMcpServer();
await server.connect(new StdioServerTransport());
```

## With Vercel AI SDK

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
import { generateText } from "ai";
import { anthropic } from "@ai-sdk/anthropic";

const client = new OpenDeskClient();
const shot = await client.screenshot({ marks: true });

await generateText({
  model: anthropic("claude-opus-4-6"),
  messages: [{
    role: "user",
    content: [
      { type: "text", text: "What do you see? Click the most important button." },
      { type: "image", image: shot.attachments[0].content },
    ],
  }],
});
```

## With LangChain.js

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";

const client = new OpenDeskClient();

// Use client methods directly inside your LangChain agent's tool implementations
const shot = await client.screenshot({ marks: true });
```

## Custom session or permission handler

```typescript
const client = new OpenDeskClient({
  sessionId: "my-session",
  permissionHandler: async (tool, action, description) => {
    console.log(`Allow: ${description}`);
  },
});
```

---

Building something that doesn't fit the above? The [Custom integration guide →](custom.md) gives you direct access to the raw tool API and sandbox configuration.
