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
    @State private var preferences = false
    var body: some View {
        NavigationSplitView {
            VStack(alignment: .leading, spacing: 20) {
                Label("OpenDesk", systemImage: "square.grid.2x2.fill")
                    .font(.title2.bold()).padding(.bottom, 20)
                Button { preferences = false } label: { Label("My workspace", systemImage: "house") }
                Button { preferences = true } label: { Label("Preferences", systemImage: "slider.horizontal.3") }
                Spacer()
                Text("Make room for your work.").font(.caption).foregroundStyle(.secondary)
            }.buttonStyle(.plain).padding(24)
                .navigationSplitViewColumnWidth(min: 200, ideal: 220)
        } detail: {
            Group {
                if preferences { WorkspacePreferences() }
                else { LocalModelsView() }
            }
            .background(Theme.brandStart.opacity(0.035))
        }
        .onReceive(NotificationCenter.default.publisher(for: .openSettings)) { _ in preferences = true }
        .onReceive(NotificationCenter.default.publisher(for: .newChat)) { _ in preferences = false }
    }
}
