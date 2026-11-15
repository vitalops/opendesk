import Foundation
import Darwin   // kill, SIGTERM, SIGKILL, pid_t

/// A `Process` wrapper that:
///   1. Spawns the child **directly** (no `setsid` wrapper) so macOS TCC
///      attribution flows naturally from OpenDesk.app → claude → opendesk-mcp.
///      That's how the spawned tools inherit our Accessibility / Screen
///      Recording grants — and why every chat doesn't re-prompt for them.
///   2. Exposes `cancel()`, which walks the process tree with `pgrep -P`
///      and SIGTERM-then-SIGKILLs every descendant (children first, then
///      the root). Multiple syscalls instead of one `killpg`, but TCC
///      stays bound; the trade is worth it.
///   3. Resumes its awaiting continuation exactly once, regardless of the
///      ordering between `terminationHandler` and `cancel()`.
///
/// History note: an earlier version wrapped the spawn in
/// `perl -e 'use POSIX; setsid; exec @ARGV'` so `killpg` could take the
/// whole session down in one call. That broke macOS TCC — every spawn
/// became its own session leader, so the OS treated it as a brand-new
/// responsible process and (a) re-prompted for Accessibility every chat,
/// (b) silently no-op'd pyautogui's mouse/keyboard calls. Don't put
/// `setsid` back without solving that.
final class CancellableProcess: @unchecked Sendable {

    enum Outcome {
        case exited(Int32)          // normal exit, terminationStatus
        case cancelled              // user hit Stop
        case spawnFailed(Error)     // process.run() threw
    }

    let process = Process()
    let stdout = Pipe()
    let stderr = Pipe()
    let stdin  = Pipe()

    private let lock = NSLock()
    private var didFinish = false
    private var cancelled = false
    private var continuation: CheckedContinuation<Outcome, Never>?
    private var pid: pid_t = 0

    /// Run a child, attach pipes, and wait for `Outcome`. Configure the
    /// `stdout` readability handler before calling this if you want
    /// streaming output. Pass `stdinPayload` to write-then-close stdin
    /// before the child starts reading (used by the short-lived bridge).
    func run(executable: URL,
             arguments: [String],
             environment: [String: String]? = nil,
             stdinPayload: Data? = nil) async -> Outcome {

        process.executableURL = executable
        process.arguments = arguments
        if let environment { process.environment = environment }
        process.standardInput  = stdin
        process.standardOutput = stdout
        process.standardError  = stderr

        process.terminationHandler = { [weak self] p in
            self?.finish(.exited(p.terminationStatus))
        }

        return await withCheckedContinuation { (cont: CheckedContinuation<Outcome, Never>) in
            lock.lock()
            self.continuation = cont
            lock.unlock()
            do {
                try process.run()
                lock.lock()
                self.pid = process.processIdentifier
                let wasCancelled = self.cancelled
                lock.unlock()
                if let stdinPayload {
                    try? stdin.fileHandleForWriting.write(contentsOf: stdinPayload)
                    try? stdin.fileHandleForWriting.close()
                }
                if wasCancelled { killTreeAsync() }
            } catch {
                finish(.spawnFailed(error))
            }
        }
    }

    /// Idempotent. Safe to call from the main actor or any queue.
    func cancel() {
        lock.lock()
        if cancelled || didFinish { lock.unlock(); return }
        cancelled = true
        let havePid = pid > 0
        lock.unlock()
        if havePid { killTreeAsync() }
        finish(.cancelled)
    }

    /// SIGTERM the root and every descendant (children first so the parent
    /// can't immediately respawn them); after 800 ms, SIGKILL stragglers.
    /// Runs off the main actor — pgrep calls are cheap but synchronous.
    private func killTreeAsync() {
        let root = pid
        guard root > 0 else { return }
        DispatchQueue.global(qos: .userInitiated).async {
            let tree = Self.descendants(of: root, including: true)
            for p in tree.reversed() { _ = kill(p, SIGTERM) }
        }
        DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + 0.8) {
            let tree = Self.descendants(of: root, including: true)
            for p in tree.reversed() where Self.isAlive(p) {
                _ = kill(p, SIGKILL)
            }
        }
    }

    /// Recursively collect `root` and every descendant via `pgrep -P`.
    private static func descendants(of root: pid_t, including: Bool) -> [pid_t] {
        var result: [pid_t] = including ? [root] : []
        var frontier: [pid_t] = [root]
        while !frontier.isEmpty {
            var next: [pid_t] = []
            for p in frontier {
                next.append(contentsOf: childPIDs(of: p))
            }
            result.append(contentsOf: next)
            frontier = next
        }
        return result
    }

    private static func childPIDs(of parent: pid_t) -> [pid_t] {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/pgrep")
        proc.arguments = ["-P", "\(parent)"]
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
        } catch { return [] }
    }

    private static func isAlive(_ pid: pid_t) -> Bool {
        // kill(pid, 0) returns 0 if the process exists; ESRCH if not.
        kill(pid, 0) == 0
    }

    private func finish(_ outcome: Outcome) {
        lock.lock()
        if didFinish { lock.unlock(); return }
        didFinish = true
        let cont = continuation
        continuation = nil
        lock.unlock()

        stdout.fileHandleForReading.readabilityHandler = nil
        stderr.fileHandleForReading.readabilityHandler = nil
        cont?.resume(returning: outcome)
    }
}
