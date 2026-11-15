"""opendesk CLI — setup and utility commands."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import sys
from pathlib import Path


def _configure_logging(log_file: str | None = None) -> None:
    """Set up root logging for `opendesk serve`.

    Default: ``stderr`` only (good for systemd-journald and launchd).  When
    ``--log-file`` is given, also attach a :class:`RotatingFileHandler`
    (10 MB × 5 backups).
    """
    from logging.handlers import RotatingFileHandler

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8",
        )
        handlers.append(fh)

    root = logging.getLogger()
    # Clear any pre-existing handlers — keeps repeated invocations idempotent.
    for h in list(root.handlers):
        root.removeHandler(h)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    for h in handlers:
        h.setFormatter(fmt)
        root.addHandler(h)
    root.setLevel(logging.INFO)


def _find_mcp_binary() -> str:
    """Return the absolute path to opendesk-mcp in the current Python environment."""
    # Prefer the binary next to the current Python executable (same venv/conda env)
    import pathlib
    bin_dir = pathlib.Path(sys.executable).parent
    for name in ("opendesk-mcp", "opendesk-mcp.exe"):
        candidate = bin_dir / name
        if candidate.exists():
            return str(candidate)

    # Fall back to PATH
    found = shutil.which("opendesk-mcp")
    if found:
        return found

    raise RuntimeError(
        "opendesk-mcp not found. Make sure you installed with:\n"
        "  pip install opendesk   (or run it with: uvx opendesk mcp)"
    )


def cmd_install(scope: str = "user") -> None:
    """Register opendesk-mcp with Claude Code."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print(
            "ERROR: 'claude' command not found.\n"
            "Install Claude Code first: https://claude.ai/code",
            file=sys.stderr,
        )
        sys.exit(1)

    mcp_path = _find_mcp_binary()

    # Remove existing registration if any (ignore errors)
    subprocess.run(
        [claude_bin, "mcp", "remove", "opendesk"],
        capture_output=True,
    )

    result = subprocess.run(
        [claude_bin, "mcp", "add", "opendesk", f"--scope={scope}", "--", mcp_path],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"opendesk MCP server registered ({scope}).")
    print(f"  Binary: {mcp_path}")
    print("Start a Claude Code conversation and say 'take a screenshot' to verify.")


def cmd_uninstall() -> None:
    """Remove opendesk MCP registration from Claude Code."""
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("ERROR: 'claude' command not found.", file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(
        [claude_bin, "mcp", "remove", "opendesk"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print("opendesk MCP server removed from Claude Code.")
    print("To fully uninstall the package: pip uninstall opendesk")


# ---------------------------------------------------------------------------
# Remote — pair / serve / discover / connect / peers
# ---------------------------------------------------------------------------


def _remote_imports():
    """Lazy-import the remote stack so plain ``opendesk install`` doesn't need it."""
    try:
        from opendesk.protocol.auth import Identity, TrustedPeers
        from opendesk.protocol.auth.identity import generate_pairing_code
        from opendesk.remote.server import OpendeskServer, DEFAULT_PORT
    except ImportError as exc:
        print(
            f"ERROR: opendesk remote features require 'opendesk[remote]': {exc}",
            file=sys.stderr,
        )
        sys.exit(2)
    return Identity, TrustedPeers, generate_pairing_code, OpendeskServer, DEFAULT_PORT


def cmd_pair(args) -> None:
    """Run a one-shot pairing session and persist the new peer."""
    Identity, TrustedPeers, generate_pairing_code, OpendeskServer, DEFAULT_PORT = _remote_imports()
    from opendesk.computer import LocalComputer
    from opendesk.wsl import print_advisory_if_wsl

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print_advisory_if_wsl()
    home = Path(args.home).expanduser() if args.home else None
    code = args.code or generate_pairing_code()

    identity = Identity.load_or_create(home)
    trusted = TrustedPeers(home)
    computer = LocalComputer()

    async def _run() -> None:
        server = OpendeskServer(
            computer, identity, trusted,
            host=args.host, port=args.port,
            advertise_mdns=not args.no_mdns,
            home=home,
        )
        await server.start()
        print()
        print("┌──────────────────────────────────────────────┐")
        print("│  opendesk pairing                            │")
        print(f"│  port:        {args.port:<31}│")
        print(f"│  fingerprint: {':'.join(identity.public_bytes.hex()[i:i+4] for i in range(0, 16, 4)):<31}│")
        print("│                                              │")
        print(f"│   pairing code:   {code:<27}│")
        print("│                                              │")
        print("│  Run on the controller:                      │")
        print(f"│    opendesk pair-with <host> {code}            │")
        print("└──────────────────────────────────────────────┘")
        print()

        new_pub = await server.enable_pairing(code, timeout=args.timeout)
        if new_pub is None:
            print(f"ERROR: no peer paired within {args.timeout}s.", file=sys.stderr)
            await server.aclose()
            sys.exit(1)

        peer = trusted.find(new_pub)
        name = peer.name if peer else "?"
        print(f"✓ Paired with {name} ({':'.join(new_pub.hex()[i:i+4] for i in range(0, 16, 4))})")
        await server.aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nPairing cancelled.")
        sys.exit(130)


def cmd_pair_with(args) -> None:
    """Master-side counterpart: connect to a peer running ``opendesk pair`` and exchange keys."""
    Identity, TrustedPeers, _, _, _ = _remote_imports()
    from opendesk.remote.client import pair_with

    home = Path(args.home).expanduser() if args.home else None

    async def _run() -> None:
        remote, server_pub = await pair_with(
            args.host, args.port, args.code, home=home, name=args.name,
        )
        await remote.aclose()
        fp = ":".join(server_pub.hex()[i : i + 4] for i in range(0, 16, 4))
        name = args.name or f"peer-{server_pub.hex()[:6]}"
        print(f"✓ Paired with {name} ({fp})")
        print(f"  Now reachable as: opendesk connect {name}")

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_serve(args) -> None:
    """Long-running serve loop.  Accepts paired peers only."""
    _, TrustedPeers, _, OpendeskServer, DEFAULT_PORT = _remote_imports()
    from opendesk.protocol.auth import Identity
    from opendesk.computer import LocalComputer
    from opendesk.wsl import print_advisory_if_wsl

    _configure_logging(getattr(args, "log_file", None))
    print_advisory_if_wsl()
    home = Path(args.home).expanduser() if args.home else None
    identity = Identity.load_or_create(home)
    trusted = TrustedPeers(home)

    if not trusted.list():
        print(
            "ERROR: no trusted peers yet.  Run `opendesk pair` first.",
            file=sys.stderr,
        )
        sys.exit(2)

    async def _run() -> None:
        from opendesk.computer.permissions import check_all, report as report_perms
        statuses = check_all()
        if statuses and not all(s.granted for s in statuses):
            print(
                "WARNING: some platform permissions appear to be missing.  "
                "Affected operations will fail until granted.",
                file=sys.stderr,
            )
            report_perms(statuses, file=sys.stderr)
            print(
                "Run `opendesk check --open` to jump to the right "
                "System Settings pane.",
                file=sys.stderr,
            )

        from opendesk.remote.policy import AllowAllPolicy, ConsolePolicy, RulePolicy
        if args.approve == "policy":
            policy = RulePolicy(home)
        else:
            policy = AllowAllPolicy() if args.approve == "auto" else ConsolePolicy()

        server = OpendeskServer(
            LocalComputer(), identity, trusted,
            host=args.host, port=args.port,
            advertise_mdns=not args.no_mdns,
            home=home,
            policy=policy,
            enable_audit=not args.no_audit,
        )
        await server.start()
        fp = ":".join(identity.public_bytes.hex()[i : i + 4] for i in range(0, 16, 4))
        approve_suffix = "" if args.approve == "auto" else f"  approve={args.approve}"
        print(
            f"opendesk serve listening on {args.host}:{server.port}  "
            f"fp={fp}{approve_suffix}"
        )
        try:
            await server.serve_forever()
        finally:
            await server.aclose()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nShutting down.")
        sys.exit(0)


def cmd_discover(args) -> None:
    """List opendesk peers visible on the LAN."""
    try:
        from opendesk.remote.discovery import discover
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    from opendesk.wsl import print_advisory_if_wsl
    print_advisory_if_wsl()

    async def _run():
        peers = await discover(timeout=args.timeout)
        if not peers:
            print("No opendesk peers found on the LAN.")
            return
        print(f"{'NAME':<24}  {'ADDR':<22}  {'FINGERPRINT':<22}  DESCRIPTION")
        for p in peers:
            desc = (p.description or "")[:80]
            print(
                f"{p.name:<24}  {p.host + ':' + str(p.port):<22}  "
                f"{p.fingerprint:<22}  {desc}"
            )

    asyncio.run(_run())


def cmd_connect(args) -> None:
    """Smoke-test connection — pull capabilities + a screenshot."""
    try:
        from opendesk.remote.client import connect
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    async def _run():
        home = Path(args.home).expanduser() if args.home else None
        remote = await connect(args.peer, home=home)
        peer_label = args.peer or "default"
        try:
            caps = remote.capabilities()
            print(f"Connected to {peer_label}  backend={caps.backend}")
            print(f"Capabilities: {sorted(c.value for c in caps.capabilities)}")
            if args.screenshot:
                pixmap = await remote.capture()
                out = Path(args.screenshot).expanduser()
                out.write_bytes(pixmap.data)
                print(f"Saved screenshot ({pixmap.width}x{pixmap.height}) → {out}")
        finally:
            await remote.aclose()

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_check(args) -> None:
    """Check platform permissions required for opendesk to work."""
    from opendesk.computer.permissions import check_all, open_settings, report

    statuses = check_all()
    if not statuses:
        print("No platform permissions to check on this OS.")
        return
    print("opendesk permission check:")
    ok = report(statuses, file=sys.stdout)
    if ok:
        print("\nAll required permissions are granted.")
        return
    print()
    if args.open and not args.no_open:
        for s in statuses:
            if not s.granted and s.settings_url:
                open_settings(s.settings_url)
                break
        print("Opened the relevant System Settings pane.  Re-run `opendesk check` after granting.")
    sys.exit(1)


def cmd_audit(args) -> None:
    """Print server-side audit log entries (or follow them live)."""
    if getattr(args, "audit_cmd", None) == "verify":
        from opendesk.safety.cli import cmd_audit_verify
        cmd_audit_verify(args)
        return
    try:
        from opendesk.remote.audit import AuditLog
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    home = Path(args.home).expanduser() if args.home else None
    log = AuditLog(home=home)
    date = args.date  # may be None → today

    def _matches(entry: dict) -> bool:
        if args.peer:
            peer = (entry.get("peer") or {}).get("name") or ""
            fp = (entry.get("peer") or {}).get("fp") or ""
            if args.peer not in peer and args.peer not in fp:
                return False
        return True

    def _format(entry: dict) -> str:
        import datetime as _dt
        ts = entry.get("ts") or 0
        when = _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        peer = (entry.get("peer") or {}).get("name") or (entry.get("peer") or {}).get("fp") or "?"
        kind = entry.get("type", "?")
        if kind == "call":
            outcome = entry.get("outcome", "?")
            if outcome == "error":
                outcome = f"error/{entry.get('error_code', '?')}"
            method = entry.get("method", "?")
            summary = entry.get("summary") or method
            return f"{when}  {peer:<16}  {kind:<14}  {outcome:<22}  {summary}"
        if kind == "session.opened":
            return (
                f"{when}  {peer:<16}  {kind:<14}                          "
                f"id={entry.get('session_id', '?')} from {entry.get('remote_addr', '?')}"
            )
        if kind == "session.closed":
            return (
                f"{when}  {peer:<16}  {kind:<14}                          "
                f"id={entry.get('session_id', '?')}  "
                f"duration={entry.get('duration', 0)}s  reason={entry.get('reason', '')!r}"
            )
        if kind == "session.rejected":
            return (
                f"{when}  {peer:<16}  {kind:<14}                          "
                f"reason={entry.get('reason', '?')}  from {entry.get('remote_addr', '?')}"
            )
        return f"{when}  {peer:<16}  {kind}  {entry}"

    def _print_filtered(entries):
        if args.limit:
            entries = entries[-args.limit :]
        for e in entries:
            if _matches(e):
                print(_format(e))

    if not args.follow:
        _print_filtered(log.iter_entries(date=date))
        return

    # --follow: poll the day's file for new lines.
    import time
    path = log.directory / f"{date or _today_iso_local()}.jsonl"
    seen = 0
    if path.exists():
        existing = log.iter_entries(date=date)
        _print_filtered(existing)
        seen = len(existing)
    try:
        while True:
            time.sleep(0.5)
            current = log.iter_entries(date=date)
            if len(current) > seen:
                for e in current[seen:]:
                    if _matches(e):
                        print(_format(e))
                seen = len(current)
    except KeyboardInterrupt:
        sys.exit(0)


def _today_iso_local() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


def cmd_sessions(args) -> None:
    """List active opendesk-serve sessions via local IPC.

    With single-controller enforcement, this is always 0 or 1 entry.
    """
    try:
        from opendesk.remote.admin import AdminClient, AdminError
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    home = Path(args.home).expanduser() if args.home else None

    async def _run() -> int:
        try:
            client = await AdminClient.connect(home=home)
        except AdminError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        try:
            sessions = await client.list_sessions()
            if not sessions:
                print("No active session.")
                return 0
            print(f"{'PEER':<22}  {'FROM':<22}  {'AGE':<8}  ID")
            for s in sessions:
                age = _format_age(s.get("age_seconds", 0))
                print(
                    f"{s['peer_name']:<22}  {s['remote_addr']:<22}  "
                    f"{age:<8}  {s['id']}"
                )
            return 0
        finally:
            await client.aclose()

    sys.exit(asyncio.run(_run()))


def cmd_disconnect(args) -> None:
    """Kick the active controller off this machine.

    With single-controller enforcement there's at most one session; that
    one is closed.  The peer remains paired and can reconnect.
    """
    try:
        from opendesk.remote.admin import AdminClient, AdminError
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    home = Path(args.home).expanduser() if args.home else None

    async def _run() -> int:
        try:
            client = await AdminClient.connect(home=home)
        except AdminError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        try:
            n = await client.kill_all()
            if n == 0:
                print("No active session to disconnect.")
                return 0
            print(f"Disconnected the active controller.")
            return 0
        finally:
            await client.aclose()

    sys.exit(asyncio.run(_run()))


async def _disconnect_if_active(home, peer_name: str) -> bool:
    """Best-effort kick of any active session belonging to *peer_name*.

    Used by `peers remove` / `unpair` so revoking trust also drops the
    in-flight connection.  Returns ``True`` if a session was actually
    closed.  No-op (returns False) if the admin IPC is unreachable —
    revocation of trust still succeeded, the peer just won't be kicked
    until they next try to call something (which will then fail).

    The admin IPC server is one-shot per connection, so list and kill
    happen over two separate connect cycles.
    """
    try:
        from opendesk.remote.admin import AdminClient
    except ImportError:
        return False

    # 1. List sessions to find the right id.
    try:
        client = await AdminClient.connect(home=home)
    except Exception:
        return False
    try:
        sessions = await client.list_sessions()
    except Exception:
        sessions = []
    finally:
        await client.aclose()

    target_id = None
    for s in sessions:
        if s.get("peer_name") == peer_name:
            target_id = s.get("id")
            break
    if target_id is None:
        return False

    # 2. Fresh connection for the kill op.
    try:
        client = await AdminClient.connect(home=home)
    except Exception:
        return False
    try:
        return await client.kill(target_id)
    except Exception:
        return False
    finally:
        await client.aclose()


def _format_age(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def cmd_install_service(args) -> None:
    """Install opendesk serve as a systemd / launchd / Task Scheduler service."""
    try:
        from opendesk.remote.service import install_service
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    home = Path(args.home).expanduser() if args.home else None
    try:
        result = install_service(
            home=home, port=args.port, autostart=not args.no_start,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"✓ Service installed ({result.manager}): {result.path}")
    if result.started:
        print("  Started.  It will also run automatically on next login.")
    elif args.no_start:
        print("  Not started (--no-start).  Activate manually or rerun without the flag.")
    else:
        print(
            "  WARNING: file written but service manager could not start it. "
            "Activate manually.",
        )


def cmd_uninstall_service(args) -> None:
    try:
        from opendesk.remote.service import uninstall_service
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    try:
        removed = uninstall_service()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print("✓ Service uninstalled." if removed else "No opendesk service was installed.")


def _do_unpair(store, target: str, home) -> None:
    """Revoke trust for ``target`` and disconnect any active session.

    Shared between `opendesk unpair <name>` and `opendesk peers remove <name>`.
    """
    # Try to look up the friendly name before we mutate trusted-peers, so we
    # can match it against an active session.
    entry = store.find_by_name(target)
    peer_name_for_kick = entry.name if entry else target

    if not store.remove(target):
        print(f"No peer matched {target!r}.", file=sys.stderr)
        sys.exit(1)

    kicked = asyncio.run(_disconnect_if_active(home, peer_name_for_kick))
    if kicked:
        print(f"Unpaired {target} and disconnected the active session.")
    else:
        print(f"Unpaired {target}.")


def cmd_wsl_setup(args) -> None:
    """Print (or apply via UAC) Windows-side port forwarding for the WSL listener."""
    from opendesk.wsl import (
        is_wsl, render_setup_commands, render_undo_commands, run_via_uac,
        wsl_interface_ipv4,
    )

    if not is_wsl():
        print(
            "This command is for WSL instances only.  You don't seem to be "
            "inside one.",
            file=sys.stderr,
        )
        sys.exit(2)

    port = args.port
    wsl_ip = wsl_interface_ipv4()
    if not wsl_ip:
        print(
            "ERROR: couldn't determine the WSL IPv4 address.  Try running "
            "`hostname -I` to confirm WSL has a network interface.",
            file=sys.stderr,
        )
        sys.exit(1)

    cmds = render_undo_commands(port) if args.undo else render_setup_commands(port, wsl_ip)
    verb = "Removing" if args.undo else "Adding"

    if args.apply:
        print(
            f"{verb} Windows port-forward for opendesk on port {port}.  "
            "A UAC prompt should appear on the Windows host — accept it."
        )
        rc = run_via_uac(cmds)
        if rc != 0:
            print(
                f"ERROR: powershell.exe returned {rc}.  Are Windows interop "
                "binaries on PATH?",
                file=sys.stderr,
            )
            sys.exit(1)
        print("Done.  Verify with `netsh interface portproxy show all` "
              "from an elevated PowerShell.")
        return

    print(f"{verb} Windows-side port forwarding for opendesk.")
    print()
    print(f"  WSL IP:  {wsl_ip}")
    print(f"  Port:    {port}")
    print()
    print("Open an elevated PowerShell on the Windows host and run:")
    print()
    for line in cmds:
        print(f"  {line}")
    print()
    print(
        "Or rerun this command with --apply to trigger a UAC prompt and "
        "execute them for you."
    )


def cmd_app(args) -> None:
    """Launch the local opendesk app UI (FastAPI + uvicorn)."""
    try:
        from opendesk.app.app import run as run_app
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
    from opendesk.wsl import print_advisory_if_wsl
    print_advisory_if_wsl()
    home = Path(args.home).expanduser() if args.home else None
    try:
        run_app(
            home=home, host=args.host, port=args.port,
            open_browser=not args.no_browser,
        )
    except KeyboardInterrupt:
        sys.exit(0)


def cmd_describe(args) -> None:
    """Read / set / clear the controlled-machine's broadcast description."""
    try:
        from opendesk.remote.server import (
            clear_description, read_description, write_description,
        )
    except ImportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    home = Path(args.home).expanduser() if args.home else None
    if args.clear:
        cleared = clear_description(home)
        print("Description cleared." if cleared else "No description was set.")
        return
    if args.text is None:
        current = read_description(home)
        if current:
            print(current)
        else:
            print("(no description set)")
        return
    write_description(home, args.text)
    print("Description saved.  Next session will broadcast it.")


def cmd_peers_describe(args) -> None:
    """Set / clear / show the controller's local description-override for a peer."""
    _, TrustedPeers, _, _, _ = _remote_imports()
    home = Path(args.home).expanduser() if args.home else None
    store = TrustedPeers(home)

    if args.clear:
        if store.clear_description_override(args.name):
            print(f"Description override for {args.name} cleared.")
        else:
            print(f"No peer named {args.name!r}.", file=sys.stderr)
            sys.exit(1)
        return

    if args.text is None:
        peer = store.find_by_name(args.name)
        if peer is None:
            print(f"No peer named {args.name!r}.", file=sys.stderr)
            sys.exit(1)
        if peer.description_override:
            print(f"override: {peer.description_override}")
        if peer.description:
            print(f"broadcast: {peer.description}")
        if not (peer.description_override or peer.description):
            print("(no description yet — the peer hasn't broadcast one and no override is set)")
        return

    if not store.set_description_override(args.name, args.text):
        print(f"No peer named {args.name!r}.", file=sys.stderr)
        sys.exit(1)
    print(f"Description override saved for {args.name}.")


def cmd_unpair(args) -> None:
    """Revoke a paired peer (and disconnect them if currently active)."""
    _, TrustedPeers, _, _, _ = _remote_imports()
    home = Path(args.home).expanduser() if args.home else None
    store = TrustedPeers(home)
    _do_unpair(store, args.name, home)


def cmd_peers(args) -> None:
    """List, remove, rename, or set the default trusted peer."""
    _, TrustedPeers, _, _, _ = _remote_imports()
    home = Path(args.home).expanduser() if args.home else None
    store = TrustedPeers(home)
    action = args.peers_cmd or "list"

    if action == "list":
        peers = store.list()
        if not peers:
            print("No trusted peers.")
            return
        default = store.get_default()
        print(f"{'NAME':<22}  {'FINGERPRINT':<22}  {'LAST ENDPOINT':<22}  DESCRIPTION")
        for p in peers:
            marker = "  [default]" if p.name == default else ""
            endpoint = f"{p.last_host}:{p.last_port}" if p.last_host else "(unknown)"
            desc = p.effective_description.splitlines()[0] if p.effective_description else ""
            desc = desc[:60] + "…" if len(desc) > 60 else desc
            print(
                f"{p.name:<22}  {p.fingerprint:<22}  {endpoint:<22}  {desc}{marker}"
            )
    elif action == "remove":
        _do_unpair(store, args.target, home)
    elif action == "rename":
        if store.rename(args.target, args.new_name):
            print(f"Renamed {args.target} → {args.new_name}.")
        else:
            print(f"No peer matched {args.target!r}.", file=sys.stderr)
            sys.exit(1)
    elif action == "describe":
        cmd_peers_describe(args)
        return
    elif action == "default":
        if args.clear:
            cleared = store.clear_default()
            print("Default peer cleared." if cleared else "No default peer was set.")
            return
        if args.name is None:
            current = store.get_default()
            if current is None:
                print("No default peer set.")
            else:
                print(current)
            return
        if not store.set_default(args.name):
            print(f"No trusted peer named {args.name!r}.", file=sys.stderr)
            sys.exit(1)
        print(f"Default peer is now: {args.name}")


def cmd_scheduler(args) -> None:
    """Run the scheduler daemon."""
    from pathlib import Path
    project_dir = Path(args.dir).resolve() if args.dir else Path.cwd()

    if args.scheduler_cmd == "start":
        from opendesk.automation.daemon import start_daemon
        start_daemon(project_dir)
    elif args.scheduler_cmd == "list":
        from opendesk.automation.schedule_store import ScheduleStore
        store = ScheduleStore(project_dir)
        entries = store.all()
        if not entries:
            print("No schedules.")
        for e in entries:
            status = "on" if e.enabled else "off"
            print(f"  [{status}] {e.name}  ({e.timing})  →  {e.task}")
    else:
        print("Usage: opendesk scheduler start|list")


# ---------------------------------------------------------------------------
# Screen memory — searchable desktop history
# ---------------------------------------------------------------------------


def cmd_memory(args) -> None:
    """``opendesk memory <start|status|pause|resume|search|timeline|show|export|deny|config|reindex|clear|install-service|uninstall-service>``."""
    home = Path(args.home).expanduser() if getattr(args, "home", None) else None
    sub = args.memory_cmd or "status"

    if sub == "start":
        from opendesk.memory.recorder import start_daemon
        from opendesk.wsl import print_advisory_if_wsl
        _configure_logging(getattr(args, "log_file", None))
        print_advisory_if_wsl()
        start_daemon(home, interval=args.interval)
        return

    if sub == "status":
        _memory_status(home)
        return

    if sub == "pause":
        from opendesk.memory.config import parse_duration, set_pause
        secs = None
        if args.duration:
            try:
                secs = parse_duration(args.duration)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(2)
        state = set_pause(home, duration_seconds=secs, reason="cli")
        print(f"Screen memory {state.describe()}.")
        return

    if sub == "resume":
        from opendesk.memory.config import clear_pause
        print("Screen memory resumed." if clear_pause(home) else "Screen memory was not paused.")
        return

    if sub in ("search", "timeline", "show"):
        _memory_query(home, sub, args)
        return

    if sub == "deny":
        from opendesk.memory.config import load_config, save_config
        cfg = load_config(home)
        action = args.deny_cmd or "list"
        if action == "add":
            print(f"Added {args.pattern!r}." if cfg.deny_add(args.pattern) else f"{args.pattern!r} already listed.")
            save_config(cfg, home)
        elif action == "remove":
            print(f"Removed {args.pattern!r}." if cfg.deny_remove(args.pattern) else f"{args.pattern!r} not found.")
            save_config(cfg, home)
        print("Deny list (never captured):")
        for d in cfg.deny_apps:
            print(f"  - {d}")
        if not cfg.deny_apps:
            print("  (empty)")
        return

    if sub == "config":
        from opendesk.memory.config import load_config, save_config
        cfg = load_config(home)
        changed = False
        if args.interval is not None:
            cfg.interval_seconds = float(args.interval); changed = True
        if args.cap is not None:
            cfg.storage_cap_mb = int(args.cap); changed = True
        if args.retention is not None:
            cfg.retention_days = int(args.retention); changed = True
        if args.hotkey is not None:
            cfg.pause_hotkey = args.hotkey; changed = True
        if args.trigger is not None:
            cfg.trigger = args.trigger; changed = True
        if args.poll is not None:
            cfg.poll_seconds = float(args.poll); changed = True
        if args.min_interval is not None:
            cfg.min_interval_seconds = float(args.min_interval); changed = True
        if args.redact is not None:
            cfg.redact = args.redact == "on"; changed = True
        before_enc = (cfg.encrypt_text, cfg.encrypt_thumbnails)
        if args.encrypt_text is not None:
            cfg.encrypt_text = args.encrypt_text == "on"; changed = True
        if args.encrypt_thumbnails is not None:
            cfg.encrypt_thumbnails = args.encrypt_thumbnails == "on"; changed = True
        if changed:
            cfg.normalize()
            path = save_config(cfg, home)
            print(f"Saved {path}")
            if (cfg.encrypt_text, cfg.encrypt_thumbnails) != before_enc:
                print("  New frames use the new setting; run `opendesk memory reindex` to convert existing ones.")
        for k, v in cfg.to_dict().items():
            print(f"  {k}: {v}")
        return

    if sub == "reindex":
        from opendesk.memory.config import load_config
        from opendesk.memory.store import MemoryStore
        cfg = load_config(home)
        with MemoryStore(home, config=cfg) as store:
            n = store.stats().frames
            what = [
                f"text → {'encrypted' if cfg.encrypt_text else 'plaintext'}",
                f"thumbnails → {'encrypted' if cfg.encrypt_thumbnails else 'plaintext'}",
            ]
            if cfg.redact:
                what.append("redact secrets in old text")
            if not args.yes:
                answer = input(f"Rewrite {n} frame(s) ({'; '.join(what)})? [y/N] ")
                if answer.strip().lower() not in ("y", "yes"):
                    print("Cancelled.")
                    return

            def _progress(done: int, total: int) -> None:
                print(f"\r  {done}/{total}", end="", flush=True)

            counts = store.reindex(redact=cfg.redact, progress=_progress if n > 200 else None)
        if n > 200:
            print()
        print(
            "Reindexed {frames} frame(s): text encrypted {text_encrypted}, decrypted {text_decrypted}; "
            "thumbnails encrypted {thumbs_encrypted}, decrypted {thumbs_decrypted}; "
            "redacted {redacted}; failed {failed}.".format(**counts)
        )
        if counts["failed"]:
            print("  Failed frames could not be decrypted (memory key missing or replaced) and were left as-is.")
        return

    if sub == "export":
        from opendesk.memory.export import export_memory
        from opendesk.memory.timeparse import parse_range
        try:
            start, end = parse_range(args.since, args.until)
            res = export_memory(
                Path(args.out) if args.out else None, home=home, fmt=args.format,
                start=start, end=end, app=args.app, query=args.query,
                thumbnails=not args.no_thumbnails, limit=args.limit,
            )
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        thumbs = f", {res.thumbnails} thumbnail(s)" if not args.no_thumbnails else ""
        print(f"✓ Exported {res.frames} moment(s){thumbs} → {res.file}")
        for w in res.warnings:
            print(f"  ! {w}")
        print("  The export is decrypted: it contains your screen history in plain form.")
        return

    if sub == "clear":
        from opendesk.memory.store import MemoryStore
        from opendesk.memory.timeparse import fmt_range, parse_range
        with MemoryStore(home) as store:
            if args.before or args.app:
                start, end = parse_range(None, args.before) if args.before else (0.0, None)
                frames = store.timeline(start=start, end=end, app=args.app, limit=10_000_000)
                ids = [f.id for f in frames]
                scope = fmt_range(start, end) + (f", app~{args.app!r}" if args.app else "")
            else:
                ids = None
                scope = "ALL frames"
            n = len(ids) if ids is not None else store.stats().frames
            if not args.yes:
                answer = input(f"Delete {n} frame(s) ({scope})? [y/N] ")
                if answer.strip().lower() not in ("y", "yes"):
                    print("Cancelled.")
                    return
            deleted = store.delete(ids) if ids is not None else store.clear()
        print(f"Deleted {deleted} frame(s).")
        return

    if sub == "install-service":
        from opendesk.memory.service import install_memory_service
        try:
            result = install_memory_service(
                home=home, interval=args.interval, autostart=not args.no_start,
            )
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ Screen-memory service installed ({result.manager}): {result.path}")
        if result.started:
            print("  Started.  It will also run automatically on next login.")
        elif args.no_start:
            print("  Not started (--no-start).")
        else:
            print("  WARNING: file written but the service manager could not start it.")
        return

    if sub == "uninstall-service":
        from opendesk.memory.service import uninstall_memory_service
        try:
            removed = uninstall_memory_service()
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(1)
        print("✓ Screen-memory service removed." if removed else "No screen-memory service was installed.")
        return

    print("Usage: opendesk memory start|status|pause|resume|search|timeline|show|export|deny|config|reindex|clear")


def _memory_status(home) -> None:
    from opendesk.memory.config import daemon_alive, get_pause, load_config, read_daemon_state
    from opendesk.memory.store import MemoryStore
    from opendesk.memory.timeparse import fmt_ts

    cfg = load_config(home)
    pause = get_pause(home)
    alive = daemon_alive(home)
    state = read_daemon_state(home) or {}
    with MemoryStore(home) as store:
        st = store.stats()
        store_dir = store.dir
        fts = store.has_fts
    mb = lambda n: f"{n / (1024 * 1024):.1f}"  # noqa: E731
    print("opendesk screen memory")
    if alive:
        print(f"  daemon:    running (pid {state.get('pid')}, last tick: {state.get('status', '?')})")
    else:
        print("  daemon:    not running — `opendesk memory start`")
    print(f"  capture:   {'PAUSED — ' + pause.describe() if pause else 'active'}")
    print(f"  store:     {store_dir}")
    span = f"  ({fmt_ts(st.oldest)} → {fmt_ts(st.newest)})" if st.frames and st.oldest and st.newest else ""
    print(f"  frames:    {st.frames}{span}")
    print(f"  size:      {mb(st.total_bytes)} MB of {cfg.storage_cap_mb} MB cap")
    if cfg.trigger == "interval":
        trig = f"interval — every {cfg.interval_seconds:g}s"
    else:
        trig = (f"events — on app/window change (poll {cfg.poll_seconds:g}s, "
                f"≥{cfg.min_interval_seconds:g}s apart), idle fallback {cfg.interval_seconds:g}s")
    print(f"  trigger:   {trig}")
    print(f"  retention: {cfg.retention_days} days")
    if st.text_sources:
        print("  text:      " + ", ".join(f"{k} ×{v}" for k, v in sorted(st.text_sources.items()))
              + f"   redaction {'on' if cfg.redact else 'off'}")
    enc_bits = [
        f"thumbnails {'on' if cfg.encrypt_thumbnails else 'off'} ({st.encrypted_thumbnails}/{st.thumbnails} stored encrypted)",
        f"text {'on' if cfg.encrypt_text else 'off'} ({st.encrypted_text_frames}/{st.frames})",
    ]
    key = st.key_store or "not created yet"
    print(f"  encrypt:   {'; '.join(enc_bits)}; key: {key}")
    if not st.encryption_available:
        print("             WARNING: 'cryptography' not installed — new frames are stored unencrypted")
    if state.get("redactions"):
        print(f"  redacted:  {state.get('redactions')} secret(s) this daemon run")
    print(f"  deny list: {', '.join(cfg.deny_apps) or '(empty)'}")
    print(f"  hotkey:    {cfg.pause_hotkey or '(disabled)'}")
    print(f"  search:    {'FTS5' if fts else 'LIKE fallback'}")
    if st.apps:
        print("  top apps:  " + ", ".join(f"{a or '(unknown)'} ×{n}" for a, n in st.apps[:6]))


def _memory_query(home, sub: str, args) -> None:
    from opendesk.memory.store import MemoryStore
    from opendesk.memory.timeparse import fmt_range, parse_range

    try:
        start, end = parse_range(getattr(args, "since", None), getattr(args, "until", None))
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(2)

    with MemoryStore(home) as store:
        if sub == "show":
            frame = store.get(args.id)
            if frame is None:
                print(f"No frame with id {args.id}.", file=sys.stderr)
                sys.exit(1)
            print(f"#{frame.id}  {frame.when}  [{frame.app or '(unknown)'}]  {frame.title}")
            src = frame.text_source or "?"
            print(f"text:      {src}{' (encrypted at rest)' if frame.encrypted else ''}")
            if frame.thumb_path:
                encrypted = frame.thumb_path.endswith(".enc")
                save = getattr(args, "save", None)
                if save:
                    data = store.thumbnail(frame)
                    if data is None:
                        print("thumbnail: could not be read (missing, or the memory key is unavailable)",
                              file=sys.stderr)
                    else:
                        Path(save).expanduser().write_bytes(data)
                        print(f"thumbnail: saved {len(data)} bytes to {save}")
                elif encrypted:
                    print(f"thumbnail: {store.dir / frame.thumb_path} (encrypted — use --save out.jpg)")
                else:
                    print(f"thumbnail: {store.dir / frame.thumb_path}")
            print()
            if frame.encrypted and not frame.text:
                print("(encrypted text — memory key unavailable)")
            else:
                print(frame.text or "(no text)")
            return
        if sub == "search":
            frames = store.search(args.query, start=start, end=end, app=args.app, limit=args.limit)
        else:
            frames = store.timeline(start=start, end=end, app=args.app, limit=args.limit)

    label = f"{sub} {args.query!r}" if sub == "search" else "timeline"
    print(f"{label} — {fmt_range(start, end)}" + (f" — app~{args.app!r}" if args.app else ""))
    if not frames:
        print("(no results)")
        return
    for f in frames:
        title = f"  {f.title[:60]}" if f.title and f.title != f.app else ""
        print(f"#{f.id:<6} {f.when}  [{f.app or '(unknown)'}]{title}")
        if sub == "search":
            snip = (f.snippet or f.text[:120]).replace("\n", " ").strip()
            if snip:
                print(f"        {snip[:200]}")


# ---------------------------------------------------------------------------
# Fleet — one tool call across many peers
# ---------------------------------------------------------------------------


def cmd_fleet(args) -> None:
    """``opendesk fleet run --peers a,b|all --tool screenshot --params '{}'``."""
    if args.fleet_cmd != "run":
        print("Usage: opendesk fleet run --peers a,b|all --tool <tool> [--params JSON]")
        sys.exit(2)
    import json
    try:
        inner_params = json.loads(args.params or "{}")
        if not isinstance(inner_params, dict):
            raise ValueError("must be a JSON object")
    except ValueError as exc:
        print(f"ERROR: --params: {exc}", file=sys.stderr)
        sys.exit(2)

    from opendesk.integrations.mcp_session import MCPSession
    from opendesk.registry import create_registry
    from opendesk.tools.base import ToolContext
    from opendesk.tools.fleet import FleetTool

    home = Path(args.home).expanduser() if args.home else None

    async def _run():
        session = MCPSession(home=home)
        registry = create_registry()
        tool = FleetTool(session=session, registry=registry)
        try:
            params = tool.parse_params({
                "peers": args.peers, "tool": args.tool, "params": inner_params,
                "match": args.match, "concurrency": args.concurrency,
                "timeout": args.timeout, "include_images": bool(args.save_images),
            })
            return await tool.execute(ToolContext(session_id="cli-fleet", computer=session.local), params)
        finally:
            await session.aclose()

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(result.output)
    if args.save_images and result.attachments:
        out_dir = Path(args.save_images).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        for att in result.attachments:
            dest = out_dir / att.filename
            dest.write_bytes(att.content)
            print(f"saved {dest}")
    sys.exit(1 if result.error else 0)


def cmd_mcp(argv: list[str]) -> None:
    """``opendesk mcp [...]`` — run the MCP server (same flags as ``opendesk-mcp``)."""
    from opendesk.integrations.mcp import main as mcp_main
    mcp_main(argv, prog="opendesk mcp")


def main() -> None:
    import argparse

    # `opendesk mcp ...` forwards every remaining flag to the MCP server's own
    # parser (so `uvx opendesk mcp --transport http` works verbatim).
    if len(sys.argv) > 1 and sys.argv[1] == "mcp":
        cmd_mcp(sys.argv[2:])
        return

    parser = argparse.ArgumentParser(
        prog="opendesk",
        description=(
            "OpenDesk by VitalOps — open-source computer-use MCP server and SDK "
            "for macOS, Windows and Linux desktops."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "mcp",
        help=(
            "Run the MCP server (stdio by default; --transport http for streamable "
            "HTTP). See `opendesk mcp --help`."
        ),
        add_help=False,
    )

    install_p = sub.add_parser("install", help="Register opendesk with Claude Code")
    install_p.add_argument(
        "--scope",
        choices=["user", "project"],
        default="user",
        help="user = all projects (default), project = current project only",
    )

    sub.add_parser("uninstall", help="Remove opendesk from Claude Code")

    sched_p = sub.add_parser("scheduler", help="Manage the background task scheduler")
    sched_p.add_argument(
        "scheduler_cmd",
        choices=["start", "list"],
        help="start: run the scheduler daemon  |  list: show scheduled tasks",
    )
    sched_p.add_argument(
        "--dir",
        default=None,
        help="Project directory (default: current directory)",
    )

    # --- Remote (controlled machine) ----------------------------------

    pair_p = sub.add_parser(
        "pair",
        help="Accept one new controller (prints a code; controller types it on `pair-with`)",
    )
    pair_p.add_argument("--port", type=int, default=8423, help="WebSocket port (default 8423)")
    pair_p.add_argument("--host", default="0.0.0.0", help="Interface to bind (default 0.0.0.0)")
    pair_p.add_argument("--code", default=None, help="Use this code instead of a random one")
    pair_p.add_argument("--timeout", type=float, default=300.0, help="Seconds to wait for a peer")
    pair_p.add_argument("--home", default=None, help="Identity / trusted-peers directory")
    pair_p.add_argument("--no-mdns", action="store_true", help="Disable mDNS advertisement")

    serve_p = sub.add_parser(
        "serve",
        help=(
            "Run the long-lived opendesk server (paired peers only). "
            "One controller at a time; a different peer trying to connect "
            "while one is active is rejected with BUSY."
        ),
    )
    serve_p.add_argument("--port", type=int, default=8423)
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--home", default=None)
    serve_p.add_argument("--no-mdns", action="store_true")
    serve_p.add_argument(
        "--approve",
        choices=["auto", "console", "policy"],
        default="auto",
        help=(
            "How to gate inbound calls.  auto = allow everything (default, "
            "safe for paired single-user setups).  console = prompt on stdin "
            "for non-observation methods (input, fs.write, process.shell, "
            "etc.).  Console mode requires a TTY; under systemd/launchd "
            "gated calls are denied.  policy = apply policy.json rules and "
            "the `opendesk stop` / `takeover` kill switch (see docs/safety.md)."
        ),
    )
    serve_p.add_argument(
        "--no-audit", action="store_true",
        help="Don't write audit-log entries to ~/.opendesk/audit/",
    )
    serve_p.add_argument(
        "--log-file", default=None,
        help=(
            "Path to a rotating log file (10 MB × 5 backups).  Without this, "
            "Python logs go to stderr — fine under systemd (journald captures "
            "them) or launchd (StandardErrorPath is set in the plist), but "
            "Windows Task Scheduler users may want this."
        ),
    )

    # --- Remote (controller machine) ----------------------------------

    pw_p = sub.add_parser(
        "pair-with",
        help="Pair this machine with a peer running `opendesk pair`",
    )
    pw_p.add_argument("host", help="Hostname or IP of the controlled machine")
    pw_p.add_argument("code", help="6-digit code shown on the peer")
    pw_p.add_argument("--port", type=int, default=8423)
    pw_p.add_argument("--name", default="", help="Friendly name for the new peer")
    pw_p.add_argument("--home", default=None)

    disc_p = sub.add_parser("discover", help="List opendesk peers on the LAN")
    disc_p.add_argument("--timeout", type=float, default=2.0)

    conn_p = sub.add_parser("connect", help="Open a paired peer and confirm it works")
    conn_p.add_argument(
        "peer", nargs="?",
        help="Friendly name from `opendesk peers list`.  Omit to use the persistent default.",
    )
    conn_p.add_argument("--screenshot", default=None, help="Path to save a captured screenshot")
    conn_p.add_argument("--home", default=None)

    wsl_p = sub.add_parser(
        "wsl-setup",
        help=(
            "(WSL only) Print or apply Windows-side port forwarding so other "
            "devices on the LAN can reach this WSL instance's opendesk listener."
        ),
    )
    wsl_p.add_argument("--port", type=int, default=8423)
    wsl_p.add_argument(
        "--apply", action="store_true",
        help="Trigger a UAC prompt on the Windows host and run the commands.",
    )
    wsl_p.add_argument(
        "--undo", action="store_true",
        help="Print / apply the cleanup commands instead.",
    )

    app_p = sub.add_parser(
        "app",
        help=(
            "Launch the local opendesk UI on http://127.0.0.1:8424.  "
            "Starts an OpendeskServer in the background so this machine "
            "can be controlled, and lets you control paired hosts from "
            "the browser."
        ),
    )
    app_p.add_argument("--port", type=int, default=8424)
    app_p.add_argument("--host", default="127.0.0.1")
    app_p.add_argument("--home", default=None)
    app_p.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open a browser tab.",
    )

    desc_p = sub.add_parser(
        "describe",
        help=(
            "Read / set / clear the broadcast description of this machine. "
            "Agents on paired controllers see this on each connect and use "
            "it to route work (e.g. 'billing machine', 'ERP terminal')."
        ),
    )
    desc_p.add_argument("text", nargs="?", help="New description; omit to show current.")
    desc_p.add_argument("--clear", action="store_true", help="Remove the description.")
    desc_p.add_argument("--home", default=None)

    chk_p = sub.add_parser(
        "check",
        help="Verify platform permissions (macOS Accessibility / Screen Recording)",
    )
    chk_p.add_argument(
        "--open", action="store_true",
        help="Open the System Settings pane for the first missing permission.",
    )
    chk_p.add_argument(
        "--no-open", action="store_true",
        help="Override --open; only print the report.",
    )

    aud_p = sub.add_parser(
        "audit",
        help="Print the server-side audit log (controlled machine); `audit verify` checks hash chains",
    )
    aud_p.add_argument(
        "audit_cmd", nargs="?", choices=["verify"], default=None,
        help="verify = check the tamper-evident hash chains (all days, or --date)",
    )
    aud_p.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    aud_p.add_argument("--peer", default=None, help="Filter by peer name or fingerprint substring")
    aud_p.add_argument("--limit", type=int, default=None, help="Show only the most recent N entries")
    aud_p.add_argument(
        "--follow", "-f", action="store_true",
        help="Stream new entries as they're written (like tail -f)",
    )
    aud_p.add_argument("--home", default=None)

    sess_p = sub.add_parser(
        "sessions",
        help="Show the active controller session (controlled machine)",
    )
    sess_p.add_argument("--home", default=None)

    disc_p = sub.add_parser(
        "disconnect",
        help=(
            "Ask the active controller to leave (cooperative; sends "
            "session.evicted PUSH and closes).  Peer stays paired.  For "
            "enforced kicks of misbehaving peers use `opendesk unpair`."
        ),
    )
    disc_p.add_argument("--home", default=None)

    unp_p = sub.add_parser(
        "unpair",
        help="Revoke a paired controller (and disconnect them if active)",
    )
    unp_p.add_argument("name", help="Friendly name from `opendesk peers list`")
    unp_p.add_argument("--home", default=None)

    inst_p = sub.add_parser(
        "install-service",
        help="Install opendesk serve as a user-scoped system service",
    )
    inst_p.add_argument("--port", type=int, default=8423)
    inst_p.add_argument("--home", default=None)
    inst_p.add_argument(
        "--no-start", action="store_true",
        help="Only write the service file; don't activate it now",
    )

    sub.add_parser(
        "uninstall-service",
        help="Remove the opendesk serve system service",
    )

    peers_p = sub.add_parser("peers", help="List, remove, rename, or set default trusted peer")
    peers_p.add_argument("--home", default=None)
    peers_sub = peers_p.add_subparsers(dest="peers_cmd")
    list_p = peers_sub.add_parser("list", help="List trusted peers (default action)")
    list_p.add_argument("--home", default=None)
    rm_p = peers_sub.add_parser("remove", help="Forget a trusted peer")
    rm_p.add_argument("target", help="Peer name or fingerprint")
    rm_p.add_argument("--home", default=None)
    ren_p = peers_sub.add_parser("rename", help="Rename a trusted peer")
    ren_p.add_argument("target")
    ren_p.add_argument("new_name")
    ren_p.add_argument("--home", default=None)
    def_p = peers_sub.add_parser(
        "default",
        help=(
            "Get / set / clear the persistent default peer.  When set, "
            "`opendesk connect` without an argument and the MCP server's "
            "implicit default both resolve to this peer."
        ),
    )
    def_p.add_argument("name", nargs="?", help="Peer name to set as default; omit to show current.")
    def_p.add_argument("--clear", action="store_true", help="Remove the default-peer setting.")
    def_p.add_argument("--home", default=None)
    pdesc_p = peers_sub.add_parser(
        "describe",
        help=(
            "Set / clear / show a controller-side description override for a "
            "trusted peer.  When set, this overrides whatever the peer "
            "broadcasts on connect."
        ),
    )
    pdesc_p.add_argument("name", help="Peer name from `opendesk peers list`")
    pdesc_p.add_argument("text", nargs="?", help="New override; omit to show current.")
    pdesc_p.add_argument("--clear", action="store_true", help="Remove the override.")
    pdesc_p.add_argument("--home", default=None)

    # --- Screen memory -------------------------------------------------

    mem_p = sub.add_parser(
        "memory",
        help=(
            "Screen memory: a local, searchable history of what was on screen. "
            "Captures on app/window change, reads accessibility text or OCR, redacts and encrypts, indexed on this machine only."
        ),
    )
    mem_p.add_argument("--home", default=None, help="opendesk home (default ~/.opendesk)")
    mem_sub = mem_p.add_subparsers(dest="memory_cmd")

    ms = mem_sub.add_parser("start", help="Run the capture daemon in the foreground (Ctrl-C to stop)")
    ms.add_argument("--interval", type=float, default=None, help="Seconds between captures (overrides config)")
    ms.add_argument("--log-file", default=None, help="Also write logs to this rotating file")
    ms.add_argument("--home", default=None)

    mst = mem_sub.add_parser("status", help="Daemon state, storage usage, config")
    mst.add_argument("--home", default=None)

    mp = mem_sub.add_parser("pause", help="Pause capture (optionally for a duration)")
    mp.add_argument("duration", nargs="?", default=None, help="e.g. 30m, 2h (omit = until resumed)")
    mp.add_argument("--home", default=None)

    mr = mem_sub.add_parser("resume", help="Resume capture")
    mr.add_argument("--home", default=None)

    mq = mem_sub.add_parser("search", help="Full-text search the history")
    mq.add_argument("query")
    mq.add_argument("--since", default=None, help="'2h', 'yesterday', 'tuesday', 'last week', ISO date")
    mq.add_argument("--until", default=None)
    mq.add_argument("--app", default=None, help="Filter by app name / window title substring")
    mq.add_argument("--limit", type=int, default=20)
    mq.add_argument("--home", default=None)

    mt = mem_sub.add_parser("timeline", help="List captured moments in a period")
    mt.add_argument("--since", default=None)
    mt.add_argument("--until", default=None)
    mt.add_argument("--app", default=None)
    mt.add_argument("--limit", type=int, default=50)
    mt.add_argument("--home", default=None)

    msh = mem_sub.add_parser("show", help="Print one moment's full text and thumbnail path")
    msh.add_argument("id", type=int)
    msh.add_argument("--save", default=None, metavar="FILE",
                     help="Write the (decrypted) JPEG thumbnail to FILE")
    msh.add_argument("--home", default=None)

    mex = mem_sub.add_parser(
        "export",
        help="Export moments (decrypted text + thumbnails) to JSON, CSV or a browsable HTML page",
    )
    mex.add_argument("--out", "-o", default=None, metavar="DIR",
                     help="New or empty folder to write to (default ~/Downloads/opendesk-memory-<time>)")
    mex.add_argument("--format", "-f", choices=["json", "csv", "html"], default="json")
    mex.add_argument("--since", default=None, help="'2h', 'yesterday', 'last week', ISO date (default: all)")
    mex.add_argument("--until", default=None)
    mex.add_argument("--app", default=None, help="Only this app name / window title substring")
    mex.add_argument("--query", "-q", default=None, help="Only moments matching this search")
    mex.add_argument("--limit", type=int, default=None, help="Max moments (default: all)")
    mex.add_argument("--no-thumbnails", action="store_true", dest="no_thumbnails",
                     help="Text only; skip the JPEG thumbnails")
    mex.add_argument("--home", default=None)

    md = mem_sub.add_parser("deny", help="Manage the per-app deny list")
    md.add_argument("--home", default=None)
    md_sub = md.add_subparsers(dest="deny_cmd")
    md_sub.add_parser("list", help="Show the deny list (default)").add_argument("--home", default=None)
    mda = md_sub.add_parser("add", help="Never capture apps/titles containing this")
    mda.add_argument("pattern")
    mda.add_argument("--home", default=None)
    mdr = md_sub.add_parser("remove", help="Remove an entry")
    mdr.add_argument("pattern")
    mdr.add_argument("--home", default=None)

    mc = mem_sub.add_parser(
        "config",
        help="Show / change trigger, intervals, storage cap, retention, hotkey, redaction, encryption",
    )
    mc.add_argument("--trigger", choices=["events", "interval"], default=None,
                    help="events = capture on app/window change (default); interval = fixed timer")
    mc.add_argument("--interval", type=float, default=None,
                    help="Seconds between captures (interval mode) / idle fallback (events mode)")
    mc.add_argument("--poll", type=float, default=None, help="Events mode: seconds between frontmost-window probes")
    mc.add_argument("--min-interval", type=float, default=None, dest="min_interval",
                    help="Events mode: minimum seconds between captures")
    mc.add_argument("--cap", type=int, default=None, help="Storage cap in MB (oldest frames deleted first)")
    mc.add_argument("--retention", type=int, default=None, help="Days to keep frames")
    mc.add_argument("--hotkey", default=None, help="Pause hotkey, pynput syntax, e.g. '<cmd>+<shift>+<alt>+p'; '' disables")
    mc.add_argument("--redact", choices=["on", "off"], default=None,
                    help="Scrub card numbers, API keys, tokens, passwords before storing text")
    mc.add_argument("--encrypt-text", choices=["on", "off"], default=None, dest="encrypt_text",
                    help="Encrypt stored text (exact-word search only); run `reindex` to convert old frames")
    mc.add_argument("--encrypt-thumbnails", choices=["on", "off"], default=None, dest="encrypt_thumbnails",
                    help="Encrypt stored thumbnails (default on)")
    mc.add_argument("--home", default=None)

    mri = mem_sub.add_parser(
        "reindex",
        help="Rewrite existing frames under the current settings (encrypt/decrypt text & thumbnails, redact)",
    )
    mri.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    mri.add_argument("--home", default=None)

    mcl = mem_sub.add_parser("clear", help="Delete stored frames (all, or --before / --app)")
    mcl.add_argument("--before", default=None, help="Only frames before this time phrase, e.g. '7d', '2026-08-01'")
    mcl.add_argument("--app", default=None, help="Only frames from this app / title substring")
    mcl.add_argument("--yes", "-y", action="store_true", help="Skip confirmation")
    mcl.add_argument("--home", default=None)

    mis = mem_sub.add_parser("install-service", help="Run the daemon at login (launchd / systemd / Task Scheduler)")
    mis.add_argument("--interval", type=float, default=None)
    mis.add_argument("--no-start", action="store_true")
    mis.add_argument("--home", default=None)

    mus = mem_sub.add_parser("uninstall-service", help="Remove the login service")
    mus.add_argument("--home", default=None)

    from opendesk.eval.cli import add_eval_parser, cmd_eval
    add_eval_parser(sub)
    fleet_p = sub.add_parser("fleet", help="Run one tool call across several paired peers")
    fleet_sub = fleet_p.add_subparsers(dest="fleet_cmd")
    fr = fleet_sub.add_parser("run", help="Run a tool on peers in parallel")
    fr.add_argument("--peers", required=True, help="Comma-separated peer names, or 'all'")
    fr.add_argument("--tool", required=True, help="Tool to run, e.g. script, screenshot, app")
    fr.add_argument("--params", default="{}", help="Tool arguments as a JSON object")
    fr.add_argument("--match", default=None, help="Only peers whose description contains these words")
    fr.add_argument("--concurrency", type=int, default=4)
    fr.add_argument("--timeout", type=float, default=120.0, help="Seconds per peer")
    fr.add_argument("--save-images", default=None, help="Directory to write image results to")
    fr.add_argument("--home", default=None)
    # --- Safety: stop / resume / takeover / handback / secrets / policy --
    from opendesk.safety import cli as safety_cli
    safety_cli.register(sub)

    from opendesk.integrations.local import register_cli, cmd_agent
    register_cli(sub)

    args = parser.parse_args()

    if safety_cli.dispatch(args):
        return

    if args.command == "agent":
        cmd_agent(args)
    elif args.command == "install":
        cmd_install(scope=args.scope)
    elif args.command == "uninstall":
        cmd_uninstall()
    elif args.command == "scheduler":
        cmd_scheduler(args)
    elif args.command == "memory":
        cmd_memory(args)
    elif args.command == "eval":
        cmd_eval(args)
    elif args.command == "fleet":
        cmd_fleet(args)
    elif args.command == "pair":
        cmd_pair(args)
    elif args.command == "pair-with":
        cmd_pair_with(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "discover":
        cmd_discover(args)
    elif args.command == "connect":
        cmd_connect(args)
    elif args.command == "peers":
        cmd_peers(args)
    elif args.command == "sessions":
        cmd_sessions(args)
    elif args.command == "disconnect":
        cmd_disconnect(args)
    elif args.command == "unpair":
        cmd_unpair(args)
    elif args.command == "audit":
        cmd_audit(args)
    elif args.command == "check":
        cmd_check(args)
    elif args.command == "describe":
        cmd_describe(args)
    elif args.command == "app":
        cmd_app(args)
    elif args.command == "wsl-setup":
        cmd_wsl_setup(args)
    elif args.command == "install-service":
        cmd_install_service(args)
    elif args.command == "uninstall-service":
        cmd_uninstall_service(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
