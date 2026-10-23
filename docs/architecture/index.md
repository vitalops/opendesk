# Architecture

opendesk separates *what a computer can do* (the capability surface) from
*where that computer lives* (local vs. remote) and *how agents talk to it*
(via tools, MCP, etc.). Each layer is independently importable.

```
┌──────────────────────────────────────────────────────────────┐
│  Integrations   MCP  ·  Claude Code  ·  OpenAI  ·  LangChain │
├──────────────────────────────────────────────────────────────┤
│  Tools          screenshot · mouse · keyboard · ui ·         │
│                 clipboard · ocr · app · learn · schedule     │
├──────────────────────────────────────────────────────────────┤
│  Computer       Computer ABC                                 │
│                   ├─ LocalComputer  (the machine we're on)   │
│                   └─ RemoteComputer (via the wire protocol)  │
│                 ComputerDispatcher (server-side router)      │
├──────────────────────────────────────────────────────────────┤
│  Remote         opendesk serve · pair · discover · connect   │
│                 mDNS advertisement & browsing                │
├──────────────────────────────────────────────────────────────┤
│  Protocol       frames · msgpack codec · peer (call-id mux)  │
│                 transports: WebSocket (TCP) — future: QUIC   │
│                 auth: X25519 + ChaCha20-Poly1305, pairing PSK│
└──────────────────────────────────────────────────────────────┘
```

Three load-bearing properties:

1. **Tools never know whether a Computer is local or remote.** The same tool
   code runs against `LocalComputer` or `RemoteComputer`.
2. **Bytes are bytes.** msgpack `bin` carries pixmaps, file contents, and
   process output natively — no base64 anywhere on the wire.
3. **Trust is keys, not certs.** No CA-signed certificates required. Both
   peers hold long-lived X25519 keypairs that authenticate each connection.

---

## Layer guide

| Layer | Guide |
|---|---|
| Computer & Tools | [Computer & Tools](layers.md) |
| Accessibility | [The Accessibility Channel](accessibility.md) |
| Protocol | [Protocol Layer](protocol-layer.md) |
| Remote & Integrations | [Remote & Integrations](remote-layer.md) |
| Data Flow | [Data Flow](data-flow.md) |
| Custom Tools | [Adding a Custom Tool](custom-tools.md) |
