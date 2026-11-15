import Foundation
import SwiftUI
import AppKit

/// Drives the `claude` CLI as a subscription-backed engine for OpenDesk.
/// Claude Code handles auth (your Pro/Max plan) and MCP, so the user
/// never has to paste an API key into this app.
@MainActor
final class ClaudeCodeService: ObservableObject {

    // MARK: Published state

    @Published var claudePath: String?
    @Published var claudeVersion: String?
    @Published var isInstalled: Bool = false
    @Published var isAuthenticated: Bool = false
    @Published var lastCheckedAt: Date?
    @Published var isCheckingAuth: Bool = false
    @Published var isRunning: Bool = false
    @Published var lastError: String?

    /// In-flight chat process so the Stop button can reach it.
    private var active: CancellableProcess?

    // MARK: Events surfaced to the chat view

    enum Event {
        case text(String)
        case toolUse(name: String, input: [String: Any])
        case toolResult(text: String, imageB64: String?)
        case error(String)
        case done(summary: String?)
    }

    // MARK: Detection

    func refresh() async {
        claudePath = findClaude()
        isInstalled = claudePath != nil
        if let path = claudePath {
            claudeVersion = runSync(path, ["--version"])?
                .trimmingCharacters(in: .whitespacesAndNewlines)
        } else {
            claudeVersion = nil
        }
        isAuthenticated = await detectAuth()
        lastCheckedAt = Date()
    }

    /// Best-effort detection of an existing login. Looks for the
    /// credentials file under ~/.claude. A `false` result just means
    /// "not detected" — the live test below is the source of truth.
    private func detectAuth() async -> Bool {
        let dir = NSString("~/.claude").expandingTildeInPath
        guard FileManager.default.fileExists(atPath: dir) else { return false }
        let credentials = [
            "\(dir)/.credentials.json",
            "\(dir)/credentials.json",
            "\(dir)/auth.json",
        ]
        for p in credentials where FileManager.default.fileExists(atPath: p) {
            return true
        }
        // Sessions directory implies prior successful logins.
        if FileManager.default.fileExists(atPath: "\(dir)/sessions") {
            return true
        }
        return false
    }

    private func findClaude() -> String? {
        let custom = UserDefaults.standard.string(forKey: "claudePath")?
            .trimmingCharacters(in: .whitespaces) ?? ""
        if !custom.isEmpty, FileManager.default.isExecutableFile(atPath: custom) {
            return custom
        }
        let candidates = [
            "/opt/homebrew/bin/claude",
            "/usr/local/bin/claude",
            NSString("~/.claude/local/claude").expandingTildeInPath,
            NSString("~/.claude/bin/claude").expandingTildeInPath,
            NSString("~/.npm-global/bin/claude").expandingTildeInPath,
        ]
        for p in candidates where FileManager.default.isExecutableFile(atPath: p) {
            return p
        }
        // Fallback to PATH.
        if let out = runSync("/usr/bin/which", ["claude"])?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !out.isEmpty, FileManager.default.isExecutableFile(atPath: out) {
            return out
        }
        return nil
    }

    // MARK: Install / login (Terminal)

    /// Drop the user into Terminal running the official Claude Code installer.
    /// Doing this in Terminal (not silently) is intentional — the script
    /// prints what it's doing and where it's installing to.
    func runInstallerInTerminal() {
        let script = """
        tell application \"Terminal\"
            activate
            do script \"curl -fsSL claude.ai/install.sh | sh && echo '' && echo 'Installer done. Close this tab and return to OpenDesk.'\"
        end tell
        """
        spawnAppleScript(script)
    }

    /// Open Terminal at `claude login` so the OAuth flow can complete.
    func runLoginInTerminal() {
        let cmd = (claudePath ?? "claude").replacingOccurrences(of: "\"", with: "\\\"")
        let script = """
        tell application \"Terminal\"
            activate
            do script \"\(cmd) login; echo ''; echo 'Login complete. Close this tab and return to OpenDesk.'\"
        end tell
        """
        spawnAppleScript(script)
    }

    private func spawnAppleScript(_ source: String) {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e", source]
        try? p.run()
    }

    /// One-shot live probe: ask Claude Code to reply with "ok". If it does,
    /// we're definitively authenticated; otherwise show the stderr to the user.
    @discardableResult
    func liveAuthProbe(timeout: TimeInterval = 12) async -> Result<String, Error> {
        isCheckingAuth = true
        defer { isCheckingAuth = false }
        guard let path = claudePath else {
            return .failure(NSError(domain: "ClaudeCode", code: -1,
                                    userInfo: [NSLocalizedDescriptionKey: "Claude Code not installed."]))
        }

        return await withCheckedContinuation { cont in
            let proc = Process()
            proc.executableURL = URL(fileURLWithPath: path)
            proc.arguments = [
                "-p", "Reply with exactly: ok",
                "--max-turns", "1",
                "--output-format", "text",
            ]
            let out = Pipe(); let err = Pipe()
            proc.standardOutput = out
            proc.standardError = err

            let timer = DispatchSource.makeTimerSource(queue: .global())
            timer.schedule(deadline: .now() + timeout)
            timer.setEventHandler { if proc.isRunning { proc.terminate() } }
            timer.resume()

            proc.terminationHandler = { p in
                timer.cancel()
                let outData = (try? out.fileHandleForReading.readToEnd()) ?? Data()
                let errData = (try? err.fileHandleForReading.readToEnd()) ?? Data()
                let outS = String(data: outData, encoding: .utf8) ?? ""
                let errS = String(data: errData, encoding: .utf8) ?? ""
                Task { @MainActor in
                    if p.terminationStatus == 0 {
                        self.isAuthenticated = true
                        cont.resume(returning: .success(outS.trimmingCharacters(in: .whitespacesAndNewlines)))
                    } else {
                        self.isAuthenticated = false
                        let msg = errS.isEmpty ? "exit \(p.terminationStatus)" : errS
                        cont.resume(returning: .failure(NSError(domain: "ClaudeCode",
                                                                code: Int(p.terminationStatus),
                                                                userInfo: [NSLocalizedDescriptionKey: msg])))
                    }
                }
            }
            do { try proc.run() } catch { cont.resume(returning: .failure(error)) }
        }
    }

    // MARK: Chat (streaming)

    /// Streams `claude -p` with the opendesk MCP server registered. The
    /// caller passes prompt + model + mcp-config path. Each event from the
    /// CLI's NDJSON stream is forwarded to `onEvent`.
    func chat(
        prompt: String,
        modelId: String,
        mcpConfigPath: String,
        maxTurns: Int,
        allowedTools: [String],
        disallowedTools: [String],
        bypassAllPermissions: Bool,
        onEvent: @escaping (Event) -> Void
    ) async {
        guard let path = claudePath else {
            onEvent(.error("Claude Code is not installed. Open Settings → Account → Install."))
            return
        }
        isRunning = true
        defer { isRunning = false; active = nil }
        lastError = nil

        var args: [String] = [
            "-p", prompt,
            "--mcp-config", mcpConfigPath,
            "--model", modelId,
            "--output-format", "stream-json",
            "--verbose",
            "--max-turns", "\(maxTurns)",
            "--append-system-prompt",
            """
            You are running inside the OpenDesk macOS app. The user can see your steps in a chat panel; the OpenDesk window is normally HIDDEN while you work so its menu bar can't steal `⌘N` / `⌘S` from the app you're driving — don't try to bring it back.

            You may only use the `opendesk` MCP server tools. DO NOT call `Bash`, `AskUserQuestion`, web fetch, or any non-opendesk tool — they are disallowed and will either fail or block. If you don't know how to do something with opendesk's tools, finish and explain.

            The opendesk MCP server exposes: `screenshot`, `mouse`, `keyboard`, `app`, `clipboard`, `ocr`, `ui`, `learn`, `schedule`.

            STRICT defaults:
            - ALWAYS pass `marks: true` to `screenshot`. The numbered Set-of-Marks overlay is how you locate clickable elements; without it, you'll be guessing pixel coordinates.
            - Take a screenshot at the START of each new visual goal AND after each state-changing action. The MCP server includes a `Change detection vs previous screenshot` hint — use it; if it says "No visible change", your last action probably didn't land.
            - Prefer `ui` (accessibility tree, click_menu, set_value) over raw `mouse` clicks. Fall back to `mouse` only when `ui get_tree` says the app has no accessible elements (Chrome web content, Electron apps, games).
            - When clicking by pixel via `mouse`, always pass `image_width` and `image_height` from the latest screenshot to compensate for Retina scaling.

            MACOS APP LAUNCH PATTERN (Chrome, Safari, etc.) — follow EXACTLY:
            1. `app` action=`open`, name=`<App>` — activates the app.
            2. Wait 600 ms — let the app finish foregrounding. (Use `mouse` action=`move` with image_width/height as a cheap delay if you need one.)
            3. `screenshot` — confirm the app is foreground (menu bar shows its name) AND has a window. Many Mac apps reopen with NO window if their last session had none.
            4. If no window is visible: `keyboard` action=`hotkey`, keys=`["command","n"]` to create one — but ONLY after the screenshot confirms the target app's menu bar is showing. If the menu bar still shows "OpenDesk", `app focus` again and re-screenshot before sending the hotkey.
            5. Re-screenshot to confirm the new window rendered.

            CHROME → GOOGLE → SEARCH (canonical recipe):
            - `app open Google Chrome` → wait → screenshot
            - If no window: hotkey command+n → screenshot
            - Click the address bar (usually around y=80 on a fresh window; let `ui get_tree` find it if possible) — or hotkey command+l to focus it directly
            - `keyboard type` "google.com" then `keyboard hotkey ["enter"]`
            - Screenshot once page loads; if Google homepage: `keyboard type` your query, `keyboard hotkey ["enter"]`

            Never invent UI elements that aren't in the latest screenshot. If something blocks you, state what and stop — the user will adjust.

            SILENT-INPUT-DROP DIAGNOSTIC. If you see TWO consecutive "No visible change detected" observations after legitimate keyboard or mouse actions, STOP. macOS TCC is dropping the input events because the Python interpreter running opendesk-mcp doesn't have Accessibility permission. Tell the user verbatim:

              "I'm taking actions but macOS is silently dropping the input events. The Python binary running opendesk-mcp needs Accessibility. Open OpenDesk → Settings → Helper binary permissions and click 'Test desktop control' to confirm, then follow the steps to add the binary."

            Do not keep retrying after that — it won't recover until the user grants the permission.

            APPS THAT REOPEN WITH NO WINDOW (TextEdit, Notes, etc.). After `app open`, if a screenshot shows the app's menu bar but no window AND command+n doesn't help, the app may be showing an iCloud-picker modal hidden behind the menu bar OR have iCloud Documents disabled. Try `keyboard press escape` once to dismiss any hidden modal, then re-screenshot and try command+n again. If still no window after that, stop and tell the user.
            """
        ]
        if !allowedTools.isEmpty {
            args.append("--allowedTools")
            args.append(allowedTools.joined(separator: ","))
        }
        if !disallowedTools.isEmpty {
            args.append("--disallowedTools")
            args.append(disallowedTools.joined(separator: ","))
        }
        if bypassAllPermissions {
            args.append("--dangerously-skip-permissions")
        }

        let cp = CancellableProcess()
        self.active = cp

        let buf = LineBuffer()
        cp.stdout.fileHandleForReading.readabilityHandler = { [weak self] handle in
            guard let self else { return }
            let data = handle.availableData
            if data.isEmpty { return }
            for s in buf.append(data) {
                Task { @MainActor in self.parseStreamLine(s, onEvent: onEvent) }
            }
        }

        let outcome = await cp.run(
            executable: URL(fileURLWithPath: path),
            arguments: args
        )

        switch outcome {
        case .cancelled:
            onEvent(.done(summary: "Stopped."))
        case .spawnFailed(let e):
            onEvent(.error(e.localizedDescription))
        case .exited(let code) where code != 0:
            let err = (try? cp.stderr.fileHandleForReading.readToEnd()) ?? Data()
            let msg = String(data: err, encoding: .utf8) ?? "exit \(code)"
            onEvent(.error(msg.trimmingCharacters(in: .whitespacesAndNewlines)))
        case .exited:
            break   // success — final NDJSON event already emitted .done
        }
    }

    // MARK: Cancel

    /// Stop the in-flight chat *and its descendants* — the claude CLI plus
    /// its opendesk-mcp grandchild, which is the one actually controlling
    /// the desktop. Implemented as `killpg(pgid)` on the session leader.
    func stop() { active?.cancel() }

    // MARK: NDJSON parsing

    private func parseStreamLine(_ line: String, onEvent: (Event) -> Void) {
        guard let data = line.data(using: .utf8),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return
        }
        let kind = obj["type"] as? String

        switch kind {
        case "assistant":
            guard let msg = obj["message"] as? [String: Any],
                  let content = msg["content"] as? [[String: Any]] else { return }
            for block in content {
                let bt = block["type"] as? String
                if bt == "text", let text = block["text"] as? String, !text.isEmpty {
                    onEvent(.text(text))
                } else if bt == "tool_use",
                          let name = block["name"] as? String {
                    let input = (block["input"] as? [String: Any]) ?? [:]
                    onEvent(.toolUse(name: name, input: input))
                }
            }

        case "user":
            // Tool results show up as user messages in Claude Code's stream.
            guard let msg = obj["message"] as? [String: Any],
                  let content = msg["content"] as? [[String: Any]] else { return }
            for block in content {
                if (block["type"] as? String) == "tool_result" {
                    var text = ""
                    var image: String?
                    if let arr = block["content"] as? [[String: Any]] {
                        for c in arr {
                            switch c["type"] as? String {
                            case "text":
                                if let t = c["text"] as? String { text += t }
                            case "image":
                                if let src = c["source"] as? [String: Any],
                                   let b64 = src["data"] as? String {
                                    image = b64
                                }
                            default: break
                            }
                        }
                    } else if let s = block["content"] as? String {
                        text = s
                    }
                    onEvent(.toolResult(text: text, imageB64: image))
                }
            }

        case "result":
            let summary = (obj["result"] as? String)
                ?? (obj["text"] as? String)
            onEvent(.done(summary: summary))

        default:
            break
        }
    }

    // MARK: Helpers

    /// Thread-safe newline-splitting buffer for the readability handler.
    private final class LineBuffer: @unchecked Sendable {
        private var data = Data()
        private let lock = NSLock()
        func append(_ chunk: Data) -> [String] {
            lock.lock(); defer { lock.unlock() }
            data.append(chunk)
            var lines: [String] = []
            while let nl = data.firstIndex(of: 0x0A) {
                let line = data[..<nl]
                data.removeSubrange(...nl)
                if let s = String(data: line, encoding: .utf8), !s.isEmpty {
                    lines.append(s)
                }
            }
            return lines
        }
    }

    private func runSync(_ exec: String, _ args: [String]) -> String? {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exec)
        p.arguments = args
        let out = Pipe(); p.standardOutput = out
        p.standardError = Pipe()
        do {
            try p.run()
            p.waitUntilExit()
            let data = (try? out.fileHandleForReading.readToEnd()) ?? Data()
            return String(data: data, encoding: .utf8)
        } catch { return nil }
    }
}
