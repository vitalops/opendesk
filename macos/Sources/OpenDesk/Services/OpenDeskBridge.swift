import Foundation
import SwiftUI
import AppKit

/// Thin Swift wrapper around the Python opendesk bridge.
@MainActor
final class OpenDeskBridge: ObservableObject {

    static let shared = OpenDeskBridge()

    @Published var lastError: String?
    @Published var auditTrail: [AuditEntry] = []
    @Published var inflightCount: Int = 0

    /// In-flight bridge subprocesses, keyed by UUID so cancel() can target one
    /// or all. Each is wrapped in a CancellableProcess so killpg takes down
    /// the python child plus any of its grandchildren.
    private var inflight: [UUID: CancellableProcess] = [:]

    struct AuditEntry: Identifiable, Hashable {
        let id = UUID()
        let timestamp: Date
        let tool: String
        let params: String
        let ok: Bool
        let note: String
    }

    struct BridgeResponse {
        let raw: [String: Any]
        let imageB64: String?
        var ok: Bool { (raw["ok"] as? Bool) ?? false }
        var error: String? { raw["error"] as? String }
        var result: Any? { raw["result"] }
    }

    enum BridgeError: LocalizedError {
        case pythonMissing
        case bridgeMissing
        case decodeFailed
        case toolFailed(String)
        var errorDescription: String? {
            switch self {
            case .pythonMissing:    "No suitable Python 3.10+ found. Set the path in Settings."
            case .bridgeMissing:    "Bundled opendesk_bridge.py not found inside the app."
            case .decodeFailed:     "Could not decode the bridge response."
            case .toolFailed(let m): m
            }
        }
    }

    // MARK: Public API

    /// Run any opendesk tool by name with a free-form parameter dict.
    @discardableResult
    func run(_ tool: String, params: [String: Any] = [:]) async throws -> BridgeResponse {
        let request: [String: Any] = ["tool": tool, "params": params]
        let data = try JSONSerialization.data(withJSONObject: request)
        let raw = try await invoke(stdin: data)

        guard let dict = try JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            throw BridgeError.decodeFailed
        }
        let resp = BridgeResponse(raw: dict, imageB64: dict["image_b64"] as? String)
        await record(tool: tool, params: params, ok: resp.ok, note: resp.error ?? "")
        if !resp.ok {
            let msg = resp.error ?? "tool failed"
            throw BridgeError.toolFailed(msg)
        }
        return resp
    }

    /// Convenience: take a screenshot and return an NSImage + raw base64.
    func screenshot(marks: Bool = true) async throws -> (NSImage?, String?) {
        let resp = try await run("screenshot", params: ["marks": marks])
        guard let b64 = resp.imageB64,
              let data = Data(base64Encoded: b64) else { return (nil, resp.imageB64) }
        return (NSImage(data: data), resp.imageB64)
    }

    // MARK: Internals

    private func record(tool: String, params: [String: Any], ok: Bool, note: String) async {
        let p = (try? JSONSerialization.data(withJSONObject: params, options: [.sortedKeys]))
            .flatMap { String(data: $0, encoding: .utf8) } ?? "{}"
        let entry = AuditEntry(timestamp: Date(), tool: tool, params: p, ok: ok, note: note)
        auditTrail.insert(entry, at: 0)
        if auditTrail.count > 200 { auditTrail.removeLast() }
    }

    private func invoke(stdin payload: Data) async throws -> Data {
        let rt = resolvedRuntime()
        let bridgePath = try resolveBridgePath()
        let py = rt.executable

        var env = ProcessInfo.processInfo.environment
        // Carry whichever extra env vars the resolver picked (e.g. PYTHONPATH).
        for (k, v) in rt.extraEnv { env[k] = v }
        // Legacy helper: if a source path is configured, also expose it for the
        // bridge's `_ensure_path()` helper. Harmless if Python has opendesk installed.
        if let pp = rt.extraEnv["PYTHONPATH"] { env["OPENDESK_SOURCE"] = pp }

        let cp = CancellableProcess()
        let token = UUID()
        inflight[token] = cp
        inflightCount = inflight.count
        defer {
            inflight.removeValue(forKey: token)
            inflightCount = inflight.count
        }

        let outcome = await cp.run(
            executable: URL(fileURLWithPath: py),
            arguments: [bridgePath],
            environment: env,
            stdinPayload: payload
        )

        switch outcome {
        case .exited(let code):
            let outData = (try? cp.stdout.fileHandleForReading.readToEnd()) ?? Data()
            let errData = (try? cp.stderr.fileHandleForReading.readToEnd()) ?? Data()
            if code == 0 {
                return outData.isEmpty ? errData : outData
            }
            let msg = String(data: errData, encoding: .utf8) ?? "exit \(code)"
            throw BridgeError.toolFailed(msg)
        case .cancelled:
            throw BridgeError.toolFailed("Cancelled by user.")
        case .spawnFailed(let e):
            throw e
        }
    }

    // MARK: Cancel

    /// Kill every in-flight bridge subprocess and its descendants.
    func cancelAll() {
        for (_, cp) in inflight { cp.cancel() }
    }

    // MARK: Diagnostic — does Python actually have Accessibility?

    struct ControlTestResult {
        let ok: Bool
        let message: String
        let detail: String
    }

    /// Test whether opendesk-mcp can actually drive the mouse. Reads current
    /// position → moves to (600, 400) → reads position again. If the second
    /// read is still the original position, macOS TCC silently dropped our
    /// CGEventPost — i.e. the Python binary running opendesk-mcp isn't in
    /// Accessibility.
    func testDesktopControl() async -> ControlTestResult {
        do {
            let before = try await run("mouse", params: ["action": "cursor_position"])
            let (bx, by) = extractXY(before.result)
            let targetX = 600, targetY = 400
            _ = try await run("mouse", params: ["action": "move",
                                                "x": targetX,
                                                "y": targetY])
            try await Task.sleep(nanoseconds: 250_000_000)
            let after = try await run("mouse", params: ["action": "cursor_position"])
            let (ax, ay) = extractXY(after.result)

            let moved = abs(ax - targetX) <= 8 && abs(ay - targetY) <= 8
            if moved {
                return ControlTestResult(
                    ok: true,
                    message: "Desktop control works.",
                    detail: "Mouse moved from (\(bx), \(by)) → (\(ax), \(ay)). Target was (\(targetX), \(targetY))."
                )
            } else {
                return ControlTestResult(
                    ok: false,
                    message: "Mouse events are being silently dropped.",
                    detail: "Before: (\(bx), \(by))   After: (\(ax), \(ay))   Target: (\(targetX), \(targetY))\n\n" +
                            "macOS dropped the CGEventPost — the Python binary running opendesk-mcp doesn't have Accessibility permission. " +
                            "Reveal the binary in Finder above, drag it into System Settings → Privacy & Security → Accessibility, toggle it on, then test again."
                )
            }
        } catch {
            return ControlTestResult(
                ok: false,
                message: "Diagnostic failed to run.",
                detail: error.localizedDescription
            )
        }
    }

    /// Pulls (x, y) out of whatever shape `cursor_position` returns. The opendesk
    /// `mouse` tool currently returns a `ToolResult` whose `output` is a text
    /// string like `"Current cursor: (716, 429)"`; we also handle a structured
    /// `{x, y}` dict in case the tool format changes.
    private func extractXY(_ result: Any?) -> (Int, Int) {
        if let d = result as? [String: Any] {
            if let x = d["x"] as? Int, let y = d["y"] as? Int { return (x, y) }
            if let x = d["x"] as? Double, let y = d["y"] as? Double { return (Int(x), Int(y)) }
            if let text = d["output"] as? String, let xy = parseCursorText(text) { return xy }
            if let nested = d["metadata"] as? [String: Any] {
                if let x = nested["x"] as? Int, let y = nested["y"] as? Int { return (x, y) }
            }
        }
        if let s = result as? String, let xy = parseCursorText(s) { return xy }
        return (0, 0)
    }

    /// Parse "Current cursor: (X, Y)" → (X, Y).
    private func parseCursorText(_ s: String) -> (Int, Int)? {
        let pattern = #"\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)"#
        guard let re = try? NSRegularExpression(pattern: pattern),
              let m = re.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)),
              m.numberOfRanges >= 3,
              let xr = Range(m.range(at: 1), in: s),
              let yr = Range(m.range(at: 2), in: s),
              let x = Int(s[xr]),
              let y = Int(s[yr]) else { return nil }
        return (x, y)
    }

    // MARK: Path resolution
    //
    // Several mambaforge envs may exist; only the one(s) that actually have
    // the opendesk package installed are usable. We probe each candidate
    // with `python -c "import opendesk"` and cache the first winner. If
    // none have opendesk installed, fall back to setting PYTHONPATH to
    // the repo source for a Python that at least has the runtime deps.

    /// (python executable, environment) tuple — environment may carry
    /// PYTHONPATH when we're running off the source tree.
    private struct PythonRuntime {
        let executable: String
        let extraEnv: [String: String]
        let displayLabel: String
    }

    private var cachedRuntime: PythonRuntime?

    /// Force a fresh probe — used by the "Re-detect" button in Settings.
    func resetResolvedRuntime() { cachedRuntime = nil }

    /// The Python the bridge will spawn, for display in Settings.
    func resolvedPythonDisplay() -> String {
        let rt = resolvedRuntime()
        if let pp = rt.extraEnv["PYTHONPATH"] {
            return "PYTHONPATH=\(pp) \(rt.executable)"
        }
        return rt.executable
    }

    /// Just the executable path — what the user should add to Accessibility.
    func resolvedPythonExecutable() -> String {
        resolvedRuntime().executable
    }

    /// Symlink-resolved real path. macOS Accessibility follows symlinks but
    /// users sometimes get confused, so we show both when they differ.
    func resolvedPythonCanonical() -> String {
        let p = resolvedPythonExecutable()
        return URL(fileURLWithPath: p).resolvingSymlinksInPath().path
    }

    private func resolvedRuntime() -> PythonRuntime {
        if let cached = cachedRuntime { return cached }
        let rt = computeRuntime()
        cachedRuntime = rt
        return rt
    }

    private func resolvePythonExecutable() -> String {
        resolvedRuntime().executable
    }

    private func computeRuntime() -> PythonRuntime {
        let customPython = UserDefaults.standard.string(forKey: "pythonPath")?
            .trimmingCharacters(in: .whitespaces) ?? ""
        let customSource = UserDefaults.standard.string(forKey: "opendeskSource")?
            .trimmingCharacters(in: .whitespaces) ?? ""

        // 1) Honour an explicit user pythonPath if it works.
        if !customPython.isEmpty, FileManager.default.isExecutableFile(atPath: customPython) {
            if canImportOpenDesk(python: customPython, env: [:]) {
                return .init(executable: customPython, extraEnv: [:], displayLabel: "user-configured")
            }
            if !customSource.isEmpty,
               canImportOpenDesk(python: customPython, env: ["PYTHONPATH": customSource]) {
                return .init(executable: customPython,
                             extraEnv: ["PYTHONPATH": customSource],
                             displayLabel: "user-configured + source")
            }
        }

        let pythons = discoverCandidatePythons()
        let sources = discoverSourcePaths(custom: customSource)

        // 2) Any candidate that has opendesk installed natively wins.
        for p in pythons where canImportOpenDesk(python: p, env: [:]) {
            return .init(executable: p, extraEnv: [:], displayLabel: label(for: p))
        }

        // 3) Otherwise pair any candidate with the repo source.
        for p in pythons {
            for src in sources {
                let env = ["PYTHONPATH": src]
                if canImportOpenDesk(python: p, env: env) {
                    return .init(executable: p,
                                 extraEnv: env,
                                 displayLabel: "\(label(for: p)) + source")
                }
            }
        }

        // 4) Last-resort: first existing Python, no env. The bridge will
        //    error informatively when invoked.
        return .init(executable: pythons.first ?? "/usr/bin/python3",
                     extraEnv: [:],
                     displayLabel: "fallback")
    }

    private func discoverCandidatePythons() -> [String] {
        var result: [String] = []
        let envsDir = "/Users/\(NSUserName())/mambaforge/envs"
        if let envs = try? FileManager.default.contentsOfDirectory(atPath: envsDir) {
            for envName in envs {
                let p = "\(envsDir)/\(envName)/bin/python"
                if FileManager.default.isExecutableFile(atPath: p) {
                    result.append(p)
                }
            }
        }
        let extras = [
            "/Users/\(NSUserName())/mambaforge/bin/python3",
            "/opt/homebrew/bin/python3",
            "/usr/local/bin/python3",
            "/usr/bin/python3",
        ]
        for p in extras where FileManager.default.isExecutableFile(atPath: p) && !result.contains(p) {
            result.append(p)
        }
        return result
    }

    private func discoverSourcePaths(custom: String) -> [String] {
        var paths: [String] = []
        if !custom.isEmpty { paths.append(custom) }
        let guess = "/Users/\(NSUserName())/Documents/GitHub/opendesk/python"
        if !paths.contains(guess) { paths.append(guess) }
        return paths.filter {
            FileManager.default.fileExists(atPath: "\($0)/opendesk/__init__.py")
        }
    }

    private func canImportOpenDesk(python: String, env: [String: String]) -> Bool {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: python)
        proc.arguments = ["-c", "import opendesk"]
        var fullEnv = ProcessInfo.processInfo.environment
        for (k, v) in env { fullEnv[k] = v }
        proc.environment = fullEnv
        proc.standardOutput = Pipe()
        proc.standardError = Pipe()
        do {
            try proc.run()
            proc.waitUntilExit()
            return proc.terminationStatus == 0
        } catch {
            return false
        }
    }

    private func label(for python: String) -> String {
        if let env = python.split(separator: "/").drop(while: { $0 != "envs" }).dropFirst().first {
            return "\(env) env"
        }
        return python
    }

    private func resolveBridgePath() throws -> String {
        if let bundleURL = Bundle.module.url(forResource: "opendesk_bridge",
                                             withExtension: "py",
                                             subdirectory: "bridge") {
            return bundleURL.path
        }
        if let bundleURL = Bundle.main.url(forResource: "opendesk_bridge",
                                           withExtension: "py") {
            return bundleURL.path
        }
        // Dev fallback: look next to the executable.
        let exec = Bundle.main.executableURL?.deletingLastPathComponent()
        if let dir = exec {
            let p = dir.appendingPathComponent("bridge/opendesk_bridge.py").path
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        throw BridgeError.bridgeMissing
    }

}
