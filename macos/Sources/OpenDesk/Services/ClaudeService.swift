import Foundation
import AppKit
import SwiftUI

/// Talks to Anthropic's Messages API and runs the computer-use tool loop.
/// Bring-your-own-key — the user provides it via Settings; never baked in.
@MainActor
final class ClaudeService: ObservableObject {

    static let endpoint = URL(string: "https://api.anthropic.com/v1/messages")!
    static let anthropicVersion = "2023-06-01"
    static let computerBeta = "computer-use-2025-01-24"

    @Published var isRunning = false
    @Published var lastError: String?

    struct LoopStep: Identifiable {
        let id = UUID()
        let kind: Kind
        let detail: String
        let imageB64: String?
        enum Kind { case thought, tool, observation, error, done }
    }

    /// Run one turn of the computer-use loop.
    /// `messages` is the running conversation (text & tool_result blocks).
    /// `onStep` is called as each tool invocation / model output is received.
    func sendTurn(
        apiKey: String,
        modelId: String,
        userText: String,
        history: [[String: Any]],
        maxSteps: Int,
        includeMarks: Bool,
        bridge: OpenDeskBridge,
        screenSize: CGSize,
        onStep: @escaping (LoopStep) -> Void
    ) async -> [[String: Any]] {
        isRunning = true
        defer { isRunning = false }
        lastError = nil

        var messages = history
        messages.append([
            "role": "user",
            "content": [["type": "text", "text": userText]]
        ])

        for step in 0..<maxSteps {
            do {
                let response = try await requestOnce(
                    apiKey: apiKey,
                    modelId: modelId,
                    messages: messages,
                    displayWidth: Int(screenSize.width),
                    displayHeight: Int(screenSize.height)
                )

                let content = (response["content"] as? [[String: Any]]) ?? []
                let stop = response["stop_reason"] as? String

                // Surface text the model emitted.
                for block in content {
                    if (block["type"] as? String) == "text",
                       let text = block["text"] as? String,
                       !text.isEmpty {
                        onStep(.init(kind: .thought, detail: text, imageB64: nil))
                    }
                }

                // Append assistant message verbatim.
                messages.append([
                    "role": "assistant",
                    "content": content
                ])

                // Find tool_use blocks and execute them.
                let toolUses = content.filter { ($0["type"] as? String) == "tool_use" }

                if toolUses.isEmpty || stop == "end_turn" {
                    onStep(.init(kind: .done, detail: "Turn complete.", imageB64: nil))
                    break
                }

                var toolResults: [[String: Any]] = []
                for tu in toolUses {
                    let toolId = (tu["id"] as? String) ?? UUID().uuidString
                    let toolName = (tu["name"] as? String) ?? ""
                    let input = (tu["input"] as? [String: Any]) ?? [:]
                    onStep(.init(kind: .tool,
                                 detail: prettyTool(toolName, input: input),
                                 imageB64: nil))

                    let (resultBlocks, imgB64) = await executeComputerTool(
                        bridge: bridge,
                        input: input,
                        includeMarks: includeMarks
                    )
                    if let imgB64 {
                        onStep(.init(kind: .observation, detail: "Screen captured.", imageB64: imgB64))
                    }
                    toolResults.append([
                        "type": "tool_result",
                        "tool_use_id": toolId,
                        "content": resultBlocks
                    ])
                }

                messages.append(["role": "user", "content": toolResults])

                if step == maxSteps - 1 {
                    onStep(.init(kind: .error, detail: "Hit max-step limit (\(maxSteps)).", imageB64: nil))
                }
            } catch {
                lastError = error.localizedDescription
                onStep(.init(kind: .error, detail: error.localizedDescription, imageB64: nil))
                break
            }
        }
        return messages
    }

    // MARK: One API request

    private func requestOnce(
        apiKey: String,
        modelId: String,
        messages: [[String: Any]],
        displayWidth: Int,
        displayHeight: Int
    ) async throws -> [String: Any] {

        let computerTool: [String: Any] = [
            "type": "computer_20250124",
            "name": "computer",
            "display_width_px": displayWidth,
            "display_height_px": displayHeight,
            "display_number": 1
        ]

        let body: [String: Any] = [
            "model": modelId,
            "max_tokens": 4096,
            "tools": [computerTool],
            "messages": messages,
            "system": "You are Claude controlling a macOS computer through the OpenDesk framework. Be deliberate: take a screenshot whenever you are unsure about screen state, never invent UI elements, and confirm actions worked before moving on."
        ]

        var req = URLRequest(url: Self.endpoint)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "content-type")
        req.setValue(apiKey, forHTTPHeaderField: "x-api-key")
        req.setValue(Self.anthropicVersion, forHTTPHeaderField: "anthropic-version")
        req.setValue(Self.computerBeta, forHTTPHeaderField: "anthropic-beta")
        req.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let text = String(data: data, encoding: .utf8) ?? "<no body>"
            throw NSError(domain: "ClaudeAPI", code: (resp as? HTTPURLResponse)?.statusCode ?? -1,
                          userInfo: [NSLocalizedDescriptionKey: text])
        }
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NSError(domain: "ClaudeAPI", code: -2,
                          userInfo: [NSLocalizedDescriptionKey: "non-JSON response"])
        }
        return json
    }

    // MARK: Computer tool dispatch

    /// Translate a single Claude computer-tool call into opendesk ops.
    /// Returns the content blocks to put in the `tool_result` and, if the call
    /// produced a screenshot, its base64 PNG for the UI.
    private func executeComputerTool(
        bridge: OpenDeskBridge,
        input: [String: Any],
        includeMarks: Bool
    ) async -> ([[String: Any]], String?) {
        let action = (input["action"] as? String) ?? ""

        do {
            switch action {
            case "screenshot":
                let resp = try await bridge.run("screenshot", params: ["marks": includeMarks])
                if let b64 = resp.imageB64 {
                    return ([["type": "image",
                              "source": ["type": "base64",
                                         "media_type": "image/png",
                                         "data": b64]]], b64)
                }
                return ([["type": "text", "text": "screenshot ok but no image"]], nil)

            case "left_click", "right_click", "middle_click", "double_click", "triple_click":
                let (x, y) = coords(from: input)
                let button: String = {
                    switch action {
                    case "right_click":  return "right"
                    case "middle_click": return "middle"
                    default:             return "left"
                    }
                }()
                let clicks = (action == "double_click") ? 2 : (action == "triple_click" ? 3 : 1)
                _ = try await bridge.run("mouse", params: [
                    "action": "click",
                    "x": x, "y": y,
                    "button": button,
                    "clicks": clicks
                ])
                return ([["type": "text", "text": "clicked \(button) @ (\(x),\(y)) x\(clicks)"]], nil)

            case "mouse_move":
                let (x, y) = coords(from: input)
                _ = try await bridge.run("mouse", params: ["action": "move", "x": x, "y": y])
                return ([["type": "text", "text": "moved to (\(x),\(y))"]], nil)

            case "left_mouse_down":
                let (x, y) = coords(from: input)
                _ = try await bridge.run("mouse", params: ["action": "down", "x": x, "y": y, "button": "left"])
                return ([["type": "text", "text": "mouse down @ (\(x),\(y))"]], nil)

            case "left_mouse_up":
                let (x, y) = coords(from: input)
                _ = try await bridge.run("mouse", params: ["action": "up", "x": x, "y": y, "button": "left"])
                return ([["type": "text", "text": "mouse up @ (\(x),\(y))"]], nil)

            case "scroll":
                let (x, y) = coords(from: input)
                let dir = (input["scroll_direction"] as? String) ?? "down"
                let amt = (input["scroll_amount"] as? Int) ?? 3
                _ = try await bridge.run("mouse", params: [
                    "action": "scroll", "x": x, "y": y,
                    "direction": dir, "amount": amt
                ])
                return ([["type": "text", "text": "scrolled \(dir) by \(amt) @ (\(x),\(y))"]], nil)

            case "type":
                let text = (input["text"] as? String) ?? ""
                _ = try await bridge.run("keyboard", params: ["action": "type", "text": text])
                return ([["type": "text", "text": "typed \(text.count) chars"]], nil)

            case "key":
                let text = (input["text"] as? String) ?? ""
                _ = try await bridge.run("keyboard", params: ["action": "hotkey", "keys": text])
                return ([["type": "text", "text": "pressed \(text)"]], nil)

            case "cursor_position":
                let resp = try await bridge.run("mouse", params: ["action": "position"])
                let summary = (resp.result as? [String: Any]).flatMap {
                    (try? JSONSerialization.data(withJSONObject: $0))
                        .flatMap { String(data: $0, encoding: .utf8) }
                } ?? "ok"
                return ([["type": "text", "text": summary]], nil)

            case "wait":
                let secs = (input["duration"] as? Double) ?? 1.0
                try await Task.sleep(nanoseconds: UInt64(secs * 1_000_000_000))
                return ([["type": "text", "text": "waited \(secs)s"]], nil)

            default:
                return ([["type": "text", "text": "unhandled action: \(action)"]], nil)
            }
        } catch {
            return ([["type": "text", "text": "error: \(error.localizedDescription)"]], nil)
        }
    }

    private func coords(from input: [String: Any]) -> (Int, Int) {
        if let arr = input["coordinate"] as? [Any], arr.count >= 2 {
            let x = (arr[0] as? Int) ?? Int((arr[0] as? Double) ?? 0)
            let y = (arr[1] as? Int) ?? Int((arr[1] as? Double) ?? 0)
            return (x, y)
        }
        let x = (input["x"] as? Int) ?? Int((input["x"] as? Double) ?? 0)
        let y = (input["y"] as? Int) ?? Int((input["y"] as? Double) ?? 0)
        return (x, y)
    }

    private func prettyTool(_ name: String, input: [String: Any]) -> String {
        let action = (input["action"] as? String) ?? "?"
        return "\(name).\(action)"
    }
}
