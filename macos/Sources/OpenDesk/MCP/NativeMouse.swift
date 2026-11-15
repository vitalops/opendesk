import Foundation
import CoreGraphics
import AppKit

enum NativeMouse {

    static func handle(args: [String: Any]) throws -> [[String: Any]] {
        let action = args.str("action") ?? "move"

        switch action {
        case "cursor_position":
            let p = currentLocation()
            return text("Current cursor: (\(Int(p.x)), \(Int(p.y)))")

        case "move":
            let (x, y) = try point(args)
            move(to: CGPoint(x: x, y: y))
            return text("Moved to (\(x), \(y)).")

        case "click":
            let (x, y) = try point(args)
            click(at: CGPoint(x: x, y: y), button: .left, count: args.int("amount") ?? 1)
            return text("Clicked at (\(x), \(y)).")

        case "double_click":
            let (x, y) = try point(args)
            click(at: CGPoint(x: x, y: y), button: .left, count: 2)
            return text("Double-clicked at (\(x), \(y)).")

        case "triple_click":
            let (x, y) = try point(args)
            click(at: CGPoint(x: x, y: y), button: .left, count: 3)
            return text("Triple-clicked at (\(x), \(y)).")

        case "right_click":
            let (x, y) = try point(args)
            click(at: CGPoint(x: x, y: y), button: .right, count: 1)
            return text("Right-clicked at (\(x), \(y)).")

        case "middle_click":
            let (x, y) = try point(args)
            click(at: CGPoint(x: x, y: y), button: .center, count: 1)
            return text("Middle-clicked at (\(x), \(y)).")

        case "left_down":
            let (x, y) = try point(args)
            postMouse(type: .leftMouseDown, at: CGPoint(x: x, y: y), button: .left)
            return text("Left mouse down at (\(x), \(y)).")

        case "left_up":
            let (x, y) = try point(args)
            postMouse(type: .leftMouseUp, at: CGPoint(x: x, y: y), button: .left)
            return text("Left mouse up at (\(x), \(y)).")

        case "scroll":
            let dir = args.str("direction") ?? "down"
            let amt = Int32(args.int("amount") ?? 3)
            let (dx, dy): (Int32, Int32) = {
                switch dir {
                case "up":    return (0,  amt)
                case "down":  return (0, -amt)
                case "left":  return ( amt, 0)
                case "right": return (-amt, 0)
                default:      return (0, -amt)
                }
            }()
            if let scroll = CGEvent(scrollWheelEvent2Source: nil,
                                    units: .line,
                                    wheelCount: 2,
                                    wheel1: dy, wheel2: dx, wheel3: 0) {
                scroll.post(tap: .cghidEventTap)
            }
            return text("Scrolled \(dir) by \(amt) lines.")

        case "drag":
            let (sx, sy) = try point(args)
            guard let endX = args.int("end_x"), let endY = args.int("end_y") else {
                throw NativeTools.ToolError("drag requires end_x and end_y")
            }
            let start = CGPoint(x: sx, y: sy)
            let end = CGPoint(x: endX, y: endY)
            postMouse(type: .leftMouseDown, at: start, button: .left)
            Thread.sleep(forTimeInterval: 0.05)
            postMouse(type: .leftMouseDragged, at: end, button: .left)
            Thread.sleep(forTimeInterval: 0.05)
            postMouse(type: .leftMouseUp, at: end, button: .left)
            return text("Dragged (\(sx), \(sy)) → (\(endX), \(endY)).")

        default:
            throw NativeTools.ToolError("Unknown mouse action: \(action)")
        }
    }

    // MARK: Low-level

    private static func currentLocation() -> CGPoint {
        // NSEvent.mouseLocation is in Cocoa coords (origin bottom-left).
        let p = NSEvent.mouseLocation
        let h = NSScreen.main?.frame.height ?? 0
        return CGPoint(x: p.x, y: h - p.y)
    }

    /// Convert (x, y) from the model's coordinate frame to Quartz screen
    /// coords. If `image_width`/`image_height` is supplied we treat (x, y)
    /// as a fraction of that frame; otherwise we assume points.
    private static func point(_ args: [String: Any]) throws -> (Int, Int) {
        guard let x = args.int("x"), let y = args.int("y") else {
            throw NativeTools.ToolError("x and y required")
        }
        if let iw = args.int("image_width"), let ih = args.int("image_height"),
           let screen = NSScreen.main {
            let sx = Int(Double(x) / Double(iw) * Double(screen.frame.width))
            let sy = Int(Double(y) / Double(ih) * Double(screen.frame.height))
            return (sx, sy)
        }
        return (x, y)
    }

    private static func move(to p: CGPoint) {
        postMouse(type: .mouseMoved, at: p, button: .left)
    }

    private static func click(at p: CGPoint, button: CGMouseButton, count: Int) {
        let downType: CGEventType = {
            switch button {
            case .left:   return .leftMouseDown
            case .right:  return .rightMouseDown
            case .center: return .otherMouseDown
            @unknown default: return .leftMouseDown
            }
        }()
        let upType: CGEventType = {
            switch button {
            case .left:   return .leftMouseUp
            case .right:  return .rightMouseUp
            case .center: return .otherMouseUp
            @unknown default: return .leftMouseUp
            }
        }()
        for i in 1...max(1, count) {
            if let down = CGEvent(mouseEventSource: nil, mouseType: downType,
                                  mouseCursorPosition: p, mouseButton: button) {
                down.setIntegerValueField(.mouseEventClickState, value: Int64(i))
                down.post(tap: .cghidEventTap)
            }
            if let up = CGEvent(mouseEventSource: nil, mouseType: upType,
                                mouseCursorPosition: p, mouseButton: button) {
                up.setIntegerValueField(.mouseEventClickState, value: Int64(i))
                up.post(tap: .cghidEventTap)
            }
        }
    }

    private static func postMouse(type: CGEventType, at p: CGPoint, button: CGMouseButton) {
        if let e = CGEvent(mouseEventSource: nil, mouseType: type,
                           mouseCursorPosition: p, mouseButton: button) {
            e.post(tap: .cghidEventTap)
        }
    }

    private static func text(_ s: String) -> [[String: Any]] {
        [["type": "text", "text": s]]
    }
}
