import Foundation
import AppKit

enum NativeApp {

    static func handle(args: [String: Any]) throws -> [[String: Any]] {
        let action = args.str("action") ?? "list"
        let ws = NSWorkspace.shared

        switch action {
        case "list":
            let names = ws.runningApplications
                .filter { $0.activationPolicy == .regular }
                .compactMap { $0.localizedName }
                .sorted()
            let body = "Running applications (\(names.count)):\n" +
                       names.map { "  • \($0)" }.joined(separator: "\n")
            return reply(body)

        case "open":
            let name = try requireName(args)
            try openApp(named: name, ws: ws)
            // Some apps relaunch silently with no window when last-session-empty.
            // Wait briefly then issue ⌘N so a new window appears for editors
            // like TextEdit / Notes / Chrome / Safari etc.
            Thread.sleep(forTimeInterval: 0.6)
            if let app = runningApp(named: name, ws: ws) {
                app.activate(options: [.activateIgnoringOtherApps])
                Thread.sleep(forTimeInterval: 0.2)
                NativeKeyboard.tapNewWindowIfNoneVisible(app: app)
            }
            return reply("Opened '\(name)'.")

        case "focus":
            let name = try requireName(args)
            guard let app = runningApp(named: name, ws: ws) else {
                throw NativeTools.ToolError("\(name) is not running.")
            }
            app.activate(options: [.activateIgnoringOtherApps])
            return reply("Focused '\(name)'.")

        case "close":
            let name = try requireName(args)
            guard let app = runningApp(named: name, ws: ws) else {
                throw NativeTools.ToolError("\(name) is not running.")
            }
            app.terminate()
            return reply("Sent quit to '\(name)'.")

        default:
            throw NativeTools.ToolError("Unknown app action: \(action)")
        }
    }

    // MARK: Helpers

    private static func requireName(_ args: [String: Any]) throws -> String {
        guard let name = args.str("name"), !name.isEmpty else {
            throw NativeTools.ToolError("name is required")
        }
        return name
    }

    private static func openApp(named name: String, ws: NSWorkspace) throws {
        if let url = locateApp(named: name, ws: ws) {
            let cfg = NSWorkspace.OpenConfiguration()
            cfg.activates = true
            cfg.addsToRecentItems = false
            let sem = DispatchSemaphore(value: 0)
            var err: Error?
            ws.openApplication(at: url, configuration: cfg) { _, e in
                err = e
                sem.signal()
            }
            _ = sem.wait(timeout: .now() + 8)
            if let err { throw NativeTools.ToolError(err.localizedDescription) }
        } else {
            throw NativeTools.ToolError("Could not find an app named '\(name)'.")
        }
    }

    private static func locateApp(named name: String, ws: NSWorkspace) -> URL? {
        // 1) Already-running app
        if let app = runningApp(named: name, ws: ws), let url = app.bundleURL {
            return url
        }
        // 2) URL lookup via LaunchServices
        if let url = ws.urlForApplication(withBundleIdentifier: name) { return url }
        // 3) /Applications scan (case-insensitive)
        let candidates = [
            "/Applications/\(name).app",
            "/System/Applications/\(name).app",
            "/Applications/Utilities/\(name).app",
            "/Applications/\(name)",
        ]
        for c in candidates where FileManager.default.fileExists(atPath: c) {
            return URL(fileURLWithPath: c)
        }
        // 4) Fuzzy /Applications search
        if let entries = try? FileManager.default.contentsOfDirectory(atPath: "/Applications") {
            for e in entries where e.lowercased().contains(name.lowercased()) {
                return URL(fileURLWithPath: "/Applications/\(e)")
            }
        }
        return nil
    }

    private static func runningApp(named name: String, ws: NSWorkspace) -> NSRunningApplication? {
        let target = name.lowercased()
        for app in ws.runningApplications {
            if let n = app.localizedName?.lowercased(), n == target || n.contains(target) {
                return app
            }
        }
        return nil
    }

    private static func reply(_ s: String) -> [[String: Any]] {
        [["type": "text", "text": s]]
    }
}

// MARK: Helper for "open then ensure a window"

extension NativeKeyboard {
    /// If the app is foreground but has no visible windows, send ⌘N so
    /// the next screenshot actually has something to click. Editors like
    /// TextEdit silently launch with no window on macOS when last-session
    /// was empty — this is the canonical workaround.
    static func tapNewWindowIfNoneVisible(app: NSRunningApplication) {
        let pid = app.processIdentifier
        guard pid > 0 else { return }
        // Cheap heuristic: ask AppKit for windows belonging to the app.
        let cgWindows = (CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements],
                                                    kCGNullWindowID) as? [[String: Any]]) ?? []
        let mine = cgWindows.filter { ($0[kCGWindowOwnerPID as String] as? Int) == Int(pid) }
        let hasContentWindow = mine.contains {
            let layer = $0[kCGWindowLayer as String] as? Int ?? 999
            let alpha = $0[kCGWindowAlpha as String] as? Double ?? 0
            return layer == 0 && alpha > 0.1
        }
        if !hasContentWindow {
            // Send ⌘N
            if let n = keycodeFor("n") {
                tapKey(virtualKey: n, flags: .maskCommand)
            }
        }
    }

    private static func keycodeFor(_ s: String) -> CGKeyCode? {
        switch s.lowercased() {
        case "n": return 0x2D
        default: return nil
        }
    }

    private static func tapKey(virtualKey: CGKeyCode, flags: CGEventFlags) {
        if let d = CGEvent(keyboardEventSource: nil, virtualKey: virtualKey, keyDown: true) {
            d.flags = flags; d.post(tap: .cghidEventTap)
        }
        if let u = CGEvent(keyboardEventSource: nil, virtualKey: virtualKey, keyDown: false) {
            u.flags = flags; u.post(tap: .cghidEventTap)
        }
    }
}
