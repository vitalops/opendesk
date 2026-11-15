import Foundation
import Darwin

/// Belt-and-suspenders cleanup that scans for *any* opendesk-related
/// processes on the system and signals them.
///
/// Normal cancellation is done by `CancellableProcess.cancel()` — that
/// catches the in-flight subprocesses the app spawned this session.
/// This module exists for the leftover case: an earlier OpenDesk session
/// crashed or was force-quit and orphaned `opendesk-mcp` / `opendesk_bridge`
/// children are still on the system holding desktop control.
enum EmergencyStop {

    /// Pattern fragments matched against the full command line via `pkill -f`.
    /// Add to this list when we spawn new long-lived helpers.
    static let opendeskPatterns: [String] = [
        "opendesk-mcp",
        "opendesk_bridge.py",
        "opendesk.integrations.mcp",
    ]

    /// SIGTERM → 600 ms → SIGKILL anything still alive. Returns the PIDs
    /// that were known to be alive at start.
    @discardableResult
    static func killAllOpenDeskOrphans() -> [pid_t] {
        let pids = matchingPIDs(patterns: opendeskPatterns)
        guard !pids.isEmpty else { return [] }
        for pid in pids { _ = kill(pid, SIGTERM) }
        Thread.sleep(forTimeInterval: 0.6)
        for pid in pids where isAlive(pid) { _ = kill(pid, SIGKILL) }
        return pids
    }

    /// Find all PIDs whose full command line contains any of the patterns.
    static func matchingPIDs(patterns: [String]) -> [pid_t] {
        var found = Set<pid_t>()
        for pat in patterns {
            for pid in pgrepF(pattern: pat) { found.insert(pid) }
        }
        return Array(found).sorted()
    }

    private static func pgrepF(pattern: String) -> [pid_t] {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        proc.arguments = ["-f", pattern]
        let out = Pipe()
        proc.standardOutput = out
        proc.standardError = Pipe()
        do {
            try proc.run()
            proc.waitUntilExit()
            let data = (try? out.fileHandleForReading.readToEnd()) ?? Data()
            let s = String(data: data, encoding: .utf8) ?? ""
            return s.split(separator: "\n")
                .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
                .filter { $0 != getpid() }   // don't kill ourselves
        } catch {
            return []
        }
    }

    private static func isAlive(_ pid: pid_t) -> Bool {
        kill(pid, 0) == 0
    }
}

/// One-shot trigger that ensures a block runs at most once even if
/// several threads race to call it. Still used by the legacy code path
/// in `liveAuthProbe` and a few other places.
final class FireOnce: @unchecked Sendable {
    private let lock = NSLock()
    private var fired = false
    func run(_ block: () -> Void) {
        lock.lock()
        let go = !fired
        fired = true
        lock.unlock()
        if go { block() }
    }
    var didFire: Bool {
        lock.lock(); defer { lock.unlock() }
        return fired
    }
}
