import SwiftUI
import AppKit

@main
enum OpenDeskEntry {
    static func main() {
        if CommandLine.arguments.contains("--mcp") { NativeMCPServer.run() }
        OpenDeskApp.main()
    }
}

struct OpenDeskApp: App {
    @StateObject private var assistant = LocalAgentService.shared
    @StateObject private var permissions = PermissionsService()
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    var body: some Scene {
        WindowGroup("OpenDesk") {
            RootView().environmentObject(assistant).environmentObject(permissions)
                .frame(minWidth: 900, minHeight: 680)
                .task { await permissions.refresh() }
        }
        .defaultSize(width: 1160, height: 820)
        .windowStyle(.hiddenTitleBar)
        .commands {
            CommandGroup(replacing: .newItem) {
                Button("My workspace") { NotificationCenter.default.post(name: .newChat, object: nil) }
                    .keyboardShortcut("n", modifiers: .command)
            }
            CommandMenu("OpenDesk") {
                Button("Stop") { assistant.stop() }.keyboardShortcut(".", modifiers: .command)
                    .disabled(!assistant.running)
                Button("Preferences…") { NotificationCenter.default.post(name: .openSettings, object: nil) }
                    .keyboardShortcut(",", modifiers: .command)
            }
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        Task { @MainActor in LocalAgentService.shared.stop() }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) { NSApp.reply(toApplicationShouldTerminate: true) }
        return .terminateLater
    }
}
extension Notification.Name {
    static let quickScreenshot = Notification.Name("OpenDesk.quickScreenshot")
    static let newChat = Notification.Name("OpenDesk.newChat")
    static let openSettings = Notification.Name("OpenDesk.openSettings")
    static let copySession = Notification.Name("OpenDesk.copySession")
    static let exportSession = Notification.Name("OpenDesk.exportSession")
}
