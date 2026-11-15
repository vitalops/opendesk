import SwiftUI
import AppKit

/// Two-mode binary. When invoked with `--mcp`, run as a JSON-RPC MCP
/// server (used by Claude Code via the MCP config we write at chat time).
/// Otherwise launch the SwiftUI app. This keeps a single signed binary
/// so macOS Accessibility / Screen Recording grants on OpenDesk.app
/// cover both the chat UI *and* every tool call Claude makes through it.
@main
enum OpenDeskEntry {
    static func main() {
        let args = CommandLine.arguments
        if args.contains("--mcp") {
            NativeMCPServer.run()
        }
        OpenDeskApp.main()
    }
}

struct OpenDeskApp: App {
    @StateObject private var local = LocalAgentService.shared
    @StateObject private var settings    = SettingsStore()
    @StateObject private var bridge      = OpenDeskBridge.shared
    @StateObject private var permissions = PermissionsService()
    @StateObject private var claudeCode  = ClaudeCodeService()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        WindowGroup("OpenDesk") {
            RootView()
                .environmentObject(local)
                .environmentObject(settings)
                .environmentObject(bridge)
                .environmentObject(permissions)
                .environmentObject(claudeCode)
                .frame(minWidth: 1080, minHeight: 720)
                .task {
                    await permissions.refresh()

                    // Hand the services to the app delegate for shutdown cleanup.
                    AppDelegate.shared.bind(claudeCode: claudeCode, bridge: bridge)
                }
        }
        .windowStyle(.hiddenTitleBar)
        .windowToolbarStyle(.unified(showsTitle: false))
        .defaultSize(width: 1240, height: 820)
        .commands {
            SidebarCommands()
            CommandGroup(replacing: .newItem) {}
            CommandMenu("OpenDesk") {
                Button("Take Screenshot")     { NotificationCenter.default.post(name: .quickScreenshot, object: nil) }
                    .keyboardShortcut("s", modifiers: [.command, .shift])
                Button("New Chat")            { NotificationCenter.default.post(name: .newChat, object: nil) }
                    .keyboardShortcut("n", modifiers: .command)
                Divider()
                Button("Copy Session as Markdown") { NotificationCenter.default.post(name: .copySession, object: nil) }
                    .keyboardShortcut("c", modifiers: [.command, .shift])
                Button("Export Session…")          { NotificationCenter.default.post(name: .exportSession, object: nil) }
                    .keyboardShortcut("e", modifiers: [.command, .shift])
                Divider()
                Button("Stop Running Chat")   {
                    local.stop()
                    claudeCode.stop()
                    bridge.cancelAll()
                }
                .keyboardShortcut(".", modifiers: .command)
                .disabled(!local.running && !claudeCode.isRunning && bridge.inflightCount == 0)

                Button("Emergency Stop · Kill All OpenDesk Helpers") {
                    local.stop()
                    claudeCode.stop()
                    bridge.cancelAll()
                    let killed = EmergencyStop.killAllOpenDeskOrphans()
                    let alert = NSAlert()
                    alert.messageText = killed.isEmpty ? "No helpers found." : "Killed \(killed.count) helper process\(killed.count == 1 ? "" : "es")."
                    alert.informativeText = killed.isEmpty
                        ? "No leftover opendesk-mcp or opendesk_bridge processes were running."
                        : "PIDs: \(killed.map(String.init).joined(separator: ", "))"
                    alert.alertStyle = .informational
                    alert.runModal()
                }
                .keyboardShortcut(".", modifiers: [.command, .shift])
                Divider()
                Button("Open Settings…")      { NotificationCenter.default.post(name: .openSettings, object: nil) }
                    .keyboardShortcut(",", modifiers: .command)
            }
        }
    }
}

/// Owns the application-lifecycle cleanup: on quit, signal any in-flight
/// processes so they don't get orphaned with desktop control.
final class AppDelegate: NSObject, NSApplicationDelegate {
    static let shared = AppDelegate()

    private var claudeCode: ClaudeCodeService?
    private var bridge: OpenDeskBridge?

    override init() { super.init() }

    @MainActor
    func bind(claudeCode: ClaudeCodeService, bridge: OpenDeskBridge) {
        self.claudeCode = claudeCode
        self.bridge = bridge
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in
            LocalAgentService.shared.stop()
            self.claudeCode?.stop()
            self.bridge?.cancelAll()
            // Belt-and-suspenders sweep for anything still hanging on.
            _ = EmergencyStop.killAllOpenDeskOrphans()
        }
        // Give cancel() its 800ms grace window before the app actually exits.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) {
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ note: Notification) {
        _ = EmergencyStop.killAllOpenDeskOrphans()
    }
}

extension Notification.Name {
    static let quickScreenshot = Notification.Name("OpenDesk.quickScreenshot")
    static let newChat         = Notification.Name("OpenDesk.newChat")
    static let openSettings    = Notification.Name("OpenDesk.openSettings")
    static let copySession     = Notification.Name("OpenDesk.copySession")
    static let exportSession   = Notification.Name("OpenDesk.exportSession")
}
