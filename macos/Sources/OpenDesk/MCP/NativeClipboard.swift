import Foundation
import AppKit

enum NativeClipboard {

    static func handle(args: [String: Any]) throws -> [[String: Any]] {
        let action = args.str("action") ?? "read"
        let pb = NSPasteboard.general

        switch action {
        case "read":
            let s = pb.string(forType: .string) ?? ""
            return [["type": "text", "text": s.isEmpty ? "(clipboard is empty)" : s]]
        case "write":
            let text = args.str("text") ?? ""
            pb.clearContents()
            pb.setString(text, forType: .string)
            return [["type": "text", "text": "Wrote \(text.count) char\(text.count == 1 ? "" : "s") to clipboard."]]
        default:
            throw NativeTools.ToolError("Unknown clipboard action: \(action)")
        }
    }
}
