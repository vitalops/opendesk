import SwiftUI

/// Three-state permission for an MCP tool: pre-approved, prompts each
/// time, or hard-denied.
enum ToolPermission: String, Codable, CaseIterable, Identifiable, Hashable {
    case allow, ask, deny
    var id: String { rawValue }

    var label: String {
        switch self {
        case .allow: "Allow"
        case .ask:   "Ask"
        case .deny:  "Deny"
        }
    }

    var icon: String {
        switch self {
        case .allow: "checkmark.circle.fill"
        case .ask:   "questionmark.circle.fill"
        case .deny:  "xmark.octagon.fill"
        }
    }

    var tint: Color {
        switch self {
        case .allow: Theme.mint
        case .ask:   Theme.amber
        case .deny:  Theme.danger
        }
    }
}

/// One MCP tool the OpenDesk app surfaces to the user for pre-approval.
/// `id` matches Claude Code's tool-naming convention so it can be passed
/// to `--allowedTools` / `--disallowedTools` directly.
struct MCPTool: Identifiable, Hashable {
    let id: String          // e.g. "mcp__opendesk__app"
    let key: String         // short key — "app"
    let name: String        // display name — "App"
    let blurb: String       // one-line description
    let icon: String        // SF Symbol
    let tint: Color
    let risk: Risk

    enum Risk: String { case low, medium, high
        var label: String {
            switch self { case .low: "low risk"; case .medium: "medium risk"; case .high: "high risk" }
        }
        var color: Color {
            switch self { case .low: Theme.mint; case .medium: Theme.amber; case .high: Theme.danger }
        }
    }
}

extension MCPTool {
    /// Every tool the bundled opendesk MCP server exposes.
    static let openDeskCatalog: [MCPTool] = [
        .init(id: "mcp__opendesk__screenshot", key: "screenshot",
              name: "Screenshot",
              blurb: "Capture the screen, optionally with Set-of-Marks numbering.",
              icon: "viewfinder", tint: Theme.brandStart, risk: .low),
        .init(id: "mcp__opendesk__ui",         key: "ui",
              name: "UI Control",
              blurb: "Click, type, read via the macOS accessibility tree.",
              icon: "cursorarrow.click.2", tint: Theme.brandEnd, risk: .medium),
        .init(id: "mcp__opendesk__mouse",      key: "mouse",
              name: "Mouse",
              blurb: "Move, click, double-click, drag, scroll.",
              icon: "computermouse.fill", tint: Theme.accent, risk: .medium),
        .init(id: "mcp__opendesk__keyboard",   key: "keyboard",
              name: "Keyboard",
              blurb: "Type Unicode text and any hotkey combo.",
              icon: "keyboard.fill", tint: Theme.mint, risk: .medium),
        .init(id: "mcp__opendesk__app",        key: "app",
              name: "App",
              blurb: "Open, close, focus or list desktop applications.",
              icon: "app.gift.fill", tint: Theme.amber, risk: .medium),
        .init(id: "mcp__opendesk__clipboard",  key: "clipboard",
              name: "Clipboard",
              blurb: "Read or write the system pasteboard.",
              icon: "doc.on.clipboard.fill", tint: .cyan, risk: .high),
        .init(id: "mcp__opendesk__ocr",        key: "ocr",
              name: "OCR",
              blurb: "Extract text from any region of the screen.",
              icon: "text.viewfinder", tint: .indigo, risk: .low),
        .init(id: "mcp__opendesk__learn",      key: "learn",
              name: "Learn",
              blurb: "Record a workflow once, replay it later.",
              icon: "play.rectangle.on.rectangle.fill",
              tint: Theme.brandStart, risk: .medium),
        .init(id: "mcp__opendesk__schedule",   key: "schedule",
              name: "Schedule",
              blurb: "Run prompts or workflows on a cron schedule.",
              icon: "calendar.badge.clock", tint: Theme.amber, risk: .medium),
    ]
}
