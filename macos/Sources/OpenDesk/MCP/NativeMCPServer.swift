import Foundation

/// Minimal MCP server running inside the OpenDesk binary. Speaks JSON-RPC
/// 2.0 over stdio (one JSON message per line). Every tool call runs
/// **inside this process**, so macOS TCC checks happen against OpenDesk.app's
/// signature — meaning one Accessibility grant in System Settings is enough
/// for everything. No Python, no shim, no symlink hunting.
///
/// Wire-up: claude-code spawns `OpenDesk.app/Contents/MacOS/OpenDesk --mcp`
/// (configured via MCPRegistration) and pipes JSON-RPC over its stdin/stdout.
enum NativeMCPServer {

    static func run() -> Never {
        // Line-buffered stdout so claude sees each response promptly.
        setvbuf(stdout, nil, _IOLBF, 0)
        // stderr is unbuffered for diagnostics.
        setvbuf(stderr, nil, _IONBF, 0)
        fputs("[opendesk-native-mcp] ready\n", stderr)

        while let line = readLine(strippingNewline: true) {
            guard let data = line.data(using: .utf8),
                  let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue
            }
            if let resp = handle(msg) {
                writeMessage(resp)
            }
        }
        exit(0)
    }

    // MARK: Dispatch

    private static func handle(_ msg: [String: Any]) -> [String: Any]? {
        let id = msg["id"]
        let method = (msg["method"] as? String) ?? ""
        let params = (msg["params"] as? [String: Any]) ?? [:]

        switch method {
        case "initialize":
            return reply(id: id, result: [
                "protocolVersion": "2024-11-05",
                "capabilities": ["tools": [:] as [String: Any]],
                "serverInfo": ["name": "opendesk-native", "version": "0.3.0"]
            ])

        case "notifications/initialized":
            return nil   // notifications get no response

        case "tools/list":
            return reply(id: id, result: ["tools": NativeTools.list()])

        case "tools/call":
            let name = (params["name"] as? String) ?? ""
            let args = (params["arguments"] as? [String: Any]) ?? [:]
            do {
                let content = try NativeTools.call(name: name, args: args)
                return reply(id: id, result: ["content": content, "isError": false])
            } catch {
                // MCP spec wants tool errors as result.isError=true, not protocol errors.
                return reply(id: id, result: [
                    "content": [["type": "text", "text": "Error: \(error.localizedDescription)"]],
                    "isError": true
                ])
            }

        case "ping":
            return reply(id: id, result: [:] as [String: Any])

        default:
            return reply(id: id, error: ["code": -32601, "message": "method not found: \(method)"])
        }
    }

    // MARK: Frame helpers

    private static func reply(id: Any?, result: [String: Any]) -> [String: Any] {
        var out: [String: Any] = ["jsonrpc": "2.0", "result": result]
        if let id = id { out["id"] = id }
        return out
    }

    private static func reply(id: Any?, error: [String: Any]) -> [String: Any] {
        var out: [String: Any] = ["jsonrpc": "2.0", "error": error]
        if let id = id { out["id"] = id }
        return out
    }

    private static func writeMessage(_ obj: [String: Any]) {
        guard let data = try? JSONSerialization.data(withJSONObject: obj,
                                                     options: [.withoutEscapingSlashes]) else {
            return
        }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write("\n".data(using: .utf8)!)
    }
}
