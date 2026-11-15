import Foundation
import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

/// Tool catalog + dispatcher. Each tool returns an array of MCP content
/// blocks (`[{type:"text"|"image", ...}]`). Errors throw and the server
/// wraps them in `isError: true`.
enum NativeTools {

    struct ToolError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
        init(_ m: String) { message = m }
    }

    /// JSON tool definitions for the `tools/list` response.
    static func list() -> [[String: Any]] {
        [
            tool(name: "screenshot",
                 description: "Capture the entire main display as a PNG.",
                 props: [
                    "marks": ["type": "boolean", "description": "Reserved — currently captures without overlay."]
                 ]),
            tool(name: "mouse",
                 description: "Move, click, scroll or read the mouse cursor.",
                 required: ["action"],
                 props: [
                    "action": ["type": "string",
                               "enum": ["move", "click", "double_click", "triple_click",
                                        "right_click", "middle_click", "left_down", "left_up",
                                        "scroll", "drag", "cursor_position"]],
                    "x": ["type": "integer"],
                    "y": ["type": "integer"],
                    "end_x": ["type": "integer"],
                    "end_y": ["type": "integer"],
                    "direction": ["type": "string", "enum": ["up", "down", "left", "right"]],
                    "amount": ["type": "integer", "description": "Scroll lines or click count."],
                    "image_width": ["type": "integer", "description": "Width of the screenshot the coordinates came from (for Retina scaling)."],
                    "image_height": ["type": "integer"]
                 ]),
            tool(name: "keyboard",
                 description: "Type text or send a hotkey combo.",
                 required: ["action"],
                 props: [
                    "action": ["type": "string", "enum": ["type", "hotkey", "press"]],
                    "text": ["type": "string", "description": "Text to type (action=type)."],
                    "key":  ["type": "string", "description": "Single key name (action=press)."],
                    "keys": ["type": "array", "items": ["type": "string"],
                             "description": "Combo for action=hotkey, e.g. ['command','n']."]
                 ]),
            tool(name: "app",
                 description: "Open, close, focus or list applications.",
                 required: ["action"],
                 props: [
                    "action": ["type": "string", "enum": ["open", "close", "focus", "list"]],
                    "name": ["type": "string", "description": "App name (e.g. 'Safari')."]
                 ]),
            tool(name: "clipboard",
                 description: "Read or write the system pasteboard.",
                 required: ["action"],
                 props: [
                    "action": ["type": "string", "enum": ["read", "write"]],
                    "text": ["type": "string"]
                 ]),
        ]
    }

    static func call(name: String, args: [String: Any]) throws -> [[String: Any]] {
        switch name {
        case "screenshot": return try NativeScreenshot.capture(args: args)
        case "mouse":      return try NativeMouse.handle(args: args)
        case "keyboard":   return try NativeKeyboard.handle(args: args)
        case "app":        return try NativeApp.handle(args: args)
        case "clipboard":  return try NativeClipboard.handle(args: args)
        default: throw ToolError("Unknown tool: \(name)")
        }
    }

    // MARK: Schema helpers

    private static func tool(name: String,
                             description: String,
                             required: [String] = [],
                             props: [String: [String: Any]]) -> [String: Any] {
        return [
            "name": name,
            "description": description,
            "inputSchema": [
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": true
            ]
        ]
    }
}

// MARK: Convenience

extension Dictionary where Key == String, Value == Any {
    func int(_ k: String) -> Int? {
        if let v = self[k] as? Int { return v }
        if let v = self[k] as? Double { return Int(v) }
        if let s = self[k] as? String { return Int(s) }
        return nil
    }
    func str(_ k: String) -> String? { self[k] as? String }
    func bool(_ k: String) -> Bool? {
        if let v = self[k] as? Bool { return v }
        if let v = self[k] as? Int { return v != 0 }
        return nil
    }
    func stringArray(_ k: String) -> [String]? {
        if let a = self[k] as? [String] { return a }
        if let a = self[k] as? [Any] { return a.compactMap { $0 as? String } }
        return nil
    }
}
