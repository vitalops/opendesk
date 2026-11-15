import AppKit
import CoreGraphics
import ApplicationServices

/// Non-destructive mouse-move test that runs **inside the OpenDesk GUI
/// process** — the same signed binary the user grants Accessibility to.
/// We also probe `AXIsProcessTrusted()` so we can tell apart:
///   * macOS hasn't authorised this process at all (TCC=false)
///   * macOS thinks we're authorised but the event still got dropped
///     (rare — usually screen lock / mirroring / Screen Time)
@MainActor
enum NativeDesktopProbe {

    struct Result {
        let ok: Bool
        let trusted: Bool
        let before: CGPoint
        let after: CGPoint
        let target: CGPoint
        let bundlePath: String
        let bundleId: String
    }

    static func runMouseTest() async -> Result {
        let trusted = AXIsProcessTrusted()
        let target = CGPoint(x: 600, y: 400)
        let before = currentMouseLocation()

        if let evt = CGEvent(mouseEventSource: nil,
                             mouseType: .mouseMoved,
                             mouseCursorPosition: target,
                             mouseButton: .left) {
            evt.post(tap: .cghidEventTap)
        }
        try? await Task.sleep(nanoseconds: 250_000_000)

        let after = currentMouseLocation()
        let moved = abs(after.x - target.x) <= 10 && abs(after.y - target.y) <= 10

        return Result(
            ok: moved,
            trusted: trusted,
            before: before,
            after: after,
            target: target,
            bundlePath: Bundle.main.bundlePath,
            bundleId: Bundle.main.bundleIdentifier ?? "<unknown>"
        )
    }

    /// Quit OpenDesk and spawn a detached helper that relaunches it
    /// once the old process is fully gone. Returns nil on success
    /// (process will terminate momentarily) or an error string if the
    /// helper failed to spawn.
    @discardableResult
    static func quitAndRelaunch() -> String? {
        let path = Bundle.main.bundlePath
        let escaped = path.replacingOccurrences(of: "'", with: "'\\''")
        let exe = "\(path)/Contents/MacOS/OpenDesk"
        let exeEscaped = exe.replacingOccurrences(of: "'", with: "'\\''")

        // Outer shell spawns inner `nohup sh -c '...' & disown`, so the
        // inner shell is fully detached from us — no SIGHUP on parent death.
        let inner =
            "trap '' HUP INT TERM; " +
            "i=0; while [ $i -lt 50 ]; do " +
              "pgrep -fl '\(exeEscaped)' >/dev/null 2>&1 || break; " +
              "sleep 0.1; i=$((i+1)); " +
            "done; " +
            "sleep 0.3; " +
            "/usr/bin/open '\(escaped)'"

        // nohup makes the inner shell ignore SIGHUP; `& disown` detaches
        // it from the outer shell's job table so it survives that shell
        // exiting too. </dev/null + >/dev/null + 2>&1 prevent SIGPIPE.
        let outer = "nohup /bin/sh -c \"\(inner)\" </dev/null >/dev/null 2>&1 & disown"

        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/sh")
        task.arguments = ["-c", outer]
        task.standardInput  = FileHandle.nullDevice
        task.standardOutput = FileHandle.nullDevice
        task.standardError  = FileHandle.nullDevice

        do {
            try task.run()
        } catch {
            let msg = "Relaunch helper failed to spawn: \(error.localizedDescription)"
            NSLog("OpenDesk: \(msg)")
            return msg
        }

        // The outer shell should exit quickly — fire termination when it does
        // so we don't race a still-spawning helper.
        task.terminationHandler = { p in
            DispatchQueue.main.async {
                if p.terminationStatus == 0 {
                    NSApp.terminate(nil)
                } else {
                    NSLog("OpenDesk: relaunch outer shell exited \(p.terminationStatus); not terminating.")
                }
            }
        }
        return nil
    }

    /// Wipe macOS TCC entries for OpenDesk (Accessibility + Screen
    /// Recording). Needed because ad-hoc-signed builds get a fresh cdhash
    /// every ./build.sh, and TCC silently denies a (path, cdhash)
    /// mismatch even when the toggle in System Settings looks ON.
    /// Returns a status string for the UI.
    static func resetTCCEntries() -> String {
        let bundleId = Bundle.main.bundleIdentifier ?? "ai.opendesk.macos"
        var results: [String] = []
        for category in ["Accessibility", "ScreenCapture"] {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/usr/bin/tccutil")
            p.arguments = ["reset", category, bundleId]
            let out = Pipe(); let err = Pipe()
            p.standardOutput = out; p.standardError = err
            do {
                try p.run(); p.waitUntilExit()
                if p.terminationStatus == 0 {
                    results.append("\(category): cleared")
                } else {
                    let stderrText = String(data: err.fileHandleForReading.availableData,
                                            encoding: .utf8) ?? ""
                    results.append("\(category): exit \(p.terminationStatus) \(stderrText)")
                }
            } catch {
                results.append("\(category): \(error.localizedDescription)")
            }
        }
        return results.joined(separator: "\n")
    }

    private static func currentMouseLocation() -> CGPoint {
        let cocoa = NSEvent.mouseLocation
        let h = NSScreen.main?.frame.height ?? 0
        return CGPoint(x: cocoa.x, y: h - cocoa.y)
    }
}
