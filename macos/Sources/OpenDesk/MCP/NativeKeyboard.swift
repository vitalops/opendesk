import Foundation
import CoreGraphics
import Carbon.HIToolbox

enum NativeKeyboard {

    static func handle(args: [String: Any]) throws -> [[String: Any]] {
        let action = args.str("action") ?? "type"
        switch action {
        case "type":
            let text = args.str("text") ?? ""
            typeUnicode(text)
            return reply("Typed \(text.count) char\(text.count == 1 ? "" : "s").")

        case "press":
            let key = args.str("key") ?? ""
            guard let kc = keycode(for: key.lowercased()) else {
                throw NativeTools.ToolError("Unknown key: \(key)")
            }
            tap(virtualKey: kc, flags: [])
            return reply("Pressed \(key).")

        case "hotkey":
            let keys = (args.stringArray("keys") ?? args.str("keys")?
                            .split(separator: "+").map(String.init) ?? [])
                            .map { $0.lowercased() }
            try sendHotkey(keys: keys)
            return reply("Sent hotkey \(keys.joined(separator: "+")).")

        default:
            throw NativeTools.ToolError("Unknown keyboard action: \(action)")
        }
    }

    // MARK: Typing text

    /// Type any Unicode string by setting it on a keyboard event directly —
    /// no virtual-keycode table needed, works across keyboard layouts.
    static func typeUnicode(_ text: String) {
        // Chunk to avoid hitting the per-event payload limit.
        for chunk in text.split(every: 16) {
            let utf16 = Array(chunk.utf16)
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true) else { continue }
            utf16.withUnsafeBufferPointer { ptr in
                down.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: ptr.baseAddress)
            }
            down.post(tap: .cghidEventTap)
            if let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) {
                utf16.withUnsafeBufferPointer { ptr in
                    up.keyboardSetUnicodeString(stringLength: utf16.count, unicodeString: ptr.baseAddress)
                }
                up.post(tap: .cghidEventTap)
            }
        }
    }

    // MARK: Hotkeys

    private static func sendHotkey(keys: [String]) throws {
        var flags: CGEventFlags = []
        var mainKeycode: CGKeyCode?
        for k in keys {
            if let mod = modifier(for: k) {
                flags.insert(mod)
            } else if let kc = keycode(for: k) {
                mainKeycode = kc
            } else {
                throw NativeTools.ToolError("Unknown key in hotkey: \(k)")
            }
        }
        if let kc = mainKeycode {
            tap(virtualKey: kc, flags: flags)
        } else {
            // No main key — just modifier presses (rare but allowed).
            // Press+release each modifier individually as fallback.
            for k in keys {
                if let kc = keycode(for: k) { tap(virtualKey: kc, flags: []) }
            }
        }
    }

    private static func tap(virtualKey: CGKeyCode, flags: CGEventFlags) {
        if let down = CGEvent(keyboardEventSource: nil, virtualKey: virtualKey, keyDown: true) {
            down.flags = flags
            down.post(tap: .cghidEventTap)
        }
        if let up = CGEvent(keyboardEventSource: nil, virtualKey: virtualKey, keyDown: false) {
            up.flags = flags
            up.post(tap: .cghidEventTap)
        }
    }

    // MARK: Tables

    private static func modifier(for name: String) -> CGEventFlags? {
        switch name {
        case "cmd", "command", "meta": return .maskCommand
        case "shift":                  return .maskShift
        case "opt", "option", "alt":   return .maskAlternate
        case "ctrl", "control":        return .maskControl
        case "fn":                     return .maskSecondaryFn
        default:                       return nil
        }
    }

    private static func keycode(for name: String) -> CGKeyCode? {
        switch name {
        // Letters
        case "a": return CGKeyCode(kVK_ANSI_A)
        case "b": return CGKeyCode(kVK_ANSI_B)
        case "c": return CGKeyCode(kVK_ANSI_C)
        case "d": return CGKeyCode(kVK_ANSI_D)
        case "e": return CGKeyCode(kVK_ANSI_E)
        case "f": return CGKeyCode(kVK_ANSI_F)
        case "g": return CGKeyCode(kVK_ANSI_G)
        case "h": return CGKeyCode(kVK_ANSI_H)
        case "i": return CGKeyCode(kVK_ANSI_I)
        case "j": return CGKeyCode(kVK_ANSI_J)
        case "k": return CGKeyCode(kVK_ANSI_K)
        case "l": return CGKeyCode(kVK_ANSI_L)
        case "m": return CGKeyCode(kVK_ANSI_M)
        case "n": return CGKeyCode(kVK_ANSI_N)
        case "o": return CGKeyCode(kVK_ANSI_O)
        case "p": return CGKeyCode(kVK_ANSI_P)
        case "q": return CGKeyCode(kVK_ANSI_Q)
        case "r": return CGKeyCode(kVK_ANSI_R)
        case "s": return CGKeyCode(kVK_ANSI_S)
        case "t": return CGKeyCode(kVK_ANSI_T)
        case "u": return CGKeyCode(kVK_ANSI_U)
        case "v": return CGKeyCode(kVK_ANSI_V)
        case "w": return CGKeyCode(kVK_ANSI_W)
        case "x": return CGKeyCode(kVK_ANSI_X)
        case "y": return CGKeyCode(kVK_ANSI_Y)
        case "z": return CGKeyCode(kVK_ANSI_Z)
        // Digits
        case "0": return CGKeyCode(kVK_ANSI_0)
        case "1": return CGKeyCode(kVK_ANSI_1)
        case "2": return CGKeyCode(kVK_ANSI_2)
        case "3": return CGKeyCode(kVK_ANSI_3)
        case "4": return CGKeyCode(kVK_ANSI_4)
        case "5": return CGKeyCode(kVK_ANSI_5)
        case "6": return CGKeyCode(kVK_ANSI_6)
        case "7": return CGKeyCode(kVK_ANSI_7)
        case "8": return CGKeyCode(kVK_ANSI_8)
        case "9": return CGKeyCode(kVK_ANSI_9)
        // Whitespace / control
        case "return", "enter":   return CGKeyCode(kVK_Return)
        case "tab":               return CGKeyCode(kVK_Tab)
        case "space":             return CGKeyCode(kVK_Space)
        case "delete", "backspace": return CGKeyCode(kVK_Delete)
        case "esc", "escape":     return CGKeyCode(kVK_Escape)
        case "forward_delete":    return CGKeyCode(kVK_ForwardDelete)
        case "left":              return CGKeyCode(kVK_LeftArrow)
        case "right":             return CGKeyCode(kVK_RightArrow)
        case "up":                return CGKeyCode(kVK_UpArrow)
        case "down":              return CGKeyCode(kVK_DownArrow)
        case "home":              return CGKeyCode(kVK_Home)
        case "end":               return CGKeyCode(kVK_End)
        case "page_up":           return CGKeyCode(kVK_PageUp)
        case "page_down":         return CGKeyCode(kVK_PageDown)
        // Function keys
        case "f1":  return CGKeyCode(kVK_F1)
        case "f2":  return CGKeyCode(kVK_F2)
        case "f3":  return CGKeyCode(kVK_F3)
        case "f4":  return CGKeyCode(kVK_F4)
        case "f5":  return CGKeyCode(kVK_F5)
        case "f6":  return CGKeyCode(kVK_F6)
        case "f7":  return CGKeyCode(kVK_F7)
        case "f8":  return CGKeyCode(kVK_F8)
        case "f9":  return CGKeyCode(kVK_F9)
        case "f10": return CGKeyCode(kVK_F10)
        case "f11": return CGKeyCode(kVK_F11)
        case "f12": return CGKeyCode(kVK_F12)
        // Punctuation
        case "-", "minus":         return CGKeyCode(kVK_ANSI_Minus)
        case "=", "equals":        return CGKeyCode(kVK_ANSI_Equal)
        case "[":                  return CGKeyCode(kVK_ANSI_LeftBracket)
        case "]":                  return CGKeyCode(kVK_ANSI_RightBracket)
        case "\\", "backslash":    return CGKeyCode(kVK_ANSI_Backslash)
        case ";", "semicolon":     return CGKeyCode(kVK_ANSI_Semicolon)
        case "'", "quote":         return CGKeyCode(kVK_ANSI_Quote)
        case ",", "comma":         return CGKeyCode(kVK_ANSI_Comma)
        case ".", "period":        return CGKeyCode(kVK_ANSI_Period)
        case "/", "slash":         return CGKeyCode(kVK_ANSI_Slash)
        case "`", "grave":         return CGKeyCode(kVK_ANSI_Grave)
        default: return nil
        }
    }

    private static func reply(_ s: String) -> [[String: Any]] {
        [["type": "text", "text": s]]
    }
}

private extension String {
    /// Split into substrings of length n (last chunk may be shorter).
    func split(every n: Int) -> [Substring] {
        guard n > 0 else { return [Substring(self)] }
        var result: [Substring] = []
        var idx = startIndex
        while idx < endIndex {
            let next = index(idx, offsetBy: n, limitedBy: endIndex) ?? endIndex
            result.append(self[idx..<next])
            idx = next
        }
        return result
    }
}
