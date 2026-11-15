import Foundation
import SwiftUI

@MainActor
final class SettingsStore: ObservableObject {

    enum AuthMode: String, CaseIterable, Identifiable {
        case subscription   // via Claude Code CLI + your Pro/Max plan
        case apiKey         // direct Anthropic API + your sk-ant-* key
        var id: String { rawValue }

        var label: String {
            switch self {
            case .subscription: "Claude Subscription"
            case .apiKey:       "API Key"
            }
        }
        var blurb: String {
            switch self {
            case .subscription: "Use your Claude Pro/Max/Team plan via the Claude Code CLI. No API key needed."
            case .apiKey:       "Direct Anthropic API calls. Brings your own sk-ant-… key. Per-token billing."
            }
        }
        var icon: String {
            switch self {
            case .subscription: "person.crop.circle.badge.checkmark"
            case .apiKey:       "key.fill"
            }
        }
    }

    // MARK: Models for the model picker

    struct ModelOption: Identifiable, Hashable {
        let id: String         // API id, e.g. "claude-opus-4-7"
        let label: String      // user-facing label
        let blurb: String      // one-line description
        let tier: String       // "Opus" / "Sonnet" / "Haiku"
        let recommended: Bool
    }

    /// Latest Claude 4.x models with computer-use support.
    static let availableModels: [ModelOption] = [
        .init(id: "claude-opus-4-7",
              label: "Opus 4.7",
              blurb: "Most capable. Best for complex multi-step tasks.",
              tier: "Opus",
              recommended: true),
        .init(id: "claude-sonnet-4-6",
              label: "Sonnet 4.6",
              blurb: "Great balance of speed, cost and capability.",
              tier: "Sonnet",
              recommended: false),
        .init(id: "claude-haiku-4-5-20251001",
              label: "Haiku 4.5",
              blurb: "Fastest and cheapest. Snappy for short tasks.",
              tier: "Haiku",
              recommended: false),
    ]

    // MARK: Defaults-backed values

    @AppStorage("authMode")          var authMode: AuthMode     = .subscription
    @AppStorage("modelId")           var modelId: String        = "claude-opus-4-7"
    @AppStorage("maxLoopSteps")      var maxLoopSteps: Int      = 25
    @AppStorage("includeMarks")      var includeMarks: Bool     = true
    @AppStorage("autoApprove")       var autoApprove: Bool      = false
    @AppStorage("hideWhileRunning")  var hideWhileRunning: Bool = true
    @AppStorage("pythonPath")        var pythonPath: String     = ""
    @AppStorage("opendeskSource")    var opendeskSource: String = ""
    @AppStorage("claudePath")        var claudePath: String     = ""

    // MARK: Keychain-backed key

    @Published var apiKey: String

    // MARK: Tool permissions (persisted as JSON in UserDefaults)

    @Published var toolPermissions: [String: ToolPermission] = [:]

    init() {
        self.apiKey = KeychainStore.get("anthropic_api_key") ?? ""
        self.toolPermissions = Self.loadToolPermissions()
    }

    private static let toolPermissionsKey = "toolPermissions"

    private static func loadToolPermissions() -> [String: ToolPermission] {
        guard let s = UserDefaults.standard.string(forKey: toolPermissionsKey),
              let d = s.data(using: .utf8),
              let dict = try? JSONDecoder().decode([String: ToolPermission].self, from: d) else {
            return [:]
        }
        return dict
    }

    private func saveToolPermissions() {
        if let d = try? JSONEncoder().encode(toolPermissions),
           let s = String(data: d, encoding: .utf8) {
            UserDefaults.standard.set(s, forKey: Self.toolPermissionsKey)
        }
    }

    func setPermission(_ toolId: String, _ permission: ToolPermission) {
        if permission == .ask {
            toolPermissions.removeValue(forKey: toolId)
        } else {
            toolPermissions[toolId] = permission
        }
        saveToolPermissions()
    }

    func permission(for toolId: String) -> ToolPermission {
        toolPermissions[toolId] ?? .ask
    }

    func setPermissionForAllOpenDeskTools(_ permission: ToolPermission) {
        for t in MCPTool.openDeskCatalog {
            if permission == .ask {
                toolPermissions.removeValue(forKey: t.id)
            } else {
                toolPermissions[t.id] = permission
            }
        }
        saveToolPermissions()
    }

    func resetToolPermissions() {
        toolPermissions.removeAll()
        saveToolPermissions()
    }

    var allowedToolIds: [String] {
        toolPermissions.filter { $0.value == .allow }.keys.sorted()
    }

    var disallowedToolIds: [String] {
        toolPermissions.filter { $0.value == .deny }.keys.sorted()
    }

    var hasAnyAllowedTool: Bool { !allowedToolIds.isEmpty }

    var hasAPIKey: Bool { !apiKey.trimmingCharacters(in: .whitespaces).isEmpty }

    func setAPIKey(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        apiKey = trimmed
        if trimmed.isEmpty {
            KeychainStore.remove("anthropic_api_key")
        } else {
            KeychainStore.set(trimmed, for: "anthropic_api_key")
        }
    }

    var selectedModel: ModelOption {
        Self.availableModels.first(where: { $0.id == modelId }) ?? Self.availableModels[0]
    }
}
