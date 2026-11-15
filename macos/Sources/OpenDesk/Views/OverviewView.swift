import SwiftUI
import AppKit

struct OverviewView: View {
    @EnvironmentObject var settings:    SettingsStore
    @EnvironmentObject var bridge:      OpenDeskBridge
    @EnvironmentObject var permissions: PermissionsService
    @EnvironmentObject var claudeCode:  ClaudeCodeService

    @State private var lastShot: NSImage?
    @State private var shotBusy = false
    @State private var shotError: String?

    private let columns = [GridItem(.adaptive(minimum: 240), spacing: 16)]

    private var authReady: Bool {
        switch settings.authMode {
        case .subscription: return claudeCode.isInstalled && claudeCode.isAuthenticated
        case .apiKey:       return settings.hasAPIKey
        }
    }
    private var authLabel: String {
        switch settings.authMode {
        case .subscription:
            if !claudeCode.isInstalled  { return "Install needed" }
            if !claudeCode.isAuthenticated { return "Sign-in needed" }
            return "Claude Code ready"
        case .apiKey:
            return settings.hasAPIKey ? "API key set" : "API key needed"
        }
    }
    private var authIcon: String {
        settings.authMode == .subscription
            ? "person.crop.circle.badge.checkmark"
            : "key.fill"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                hero
                if !authReady { onboardingBanner }
                quickStats
                quickActions
                heroPreview
                featureGrid
            }
            .padding(28)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
    }

    // MARK: Onboarding banner

    private var onboardingBanner: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 11).fill(Theme.brandGradient)
                    .frame(width: 44, height: 44)
                Image(systemName: settings.authMode == .subscription ? "terminal.fill" : "key.fill")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(.white)
            }
            VStack(alignment: .leading, spacing: 4) {
                Text(settings.authMode == .subscription
                     ? "Finish setting up Claude Code"
                     : "Add your Anthropic API key")
                    .font(.system(size: 14, weight: .semibold))
                Text(settings.authMode == .subscription
                     ? "OpenDesk drives Claude Code so your Pro/Max subscription handles auth. No API key needed."
                     : "Drop in an sk-ant-… key. It lives in macOS Keychain, never in plain text.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: 520, alignment: .leading)
            }
            Spacer()
            Button {
                NotificationCenter.default.post(name: .openSettings, object: nil)
            } label: {
                Label("Open Setup", systemImage: "arrow.right")
            }
            .buttonStyle(.plain)
            .modifier(PrimaryButton())
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.brandStart.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Theme.brandStart.opacity(0.25)))
    }

    // MARK: Hero

    private var hero: some View {
        HStack(alignment: .top, spacing: 22) {
            VStack(alignment: .leading, spacing: 8) {
                Text("Welcome to OpenDesk.")
                    .font(.system(size: 30, weight: .bold, design: .rounded))
                Text("Give Claude eyes, hands and a keyboard on your Mac — locally, encrypted, and entirely under your control.")
                    .font(.system(size: 14))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: 540, alignment: .leading)
                HStack(spacing: 10) {
                    Button { NotificationCenter.default.post(name: .newChat, object: nil) } label: {
                        Label("Start a Chat", systemImage: "sparkles")
                    }
                    .buttonStyle(.plain)
                    .modifier(PrimaryButton())

                    Button { NotificationCenter.default.post(name: .openSettings, object: nil) } label: {
                        Label(authReady ? "Settings" : "Finish Setup",
                              systemImage: authReady ? "gearshape" : "checkmark.circle.fill")
                    }
                    .buttonStyle(.plain)
                    .modifier(SecondaryButton())
                }
                .padding(.top, 6)
            }
            Spacer(minLength: 0)
            heroBadge
        }
    }

    private var heroBadge: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 22, style: .continuous)
                .fill(Theme.brandGradient)
                .frame(width: 156, height: 156)
                .shadow(color: Theme.brandStart.opacity(0.35), radius: 28, y: 14)
            VStack(spacing: 4) {
                Image(systemName: "command.square.fill")
                    .font(.system(size: 56, weight: .bold))
                    .foregroundStyle(.white)
                    .symbolRenderingMode(.hierarchical)
                Text("OpenDesk")
                    .font(.system(size: 14, weight: .semibold, design: .rounded))
                    .foregroundStyle(.white.opacity(0.95))
            }
        }
    }

    // MARK: Quick stats

    private var quickStats: some View {
        HStack(spacing: 14) {
            stat(settings.authMode.label,
                 value: authLabel,
                 icon: authIcon,
                 tint: authReady ? Theme.mint : Theme.amber)
            stat("Model",
                 value: settings.selectedModel.label,
                 icon: "cpu.fill",
                 tint: Theme.brandStart)
            stat("Permissions",
                 value: "\(permissions.statuses.filter(\.granted).count)/\(max(permissions.statuses.count,1))",
                 icon: "lock.shield.fill",
                 tint: permissions.allGranted ? Theme.mint : Theme.amber)
            stat("Recent calls",
                 value: "\(bridge.auditTrail.count)",
                 icon: "list.bullet.rectangle.portrait.fill",
                 tint: Theme.accent)
        }
    }

    private func stat(_ title: String, value: String, icon: String, tint: Color) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 9, style: .continuous)
                    .fill(tint.opacity(0.18))
                    .frame(width: 34, height: 34)
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(tint)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(title)
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                Text(value)
                    .font(.system(size: 14, weight: .bold, design: .rounded))
            }
            Spacer()
        }
        .odCard(padding: 14)
    }

    // MARK: Quick actions

    private var quickActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Quick Actions")
                    .font(.system(size: 15, weight: .semibold))
                Spacer()
            }
            HStack(spacing: 12) {
                actionTile(title: "Screenshot",
                           subtitle: "Capture screen with marks",
                           icon: "rectangle.dashed.badge.record",
                           tint: Theme.brandStart) { Task { await takeShot() } }
                actionTile(title: "Open App",
                           subtitle: "Launch any installed app",
                           icon: "app.badge.fill",
                           tint: Theme.accent) {
                    NotificationCenter.default.post(name: Notification.Name("OpenDesk.openTools"), object: "app")
                }
                actionTile(title: "Read Clipboard",
                           subtitle: "What's on the pasteboard",
                           icon: "doc.on.clipboard.fill",
                           tint: Theme.mint) {
                    NotificationCenter.default.post(name: Notification.Name("OpenDesk.openTools"), object: "clipboard")
                }
                actionTile(title: "Audit Log",
                           subtitle: "What ran in this session",
                           icon: "clock.arrow.circlepath",
                           tint: Theme.amber) {
                    NotificationCenter.default.post(name: Notification.Name("OpenDesk.openAudit"), object: nil)
                }
            }
        }
    }

    private func actionTile(title: String, subtitle: String, icon: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 11, style: .continuous)
                        .fill(tint.opacity(0.18))
                        .frame(width: 40, height: 40)
                    Image(systemName: icon)
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(tint)
                }
                Text(title).font(.system(size: 14, weight: .semibold))
                Text(subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .odCard()
        }
        .buttonStyle(.plain)
    }

    // MARK: Live screenshot preview

    private var heroPreview: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Live View")
                    .font(.system(size: 15, weight: .semibold))
                Spacer()
                if shotBusy { ProgressView().controlSize(.small) }
                Button("Refresh") { Task { await takeShot() } }
                    .buttonStyle(.plain)
                    .modifier(SecondaryButton())
            }
            ZStack {
                if let img = lastShot {
                    Image(nsImage: img)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: .infinity, maxHeight: 360)
                        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                } else {
                    placeholder
                }
            }
            .odCard(padding: 10)

            if let err = shotError {
                Label(err, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 12))
                    .foregroundStyle(Theme.amber)
            }
        }
    }

    private var placeholder: some View {
        VStack(spacing: 10) {
            Image(systemName: "rectangle.dashed.badge.record")
                .font(.system(size: 32))
                .foregroundStyle(.secondary)
            Text("Tap Refresh to take your first screenshot.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, minHeight: 200)
    }

    private func takeShot() async {
        shotBusy = true
        shotError = nil
        defer { shotBusy = false }
        do {
            let (img, _) = try await bridge.screenshot(marks: settings.includeMarks)
            lastShot = img
        } catch {
            shotError = error.localizedDescription
        }
    }

    // MARK: Feature grid

    private var featureGrid: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Everything OpenDesk Can Do")
                .font(.system(size: 15, weight: .semibold))
            LazyVGrid(columns: columns, spacing: 12) {
                ForEach(Feature.all) { f in
                    featureCard(f)
                }
            }
        }
    }

    private func featureCard(_ f: Feature) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 9) {
                Image(systemName: f.icon)
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(f.tint)
                Text(f.name).font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            Text(f.blurb)
                .font(.system(size: 11.5))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .multilineTextAlignment(.leading)
        }
        .odCard(padding: 14)
    }
}

struct PrimaryButton: ViewModifier {
    func body(content: Content) -> some View { content.odPrimaryButton() }
}
struct SecondaryButton: ViewModifier {
    func body(content: Content) -> some View { content.odSecondaryButton() }
}

struct Feature: Identifiable {
    let id = UUID()
    let name: String
    let blurb: String
    let icon: String
    let tint: Color

    static let all: [Feature] = [
        .init(name: "Screenshot", blurb: "Capture screen with numbered Set-of-Marks overlays.",
              icon: "viewfinder", tint: Theme.brandStart),
        .init(name: "UI Control", blurb: "Click/type via native accessibility — no pixel guessing.",
              icon: "cursorarrow.click.2", tint: Theme.brandEnd),
        .init(name: "Mouse", blurb: "Move, click, drag, scroll with precision.",
              icon: "computermouse.fill", tint: Theme.accent),
        .init(name: "Keyboard", blurb: "Type Unicode text and any hotkey combo.",
              icon: "keyboard.fill", tint: Theme.mint),
        .init(name: "App", blurb: "Open, close, focus or list desktop applications.",
              icon: "app.gift.fill", tint: Theme.amber),
        .init(name: "Clipboard", blurb: "Read and write the system pasteboard.",
              icon: "doc.on.clipboard.fill", tint: .cyan),
        .init(name: "OCR", blurb: "Extract text from any region of the screen.",
              icon: "text.viewfinder", tint: .indigo),
        .init(name: "Learn", blurb: "Record a workflow once, replay it forever.",
              icon: "play.rectangle.on.rectangle.fill", tint: Theme.brandStart),
        .init(name: "Schedule", blurb: "Run tasks on a timer or cron expression.",
              icon: "calendar.badge.clock", tint: Theme.amber),
        .init(name: "Remote Peers", blurb: "Drive other Macs on your LAN, end-to-end encrypted.",
              icon: "antenna.radiowaves.left.and.right", tint: .cyan),
        .init(name: "Audit", blurb: "A full record of every action taken.",
              icon: "list.bullet.rectangle.portrait.fill", tint: .gray),
        .init(name: "Computer Use", blurb: "Claude Opus 4.7 driving everything above.",
              icon: "sparkles.rectangle.stack.fill", tint: Theme.brandEnd),
    ]
}
