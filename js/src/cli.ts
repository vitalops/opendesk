/**
 * opendesk-js CLI — mirrors the Python opendesk CLI.
 *
 * Controlled-machine commands: serve, pair, sessions, disconnect, describe
 * Controller commands:         pair-with, discover, connect, peers, unpair
 * Shared:                      install, uninstall, mcp
 */

import fs from "fs";
import path from "path";
import os from "os";

async function cmdAgent(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  if (flags['help']) {
    console.log('opendesk-js agent "TASK" --model MODEL [--base-url http://127.0.0.1:1234/v1] [--vision] [--mode all|memory|desktop] [--allow-actions] [--tools app,ui] [--max-steps 8]');
    return;
  }
  const { LocalAgent, LocalHTTPBackend } = await import('./integrations/local.js');
  if (!pos.length) fatal('agent requires a task');
  const home = resolveHome(str(flags['home']) || undefined);
  if (home) process.env.OPENDESK_HOME = home;
  const backend = new LocalHTTPBackend(str(flags['model']), str(flags['base-url']) || undefined, bool(flags['vision']), bool(flags['structured']));
  const agent = new LocalAgent(backend, {
    mode: (str(flags['mode']) || 'all') as 'all' | 'memory' | 'desktop',
    allowActions: bool(flags['allow-actions']), maxSteps: num(flags['max-steps'], 8),
    tools: flags['tools'] ? str(flags['tools']).split(',') : undefined,
    trace: message => process.stderr.write(message + '\n'),
  });
  const r = await agent.run(pos.join(' '));
  console.log(r.output);
  if (r.error) process.exitCode = 1;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fatal(msg: string, code = 1): never {
  process.stderr.write(`ERROR: ${msg}\n`);
  process.exit(code);
}

function formatAge(seconds: number): string {
  const s = Math.floor(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** Resolve --home to an absolute path. Prevents path traversal. */
function resolveHome(raw: string | undefined): string | undefined {
  if (!raw) return undefined;
  return path.resolve(String(raw));
}

function validatePort(raw: unknown): number {
  const n = Number(raw);
  if (!Number.isInteger(n) || n < 1 || n > 65535) fatal(`invalid port: ${raw}`);
  return n;
}

function validateCode(raw: unknown): string {
  const s = String(raw ?? "");
  if (!/^\d{6}$/.test(s)) fatal("pairing code must be exactly 6 digits");
  return s;
}

/** Minimal flag parser — handles --key=val, --key val, --bool */
function parseFlags(argv: string[]): { pos: string[]; flags: Record<string, string | boolean> } {
  const pos: string[] = [];
  const flags: Record<string, string | boolean> = {};
  let i = 0;
  while (i < argv.length) {
    const arg = argv[i];
    if (arg === "--") { pos.push(...argv.slice(i + 1)); break; }
    if (arg.startsWith("--")) {
      const eqIdx = arg.indexOf("=");
      if (eqIdx > 2) {
        flags[arg.slice(2, eqIdx)] = arg.slice(eqIdx + 1);
      } else {
        const key = arg.slice(2);
        const nxt = argv[i + 1];
        if (nxt !== undefined && !nxt.startsWith("-")) { flags[key] = nxt; i++; }
        else { flags[key] = true; }
      }
    } else {
      pos.push(arg);
    }
    i++;
  }
  return { pos, flags };
}

function str(v: unknown): string  { return v != null ? String(v) : ""; }
function bool(v: unknown): boolean { return v === true || v === "true" || v === "1"; }
function num(v: unknown, def: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : def;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function cmdInstall(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const scope = str(flags["scope"]) || "user";
  if (scope !== "user" && scope !== "project") fatal("--scope must be 'user' or 'project'");
  const { install } = await import("./install.js");
  install(scope);
}

async function cmdUninstall(): Promise<void> {
  const { uninstall } = await import("./install.js");
  uninstall();
}

async function cmdMcp(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const home = resolveHome(str(flags["home"]) || undefined);
  const transport = flags["http"] ? "http" : (str(flags["transport"]) || "stdio");
  if (transport !== "stdio" && transport !== "http") fatal("--transport must be 'stdio' or 'http'");
  if (transport === "stdio") {
    const { runMcpStdio } = await import("./mcp.js");
    await runMcpStdio(undefined, undefined, home);
    return;
  }
  const noAuth = bool(flags["no-auth"]);
  const token = str(flags["token"]) || undefined;
  if (noAuth && token) fatal("--token and --no-auth are mutually exclusive");
  const { runMcpHttp } = await import("./mcp.js");
  try {
    await runMcpHttp({
      host: str(flags["host"]) || "127.0.0.1",
      port: validatePort(flags["port"] ?? 8765),
      token: noAuth ? null : token,
      home,
    });
  } catch (e) {
    fatal(e instanceof Error ? e.message : String(e), 2);
  }
}

// ---------------------------------------------------------------------------
// serve
// ---------------------------------------------------------------------------

async function cmdServe(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const home    = resolveHome(str(flags["home"]) || undefined);
  const port    = validatePort(flags["port"] ?? 8423);
  const host    = str(flags["host"]) || "0.0.0.0";
  const noMdns  = bool(flags["no-mdns"]);
  const approve = str(flags["approve"]) || "auto";

  if (approve !== "auto" && approve !== "console" && approve !== "policy") {
    fatal("--approve must be 'auto', 'console' or 'policy'");
  }
  // Note: the safety guard (policy.json rules + `opendesk-js stop` kill switch)
  // runs on every inbound tool call regardless; 'policy' relies on it alone.

  const { Identity }        = await import("./protocol/auth/identity.js");
  const { fingerprint }     = await import("./protocol/auth/identity.js");
  const { TrustedPeers }   = await import("./protocol/auth/storage.js");
  const { OpendeskServer } = await import("./remote/server.js");
  const { ToolDispatcher } = await import("./computer/dispatcher.js");
  const { createRegistry } = await import("./registry.js");
  const { allowAllContext, PermissionDeniedError } = await import("./tools/base.js");

  const identity = Identity.loadOrCreate(home);
  const trusted  = new TrustedPeers(home);

  if (!trusted.list().length) {
    fatal("no trusted peers yet — run 'opendesk-js pair' first to pair a controller", 2);
  }

  let ctx;
  if (approve === "console") {
    if (!process.stdin.isTTY) {
      process.stderr.write("WARNING: --approve console requires a TTY; falling back to auto-approve\n");
      ctx = allowAllContext();
    } else {
      const readline = await import("readline");
      ctx = {
        sessionId: "server",
        permissionHandler: async (tool: string, argument: string, description: string) => {
          const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
          const answer = await new Promise<string>((resolve) =>
            rl.question(`Allow ${tool}(${argument}) — ${description}? [y/N] `, resolve),
          );
          rl.close();
          if (!answer.trim().toLowerCase().startsWith("y")) {
            throw new PermissionDeniedError(`denied: ${tool}(${argument})`);
          }
        },
      };
    }
  } else {
    ctx = allowAllContext();
  }

  const { AuditLog } = await import("./remote/audit.js");
  const registry = createRegistry();
  const audit = new AuditLog({ home });
  const server = new OpendeskServer(identity, trusted, {
    host,
    port,
    home,
    advertise: !noMdns,
    audit,
    dispatcherFactory: ({ peerName, peerFingerprint, sessionId }) =>
      new ToolDispatcher({ registry, ctx, audit, peerName, peerFingerprint, sessionId, home }),
  });

  await server.start();
  const fp = fingerprint(identity.publicBytes);
  console.log(`opendesk serve  ${host}:${server.port}  fp=${fp}  approve=${approve}`);
  if (host === "0.0.0.0") {
    console.log("Listening on all interfaces. Ensure your firewall allows port " + server.port + " on trusted networks only.");
  }

  const shutdown = async () => {
    console.log("\nShutting down.");
    await server.close();
    process.exit(0);
  };
  process.on("SIGINT",  () => void shutdown());
  process.on("SIGTERM", () => void shutdown());

  // Block forever until signal
  await new Promise<void>(() => {});
}

// ---------------------------------------------------------------------------
// pair  (controlled machine — generates a code, waits for controller)
// ---------------------------------------------------------------------------

async function cmdPair(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const home      = resolveHome(str(flags["home"]) || undefined);
  const port      = validatePort(flags["port"] ?? 8423);
  const host      = str(flags["host"]) || "0.0.0.0";
  const noMdns    = bool(flags["no-mdns"]);
  const timeout   = num(flags["timeout"], 300) * 1000; // convert s → ms
  const rawCode   = str(flags["code"]) || undefined;
  const code      = rawCode ? validateCode(rawCode) : undefined;

  const { Identity }         = await import("./protocol/auth/identity.js");
  const { fingerprint, generatePairingCode } = await import("./protocol/auth/identity.js");
  const { TrustedPeers }    = await import("./protocol/auth/storage.js");
  const { OpendeskServer }  = await import("./remote/server.js");

  const identity  = Identity.loadOrCreate(home);
  const trusted   = new TrustedPeers(home);
  const pairingCode = code ?? generatePairingCode();

  const server = new OpendeskServer(identity, trusted, {
    host, port, home, advertise: !noMdns,
  });
  await server.start();

  const fp = fingerprint(identity.publicBytes);
  console.log();
  console.log("┌──────────────────────────────────────────────────────┐");
  console.log("│  opendesk pairing                                    │");
  console.log(`│  port:        ${String(server.port).padEnd(39)}│`);
  console.log(`│  fingerprint: ${fp.padEnd(39)}│`);
  console.log("│                                                      │");
  console.log(`│  pairing code:  ${pairingCode.padEnd(37)}│`);
  console.log("│                                                      │");
  console.log("│  On the controller machine run:                      │");
  console.log(`│    opendesk-js pair-with <host> ${pairingCode.padEnd(21)}│`);
  console.log("└──────────────────────────────────────────────────────┘");
  console.log();

  let newPubkey: Buffer | null;
  try {
    newPubkey = await server.enablePairing(pairingCode, timeout);
  } catch {
    newPubkey = null;
  }

  await server.close();

  if (!newPubkey) {
    fatal(`no peer paired within ${Math.floor(timeout / 1000)}s`);
  }

  const fp2  = fingerprint(newPubkey);
  const peer = trusted.find(newPubkey);
  const name = peer?.name ?? `peer-${newPubkey.toString("hex").slice(0, 6)}`;
  console.log(`Paired with ${name} (${fp2})`);
  console.log(`Use 'opendesk-js peers rename ${name} <friendly-name>' to give it a better name.`);
}

// ---------------------------------------------------------------------------
// pair-with  (controller machine — connects to a running opendesk pair)
// ---------------------------------------------------------------------------

async function cmdPairWith(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  if (pos.length < 2) fatal("usage: opendesk-js pair-with <host> <code> [--port=8423] [--name=<name>]");
  const [host, rawCode] = pos;
  const code = validateCode(rawCode);
  const port = validatePort(flags["port"] ?? 8423);
  const name = str(flags["name"]) || undefined;
  const home = resolveHome(str(flags["home"]) || undefined);

  const { fingerprint } = await import("./protocol/auth/identity.js");
  const { pairWith }    = await import("./remote/client.js");

  let remote, serverPubkey;
  try {
    ({ remote, serverPubkey } = await pairWith(host, port, code, { home, name }));
  } catch (e) {
    fatal(e instanceof Error ? e.message : String(e));
  }
  await remote.close();

  const fp       = fingerprint(serverPubkey);
  const peerName = name || `peer-${serverPubkey.toString("hex").slice(0, 6)}`;
  console.log(`Paired with ${peerName} (${fp})`);
  console.log(`Now reachable as: opendesk-js connect ${peerName}`);
}

// ---------------------------------------------------------------------------
// discover
// ---------------------------------------------------------------------------

async function cmdDiscover(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const timeout   = num(flags["timeout"], 2000);
  const { discover } = await import("./remote/discovery.js");
  const peers = await discover(timeout);
  if (!peers.length) { console.log("No opendesk peers found on the LAN."); return; }
  console.log(`${"NAME".padEnd(24)}  ${"ADDR".padEnd(22)}  ${"FINGERPRINT".padEnd(22)}  DESCRIPTION`);
  for (const p of peers) {
    const addr = `${p.host}:${p.port}`;
    const desc = (p.description ?? "").slice(0, 60);
    console.log(`${p.name.padEnd(24)}  ${addr.padEnd(22)}  ${p.fingerprint.padEnd(22)}  ${desc}`);
  }
}

// ---------------------------------------------------------------------------
// connect  (smoke test)
// ---------------------------------------------------------------------------

async function cmdConnect(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  const peer = pos[0] || undefined;
  const home = resolveHome(str(flags["home"]) || undefined);

  const { connect } = await import("./remote/client.js");

  let remote;
  try {
    remote = await connect(peer, { home });
  } catch (e) {
    fatal(e instanceof Error ? e.message : String(e));
  }

  try {
    const caps  = remote.capabilities();
    const label = peer ?? "default";
    console.log(`Connected to ${label}  backend=${caps.backend ?? "remote"}`);
    if (caps.description) console.log(`Description: ${caps.description}`);

    // Take a screenshot to exercise the full ToolDispatcher path
    const result = await remote.call("tool.screenshot", {});
    const atts   = (result?.["attachments"] as Array<{ mediaType: string; content: string }>) ?? [];
    const img    = atts.find((a) => a.mediaType.startsWith("image/"));
    if (img) {
      console.log("Screenshot: OK (received image data)");
    } else if (result?.["output"]) {
      console.log(`Screenshot response: ${String(result["output"]).slice(0, 80)}`);
    } else {
      console.log("Screenshot call returned (no image attached)");
    }
  } finally {
    await remote.close();
  }
}

// ---------------------------------------------------------------------------
// peers  (list | remove | rename | default | describe)
// ---------------------------------------------------------------------------

async function cmdPeers(argv: string[]): Promise<void> {
  const [sub, ...rest] = argv;
  const action = sub && !sub.startsWith("-") ? sub : "list";
  const subArgv = action === sub ? rest : argv;

  const { flags, pos } = parseFlags(subArgv);
  const home = resolveHome(str(flags["home"]) || undefined);
  const { TrustedPeers, effectiveDescription } = await import("./protocol/auth/storage.js");
  const store = new TrustedPeers(home);

  if (action === "list") {
    const peers = store.list();
    if (!peers.length) { console.log("No trusted peers."); return; }
    const def = store.getDefault();
    console.log(`${"NAME".padEnd(22)}  ${"FINGERPRINT".padEnd(22)}  ${"LAST ENDPOINT".padEnd(22)}  DESCRIPTION`);
    for (const p of peers) {
      const { fingerprint } = await import("./protocol/auth/identity.js");
      const fp       = fingerprint(Buffer.from(p.publicKey, "hex"));
      const endpoint = p.lastHost ? `${p.lastHost}:${p.lastPort}` : "(unknown)";
      let desc       = effectiveDescription(p);
      if (desc.length > 60) desc = desc.slice(0, 59) + "…";
      const marker   = p.name === def ? "  [default]" : "";
      console.log(`${p.name.padEnd(22)}  ${fp.padEnd(22)}  ${endpoint.padEnd(22)}  ${desc}${marker}`);
    }

  } else if (action === "remove") {
    const target = pos[0] || str(flags["target"]);
    if (!target) fatal("usage: opendesk-js peers remove <name-or-key>");
    if (!store.remove(target)) fatal(`no peer matched '${target}'`);
    console.log(`Removed ${target}.`);

  } else if (action === "rename") {
    const [target, newName] = pos;
    if (!target || !newName) fatal("usage: opendesk-js peers rename <target> <new-name>");
    if (!store.rename(target, newName)) fatal(`no peer matched '${target}'`);
    console.log(`Renamed ${target} → ${newName}.`);

  } else if (action === "default") {
    if (bool(flags["clear"])) {
      const cleared = store.clearDefault();
      console.log(cleared ? "Default peer cleared." : "No default peer was set.");
      return;
    }
    const name = pos[0] || str(flags["name"]) || undefined;
    if (!name) {
      const cur = store.getDefault();
      console.log(cur ? cur : "No default peer set.");
      return;
    }
    if (!store.setDefault(name)) fatal(`no trusted peer named '${name}'`);
    console.log(`Default peer is now: ${name}`);

  } else if (action === "describe") {
    const name = pos[0] || str(flags["name"]);
    if (!name) fatal("usage: opendesk-js peers describe <name> [text] [--clear]");

    if (bool(flags["clear"])) {
      if (!store.clearDescriptionOverride(name)) fatal(`no peer named '${name}'`);
      console.log(`Description override for ${name} cleared.`);
      return;
    }
    const text = pos[1] || str(flags["text"]) || undefined;
    if (!text) {
      const p = store.findByName(name);
      if (!p) fatal(`no peer named '${name}'`);
      if (p.descriptionOverride) console.log(`override:   ${p.descriptionOverride}`);
      if (p.description)         console.log(`broadcast:  ${p.description}`);
      if (!p.descriptionOverride && !p.description) {
        console.log("(no description set)");
      }
      return;
    }
    if (!store.setDescriptionOverride(name, text)) fatal(`no peer named '${name}'`);
    console.log(`Description override saved for ${name}.`);

  } else {
    fatal(`unknown peers subcommand: ${action}`);
  }
}

// ---------------------------------------------------------------------------
// unpair
// ---------------------------------------------------------------------------

async function cmdUnpair(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  const name = pos[0] || str(flags["name"]);
  if (!name) fatal("usage: opendesk-js unpair <name>");
  const home = resolveHome(str(flags["home"]) || undefined);
  const { TrustedPeers } = await import("./protocol/auth/storage.js");
  const store = new TrustedPeers(home);
  if (!store.remove(name)) fatal(`no peer matched '${name}'`);
  console.log(`Unpaired ${name}.`);
}

// ---------------------------------------------------------------------------
// describe  (broadcast description of THIS machine)
// ---------------------------------------------------------------------------

async function cmdDescribe(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  const home = resolveHome(str(flags["home"]) || undefined);
  const { readDescription, writeDescription, clearDescription } = await import("./remote/server.js");

  if (bool(flags["clear"])) {
    const cleared = clearDescription(home);
    console.log(cleared ? "Description cleared." : "No description was set.");
    return;
  }
  const text = pos[0] || str(flags["text"]) || undefined;
  if (!text) {
    const cur = readDescription(home);
    console.log(cur || "(no description set)");
    return;
  }
  writeDescription(home, text);
  console.log("Description saved. Next session will broadcast it.");
}

// ---------------------------------------------------------------------------
// sessions
// ---------------------------------------------------------------------------

async function cmdSessions(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const home = resolveHome(str(flags["home"]) || undefined);
  const { AdminClient, AdminError } = await import("./remote/admin.js");

  let client;
  try {
    client = await AdminClient.connect(home);
  } catch (e) {
    fatal(e instanceof AdminError ? e.message : String(e));
  }
  try {
    const sessions = await client.listSessions();
    if (!sessions.length) { console.log("No active session."); return; }
    console.log(`${"PEER".padEnd(22)}  ${"FROM".padEnd(22)}  ${"AGE".padEnd(8)}  ID`);
    for (const s of sessions) {
      console.log(
        `${s.peer_name.padEnd(22)}  ${s.remote_addr.padEnd(22)}  ${formatAge(s.age_seconds).padEnd(8)}  ${s.id}`,
      );
    }
  } finally {
    client.close();
  }
}

// ---------------------------------------------------------------------------
// disconnect  (cooperative eviction of the active controller)
// ---------------------------------------------------------------------------

async function cmdDisconnect(argv: string[]): Promise<void> {
  const { flags } = parseFlags(argv);
  const home = resolveHome(str(flags["home"]) || undefined);
  const { AdminClient, AdminError } = await import("./remote/admin.js");

  let client;
  try {
    client = await AdminClient.connect(home);
  } catch (e) {
    fatal(e instanceof AdminError ? e.message : String(e));
  }
  try {
    const n = await client.killAll();
    if (n === 0) { console.log("No active session to disconnect."); return; }
    console.log("Disconnected the active controller.");
  } finally {
    client.close();
  }
}

// ---------------------------------------------------------------------------
// audit
// ---------------------------------------------------------------------------

async function cmdAudit(argv: string[]): Promise<void> {
  const { pos, flags } = parseFlags(argv);
  if (pos[0] === "verify") {
    const { runSafetyCommand } = await import("./safety/cli.js");
    await runSafetyCommand("audit-verify", argv.filter((a) => a !== "verify"));
    return;
  }
  const home   = resolveHome(str(flags["home"]) || undefined);
  const date   = str(flags["date"]) || undefined;
  const peer   = str(flags["peer"]) || undefined;
  const limit  = num(flags["limit"], 0);
  const follow = bool(flags["follow"]);

  const { AuditLog } = await import("./remote/audit.js");
  type AuditEntry = import("./remote/audit.js").AuditEntry;
  const log = new AuditLog({ home });

  function printEntries(entries: AuditEntry[]): void {
    let filtered = peer
      ? entries.filter((e) => e.peer?.name === peer || e.peer?.fp?.startsWith(peer))
      : entries;
    if (limit > 0) filtered = filtered.slice(-limit);
    for (const e of filtered) {
      const d = new Date(e.ts * 1000).toISOString().replace("T", " ").replace("Z", "");
      const p = e.peer ? `${(e.peer.name || "?").padEnd(16)} ${e.peer.fp.slice(0, 8)}` : "?".padEnd(25);
      let detail = "";
      if (e.type === "call") {
        detail = `  ${(e.method ?? "").padEnd(18)} ${(e.outcome ?? "").padEnd(7)} ${e.duration_ms ?? 0}ms`;
        if (e.summary) detail += `  ${e.summary}`;
      } else if (e.reason) {
        detail = `  reason=${e.reason}`;
      }
      if (e.session_id) detail += `  sid=${e.session_id.slice(0, 12)}`;
      console.log(`${d}  ${e.type.padEnd(20)} ${p}${detail}`);
    }
  }

  if (follow) {
    let seen = 0;
    const tick = () => {
      const entries = log.iterEntries(date);
      if (entries.length > seen) {
        printEntries(entries.slice(seen));
        seen = entries.length;
      }
    };
    tick();
    const iv = setInterval(tick, 500);
    process.on("SIGINT", () => { clearInterval(iv); process.exit(0); });
    await new Promise<void>(() => {});
  } else {
    const entries = log.iterEntries(date);
    printEntries(entries);
    if (!entries.length) console.log("No audit entries for " + (date ?? "today") + ".");
  }
}

// ---------------------------------------------------------------------------
// memory  (screen memory — local searchable desktop history)
// ---------------------------------------------------------------------------

async function cmdMemory(argv: string[]): Promise<void> {
  const [sub0, ...rest] = argv;
  const sub = sub0 && !sub0.startsWith("-") ? sub0 : "status";
  const subArgv = sub === sub0 ? rest : argv;
  const { pos, flags } = parseFlags(subArgv);
  const home = resolveHome(str(flags["home"]) || undefined);

  switch (sub) {
    case "start": {
      const { startDaemon } = await import("./memory/recorder.js");
      const interval = flags["interval"] !== undefined ? num(flags["interval"], 0) : undefined;
      if (interval !== undefined && interval < 1) fatal("--interval must be >= 1 second");
      await startDaemon({ home, interval: interval || undefined });
      return;
    }
    case "status": {
      await memoryStatus(home);
      return;
    }
    case "pause": {
      const { parseDuration, setPause, describePause } = await import("./memory/config.js");
      const raw = pos[0] || str(flags["for"]) || "";
      let secs: number | undefined;
      if (raw) {
        try { secs = parseDuration(raw); } catch (e) { fatal((e as Error).message, 2); }
      }
      const state = setPause(home, { durationSeconds: secs, reason: "cli" });
      console.log(`Screen memory ${describePause(state)}.`);
      return;
    }
    case "resume": {
      const { clearPause } = await import("./memory/config.js");
      console.log(clearPause(home) ? "Screen memory resumed." : "Screen memory was not paused.");
      return;
    }
    case "search":
    case "timeline":
    case "show": {
      await memoryQuery(home, sub, pos, flags);
      return;
    }
    case "deny": {
      const { loadConfig, saveConfig } = await import("./memory/config.js");
      const cfg = loadConfig(home);
      const action = pos[0] && !["list"].includes(pos[0]) ? pos[0] : "list";
      const pattern = pos[1] ?? "";
      if (action === "add") {
        if (!pattern) fatal("usage: opendesk-js memory deny add <pattern>");
        console.log(cfg.denyAdd(pattern) ? `Added '${pattern}'.` : `'${pattern}' already listed.`);
        saveConfig(cfg, home);
      } else if (action === "remove") {
        if (!pattern) fatal("usage: opendesk-js memory deny remove <pattern>");
        console.log(cfg.denyRemove(pattern) ? `Removed '${pattern}'.` : `'${pattern}' not found.`);
        saveConfig(cfg, home);
      } else if (action !== "list") {
        fatal(`unknown deny subcommand: ${action}`);
      }
      console.log("Deny list (never captured):");
      for (const d of cfg.deny_apps) console.log(`  - ${d}`);
      if (!cfg.deny_apps.length) console.log("  (empty)");
      return;
    }
    case "config": {
      const { loadConfig, saveConfig } = await import("./memory/config.js");
      const cfg = loadConfig(home);
      let changed = false;
      if (flags["interval"] !== undefined) { cfg.interval_seconds = num(flags["interval"], cfg.interval_seconds); changed = true; }
      if (flags["cap"] !== undefined) { cfg.storage_cap_mb = Math.floor(num(flags["cap"], cfg.storage_cap_mb)); changed = true; }
      if (flags["retention"] !== undefined) { cfg.retention_days = Math.floor(num(flags["retention"], cfg.retention_days)); changed = true; }
      if (flags["hotkey"] !== undefined) { cfg.pause_hotkey = flags["hotkey"] === true ? "" : str(flags["hotkey"]); changed = true; }
      const onOff = (name: string): boolean | undefined => {
        if (flags[name] === undefined) return undefined;
        const v = str(flags[name]).toLowerCase();
        if (v !== "on" && v !== "off") fatal(`--${name} must be 'on' or 'off'`, 2);
        return v === "on";
      };
      if (flags["trigger"] !== undefined) {
        const t = str(flags["trigger"]).toLowerCase();
        if (t !== "events" && t !== "interval") fatal("--trigger must be 'events' or 'interval'", 2);
        cfg.trigger = t; changed = true;
      }
      if (flags["poll"] !== undefined) { cfg.poll_seconds = num(flags["poll"], cfg.poll_seconds); changed = true; }
      if (flags["min-interval"] !== undefined) { cfg.min_interval_seconds = num(flags["min-interval"], cfg.min_interval_seconds); changed = true; }
      const redactFlag = onOff("redact");
      if (redactFlag !== undefined) { cfg.redact = redactFlag; changed = true; }
      const beforeEnc = `${cfg.encrypt_text}/${cfg.encrypt_thumbnails}`;
      const encText = onOff("encrypt-text");
      if (encText !== undefined) { cfg.encrypt_text = encText; changed = true; }
      const encThumbs = onOff("encrypt-thumbnails");
      if (encThumbs !== undefined) { cfg.encrypt_thumbnails = encThumbs; changed = true; }
      if (changed) {
        cfg.normalize();
        console.log(`Saved ${saveConfig(cfg, home)}`);
        if (`${cfg.encrypt_text}/${cfg.encrypt_thumbnails}` !== beforeEnc) {
          console.log("  New frames use the new setting; run `opendesk-js memory reindex` to convert existing ones.");
        }
      }
      for (const [k, v] of Object.entries(cfg.toDict())) console.log(`  ${k}: ${Array.isArray(v) ? JSON.stringify(v) : v}`);
      return;
    }
    case "reindex": {
      const { loadConfig } = await import("./memory/config.js");
      const { MemoryStore } = await import("./memory/store.js");
      const cfg = loadConfig(home);
      const store = new MemoryStore(home, { config: cfg });
      const n = store.stats().frames;
      const what = [
        `text → ${cfg.encrypt_text ? "encrypted" : "plaintext"}`,
        `thumbnails → ${cfg.encrypt_thumbnails ? "encrypted" : "plaintext"}`,
        ...(cfg.redact ? ["redact secrets in old text"] : []),
      ].join("; ");
      if (!bool(flags["yes"]) && !bool(flags["y"])) {
        const readline = await import("readline");
        const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
        const answer = await new Promise<string>((resolve) => rl.question(`Rewrite ${n} frame(s) (${what})? [y/N] `, resolve));
        rl.close();
        if (!answer.trim().toLowerCase().startsWith("y")) { console.log("Cancelled."); return; }
      }
      const c = store.reindex({ redact: cfg.redact });
      console.log(
        `Reindexed ${c.frames} frame(s): text encrypted ${c.text_encrypted}, decrypted ${c.text_decrypted}; ` +
        `thumbnails encrypted ${c.thumbs_encrypted}, decrypted ${c.thumbs_decrypted}; redacted ${c.redacted}; failed ${c.failed}.`,
      );
      if (c.failed) console.log("  Failed frames could not be decrypted (memory key missing or replaced) and were left as-is.");
      return;
    }
    case "export": {
      const { exportMemory, EXPORT_FORMATS } = await import("./memory/export.js");
      const { parseRange } = await import("./memory/timeparse.js");
      const format = (str(flags["format"]) || "json") as (typeof EXPORT_FORMATS)[number];
      const limit = str(flags["limit"]) ? Number(str(flags["limit"])) : undefined;
      const noThumbs = bool(flags["no-thumbnails"]);
      let res;
      try {
        const [start, end] = parseRange(str(flags["since"]) || undefined, str(flags["until"]) || undefined);
        res = exportMemory(str(flags["out"]) || undefined, {
          home, format, start, end, app: str(flags["app"]) || null,
          query: str(flags["query"]) || null, thumbnails: !noThumbs, limit,
        });
      } catch (e) {
        fatal((e as Error).message, 2);
      }
      console.log(`✓ Exported ${res.frames} moment(s)${noThumbs ? "" : `, ${res.thumbnails} thumbnail(s)`} → ${res.file}`);
      for (const w of res.warnings) console.log(`  ! ${w}`);
      console.log("  The export is decrypted: it contains your screen history in plain form.");
      return;
    }
    case "clear": {
      const { MemoryStore } = await import("./memory/store.js");
      const { fmtRange, parseRange } = await import("./memory/timeparse.js");
      const store = new MemoryStore(home);
      const before = str(flags["before"]) || undefined;
      const app = str(flags["app"]) || undefined;
      let ids: number[] | null = null;
      let scope = "ALL frames";
      if (before || app) {
        let start = 0; let end: number | null = null;
        if (before) {
          try { [start, end] = parseRange(undefined, before); } catch (e) { fatal((e as Error).message, 2); }
        }
        ids = store.timeline({ start, end, app: app ?? null, limit: Infinity }).map((f) => f.id);
        scope = fmtRange(start, end) + (app ? `, app~'${app}'` : "");
      }
      const n = ids ? ids.length : store.stats().frames;
      if (!bool(flags["yes"]) && !bool(flags["y"])) {
        const readline = await import("readline");
        const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
        const answer = await new Promise<string>((resolve) => rl.question(`Delete ${n} frame(s) (${scope})? [y/N] `, resolve));
        rl.close();
        if (!answer.trim().toLowerCase().startsWith("y")) { console.log("Cancelled."); return; }
      }
      const deleted = ids ? store.delete(ids) : store.clear();
      console.log(`Deleted ${deleted} frame(s).`);
      return;
    }
    case "install-service": {
      const { installMemoryService } = await import("./memory/service.js");
      const interval = flags["interval"] !== undefined ? num(flags["interval"], 0) || undefined : undefined;
      let result;
      try {
        result = installMemoryService({ home, interval, autostart: !bool(flags["no-start"]) });
      } catch (e) {
        fatal((e as Error).message);
      }
      console.log(`Screen-memory service installed (${result.manager}): ${result.path}`);
      if (result.started) console.log("  Started.  It will also run automatically on next login.");
      else if (bool(flags["no-start"])) console.log("  Not started (--no-start).");
      else console.log("  WARNING: file written but the service manager could not start it.");
      return;
    }
    case "uninstall-service": {
      const { uninstallMemoryService } = await import("./memory/service.js");
      let removed = false;
      try { removed = uninstallMemoryService(); } catch (e) { fatal((e as Error).message); }
      console.log(removed ? "Screen-memory service removed." : "No screen-memory service was installed.");
      return;
    }
    default:
      fatal("usage: opendesk-js memory start|status|pause|resume|search|timeline|show|export|deny|config|reindex|clear|install-service|uninstall-service", 2);
  }
}

async function memoryStatus(home: string | undefined): Promise<void> {
  const { daemonAlive, describePause, getPause, loadConfig, readDaemonState } = await import("./memory/config.js");
  const { MemoryStore } = await import("./memory/store.js");
  const { fmtTs } = await import("./memory/timeparse.js");
  const cfg = loadConfig(home);
  const pause = getPause(home);
  const alive = daemonAlive(home);
  const state = readDaemonState(home);
  const store = new MemoryStore(home);
  const st = store.stats();
  const mb = (n: number) => (n / (1024 * 1024)).toFixed(1);
  console.log("opendesk screen memory (js)");
  console.log(alive
    ? `  daemon:    running (pid ${state?.pid}, last tick: ${state?.status ?? "?"})`
    : "  daemon:    not running — `opendesk-js memory start`");
  console.log(`  capture:   ${pause ? "PAUSED — " + describePause(pause) : "active"}`);
  console.log(`  store:     ${store.dir}`);
  const span = st.frames && st.oldest !== null && st.newest !== null ? `  (${fmtTs(st.oldest)} → ${fmtTs(st.newest)})` : "";
  console.log(`  frames:    ${st.frames}${span}`);
  console.log(`  size:      ${mb(st.totalBytes)} MB of ${cfg.storage_cap_mb} MB cap`);
  console.log(cfg.trigger === "interval"
    ? `  trigger:   interval — every ${cfg.interval_seconds}s`
    : `  trigger:   events — on app/window change (poll ${cfg.poll_seconds}s, ≥${cfg.min_interval_seconds}s apart), idle fallback ${cfg.interval_seconds}s`);
  console.log(`  retention: ${cfg.retention_days} days`);
  const srcs = Object.entries(st.textSources).sort().map(([k, v]) => `${k} ×${v}`).join(", ");
  if (srcs) console.log(`  text:      ${srcs}   redaction ${cfg.redact ? "on" : "off"}`);
  console.log(
    `  encrypt:   thumbnails ${cfg.encrypt_thumbnails ? "on" : "off"} (${st.encryptedThumbnails}/${st.thumbnails} stored encrypted); ` +
    `text ${cfg.encrypt_text ? "on" : "off"} (${st.encryptedTextFrames}/${st.frames}); key: ${st.keyStore ?? "not created yet"}`,
  );
  if (state?.["redactions"]) console.log(`  redacted:  ${state["redactions"]} secret(s) this daemon run`);
  console.log(`  deny list: ${cfg.deny_apps.join(", ") || "(empty)"}`);
  console.log(`  hotkey:    ${cfg.pause_hotkey || "(disabled)"}`);
  if (st.apps.length) console.log("  top apps:  " + st.apps.slice(0, 6).map(([a, n]) => `${a || "(unknown)"} ×${n}`).join(", "));
}

async function memoryQuery(home: string | undefined, sub: string, pos: string[], flags: Record<string, string | boolean>): Promise<void> {
  const { MemoryStore, frameWhen } = await import("./memory/store.js");
  const { fmtRange, parseRange } = await import("./memory/timeparse.js");
  const store = new MemoryStore(home);

  if (sub === "show") {
    const id = Number(pos[0]);
    if (!Number.isInteger(id)) fatal("usage: opendesk-js memory show <id>");
    const frame = store.get(id);
    if (!frame) fatal(`No frame with id ${id}.`);
    console.log(`#${frame.id}  ${frameWhen(frame)}  [${frame.app || "(unknown)"}]  ${frame.title}`);
    console.log(`text:      ${frame.text_source || "?"}${frame.encrypted ? " (encrypted at rest)" : ""}`);
    if (frame.thumb_path) {
      const save = str(flags["save"]);
      if (save) {
        const data = store.thumbnail(frame);
        if (!data) process.stderr.write("thumbnail: could not be read (missing, or the memory key is unavailable)\n");
        else {
          fs.writeFileSync(save, data);
          console.log(`thumbnail: saved ${data.length} bytes to ${save}`);
        }
      } else if (frame.thumb_path.endsWith(".enc")) {
        console.log(`thumbnail: ${path.join(store.dir, frame.thumb_path)} (encrypted — use --save out.jpg)`);
      } else {
        console.log(`thumbnail: ${path.join(store.dir, frame.thumb_path)}`);
      }
    }
    console.log();
    console.log(frame.encrypted && !frame.text ? "(encrypted text — memory key unavailable)" : frame.text || "(no text)");
    return;
  }

  let start = 0; let end: number | null = null;
  try {
    [start, end] = parseRange(str(flags["since"]) || undefined, str(flags["until"]) || undefined);
  } catch (e) {
    fatal((e as Error).message, 2);
  }
  const app = str(flags["app"]) || null;
  const limit = num(flags["limit"], sub === "search" ? 20 : 50);
  let frames;
  let label: string;
  if (sub === "search") {
    const query = pos.join(" ") || str(flags["query"]);
    if (!query) fatal("usage: opendesk-js memory search <query> [--since ..] [--until ..] [--app ..]");
    frames = store.search(query, { start, end, app, limit });
    label = `search '${query}'`;
  } else {
    frames = store.timeline({ start, end, app, limit });
    label = "timeline";
  }
  console.log(`${label} — ${fmtRange(start, end)}` + (app ? ` — app~'${app}'` : ""));
  if (!frames.length) { console.log("(no results)"); return; }
  for (const f of frames) {
    const title = f.title && f.title !== f.app ? `  ${f.title.slice(0, 60)}` : "";
    console.log(`#${String(f.id).padEnd(6)} ${frameWhen(f)}  [${f.app || "(unknown)"}]${title}`);
    if (sub === "search") {
      const snip = (f.snippet || f.text.slice(0, 120)).replace(/\n/g, " ").trim();
      if (snip) console.log(`        ${snip.slice(0, 200)}`);
    }
  }
}

// ---------------------------------------------------------------------------
// Help
// ---------------------------------------------------------------------------

function printHelp(): void {
  console.log(`opendesk-js — JavaScript SDK for opendesk

Controlled-machine commands (run on the machine to be controlled):
  serve         Long-running server — accepts paired controllers only
  pair          Accept one new controller (prints a pairing code)
  sessions      Show active controller session
  disconnect    Evict the active controller (peer stays paired)
  describe      Read / set / clear this machine's broadcast description
  audit         View the audit log (session opens, calls, rejections); 'audit verify' checks hash chains

Safety (see docs/safety.md):
  stop / resume        Kill switch — refuse every agent tool call / release it
  takeover / handback  You drive; agent calls are refused / hand control back
  secrets              set NAME | list | delete NAME  ({{secret:NAME}} placeholders; macOS Keychain)
  policy               show | preset <relaxed|standard|strict> | add-rule --tool ... --decision ... | remove-rule N

Controller commands (run on the machine that drives others):
  pair-with     Complete pairing with a machine running 'opendesk-js pair'
  discover      Find opendesk peers on the LAN
  connect       Smoke-test connection to a paired peer
  peers         Manage trusted peers (list | remove | rename | default | describe)
  unpair        Revoke a paired peer

Shared:
  agent         Local model agent over all registered tools (--model, --base-url, --vision)
  install       Register the native MCP server with Claude Code
  uninstall     Remove the MCP server registration from Claude Code
  mcp           Run the MCP server (stdio; --http [--host 127.0.0.1] [--port 8765]
                [--token T | --no-auth] for streamable HTTP with bearer auth)

Screen memory (local, searchable history of what was on screen):
  memory start            Run the capture daemon (--interval N, Ctrl-C to stop)
  memory status           Daemon state, storage usage, config
  memory pause [30m|2h]   Pause capture (optionally for a duration)
  memory resume           Resume capture
  memory search <query>   Full-text search (--since, --until, --app, --limit)
  memory timeline         List captured moments (--since, --until, --app)
  memory show <id>        One moment's full text + thumbnail (--save out.jpg decrypts it)
  memory export           Decrypted export (--out DIR, --format json|csv|html, --since, --until,
                          --app, --query, --limit, --no-thumbnails)
  memory deny [add|remove <pattern>]   Per-app / window-title deny list
  memory config           --trigger events|interval --interval N --poll S --min-interval S
                          --redact on|off --encrypt-text on|off --encrypt-thumbnails on|off
                          --cap MB --retention DAYS --hotkey '<ctrl>+<alt>+m'
  memory reindex          Rewrite stored frames under the current encryption/redaction settings (--yes)
  memory clear            Delete frames (--before <when>, --app <name>, --yes)
  memory install-service | uninstall-service   Run the daemon at login

Flags (common):
  --home=<dir>  Identity / trusted-peers directory (default: ~/.opendesk)

Examples:
  opendesk-js pair                          # start pairing on port 8423
  opendesk-js pair-with 192.168.1.42 123456 --name=laptop
  opendesk-js serve
  opendesk-js discover
  opendesk-js connect laptop
  opendesk-js peers list
  opendesk-js peers default laptop
  opendesk-js audit --date=2026-05-13 --peer=laptop --limit=50
  opendesk-js audit --follow
  opendesk-js memory start --interval=30
  opendesk-js memory search "invoice" --since="last week"
`);
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

export async function main(): Promise<void> {
  const [command, ...rest] = process.argv.slice(2);

  try {
    switch (command) {
      case "install":     return await cmdInstall(rest);
      case "uninstall":   return await cmdUninstall();
      case "mcp":         return await cmdMcp(rest);
      case "serve":       return await cmdServe(rest);
      case "pair":        return await cmdPair(rest);
      case "pair-with":   return await cmdPairWith(rest);
      case "discover":    return await cmdDiscover(rest);
      case "connect":     return await cmdConnect(rest);
      case "peers":       return await cmdPeers(rest);
      case "unpair":      return await cmdUnpair(rest);
      case "describe":    return await cmdDescribe(rest);
      case "sessions":    return await cmdSessions(rest);
      case "disconnect":  return await cmdDisconnect(rest);
      case "audit":       return await cmdAudit(rest);
      case "stop":
      case "resume":
      case "takeover":
      case "handback":
      case "secrets":
      case "policy": {
        const { runSafetyCommand } = await import("./safety/cli.js");
        await runSafetyCommand(command, rest);
        return;
      }
      case "agent":       return await cmdAgent(rest);
      case "memory":      return await cmdMemory(rest);
      default:
        printHelp();
        if (command && command !== "--help" && command !== "-h") {
          process.stderr.write(`Unknown command: ${command}\n`);
          process.exit(1);
        }
    }
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ERR_USE_AFTER_CLOSE" ||
        (e instanceof Error && e.message.includes("closed"))) {
      // Ignore clean shutdown errors
      return;
    }
    process.stderr.write(`ERROR: ${e instanceof Error ? e.message : String(e)}\n`);
    process.exit(1);
  }
}
