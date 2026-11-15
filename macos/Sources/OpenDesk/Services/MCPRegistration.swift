import Foundation

/// Writes the `--mcp-config` file that wires `opendesk` into Claude Code.
/// We pick the best Python + opendesk-mcp combination available on the box.
enum MCPRegistration {

    struct ResolvedRuntime {
        let command: String           // executable to run
        let args: [String]            // its args
        let env: [String: String]     // any env vars needed (e.g. PYTHONPATH)
        let prettyName: String        // for the UI
    }

    /// We are the MCP server. Point claude at our own signed binary, run
    /// with `--mcp`. Every tool call then executes inside OpenDesk.app, so
    /// macOS TCC checks against OpenDesk.app's Accessibility grant — the
    /// one the user authorized when they first opened the app.
    static func resolveRuntime() -> ResolvedRuntime {
        let binary = Bundle.main.executableURL?.path ?? "/usr/local/bin/OpenDesk"
        return .init(command: binary,
                     args: ["--mcp"],
                     env: [:],
                     prettyName: "OpenDesk (native MCP)")
    }

    /// Build the MCP config and write it to a temp file. Returns the path.
    /// The file persists for the app lifetime so multi-turn chats can reuse it.
    private static var cachedPath: String?

    static func writeOpenDeskConfig() throws -> String {
        if let p = cachedPath, FileManager.default.fileExists(atPath: p) {
            return p
        }
        let rt = resolveRuntime()
        let server: [String: Any] = [
            "command": rt.command,
            "args": rt.args,
            "env": rt.env,
        ]
        let config: [String: Any] = ["mcpServers": ["opendesk": server]]

        let dir = NSTemporaryDirectory()
        let path = (dir as NSString).appendingPathComponent("opendesk-mcp-config.json")
        let data = try JSONSerialization.data(withJSONObject: config, options: [.prettyPrinted])
        try data.write(to: URL(fileURLWithPath: path))
        cachedPath = path
        return path
    }

    /// Pretty description for the Settings card so the user knows which
    /// runtime Claude Code will spawn for the MCP server.
    static func describeRuntime() -> String {
        let rt = resolveRuntime()
        var parts = [rt.command]
        parts.append(contentsOf: rt.args)
        var line = parts.joined(separator: " ")
        if let pp = rt.env["PYTHONPATH"] { line = "PYTHONPATH=\(pp) " + line }
        return line
    }
}
