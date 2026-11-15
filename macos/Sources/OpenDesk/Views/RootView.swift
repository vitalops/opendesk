import SwiftUI

enum AppSection: String, CaseIterable, Identifiable, Hashable {
    case local, overview, chat, tools, workflows, schedules, peers, audit, settings
    var id: String { rawValue }

    var title: String {
        switch self {
        case .local: "Local Models"
        case .overview:  "Overview"
        case .chat:      "Computer Use"
        case .tools:     "Tools"
        case .workflows: "Workflows"
        case .schedules: "Schedules"
        case .peers:     "Remote Peers"
        case .audit:     "Activity"
        case .settings:  "Settings"
        }
    }

    var systemImage: String {
        switch self {
        case .local: "cpu"
        case .overview:  "square.grid.2x2.fill"
        case .chat:      "sparkles.rectangle.stack.fill"
        case .tools:     "wand.and.rays"
        case .workflows: "rectangle.stack.badge.play.fill"
        case .schedules: "calendar.badge.clock"
        case .peers:     "antenna.radiowaves.left.and.right"
        case .audit:     "list.bullet.rectangle.portrait.fill"
        case .settings:  "gearshape.fill"
        }
    }

    var tint: Color {
        switch self {
        case .local: Theme.mint
        case .overview:  Theme.brandStart
        case .chat:      Theme.brandEnd
        case .tools:     Theme.accent
        case .workflows: Theme.mint
        case .schedules: Theme.amber
        case .peers:     .cyan
        case .audit:     .gray
        case .settings:  .secondary
        }
    }

    var blurb: String {
        switch self {
        case .local: "Try local models with screen memory and computer use."
        case .overview:  "At-a-glance status, permissions and quick actions."
        case .chat:      "Talk to Claude. It can see your screen and operate it."
        case .tools:     "Manually run every OpenDesk tool — great for debugging."
        case .workflows: "Record what you do once, replay it whenever."
        case .schedules: "Run any task or workflow on a timer."
        case .peers:     "Discover and pair with other OpenDesk machines on your LAN."
        case .audit:     "Every action OpenDesk has taken in this session."
        case .settings:  "API key, model, permissions, advanced options."
        }
    }
}

struct RootView: View {
    @State private var selection: AppSection? = .local
    @State private var sidebarVisibility: NavigationSplitViewVisibility = .all

    var body: some View {
        NavigationSplitView(columnVisibility: $sidebarVisibility) {
            Sidebar(selection: $selection)
                .navigationSplitViewColumnWidth(min: 220, ideal: 240, max: 280)
        } detail: {
            DetailContainer(selection: selection ?? .overview)
        }
        .navigationSplitViewStyle(.balanced)
        .onReceive(NotificationCenter.default.publisher(for: .newChat)) { _ in
            selection = .chat
        }
        .onReceive(NotificationCenter.default.publisher(for: .openSettings)) { _ in
            selection = .settings
        }
        .onReceive(NotificationCenter.default.publisher(for: .quickScreenshot)) { _ in
            selection = .tools
        }
    }
}

struct DetailContainer: View {
    let selection: AppSection

    var body: some View {
        ZStack {
            // Subtle ambient gradient background that picks up the brand color
            LinearGradient(
                colors: [
                    Theme.brandStart.opacity(0.08),
                    Color.clear,
                    Theme.accent.opacity(0.05)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            Group {
                switch selection {
                case .local: LocalModelsView()
                case .overview:  OverviewView()
                case .chat:      ChatView()
                case .tools:     ToolsView()
                case .workflows: WorkflowsView()
                case .schedules: SchedulesView()
                case .peers:     PeersView()
                case .audit:     AuditView()
                case .settings:  SettingsView()
                }
            }
            .transition(.opacity.combined(with: .move(edge: .trailing)))
            .animation(.easeOut(duration: 0.18), value: selection)
        }
    }
}
