import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var settings:    SettingsStore
    @EnvironmentObject var permissions: PermissionsService
    @EnvironmentObject var claudeCode:  ClaudeCodeService
    @EnvironmentObject var bridge:      OpenDeskBridge

    @State private var apiKeyDraft = ""
    @State private var apiKeyRevealed = false
    @State private var apiKeySaved = false
    @State private var probeMessage: String?
    @State private var probeOK: Bool = false
    @State private var controlTesting = false
    @State private var controlMessage: String?
    @State private var controlOK = false
    @State private var controlDetail = ""
    @State private var controlNeedsRelaunch = false
    @State private var relaunchError: String?
    @State private var tccResetReport: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                authModeSwitcher
                if settings.authMode == .subscription {
                    subscriptionSection
                } else {
                    apiKeySection
                }
                toolPermissionsSection
                modelSection
                loopSection
                permissionsSection
                helperBinarySection
                advancedSection
                aboutSection
            }
            .padding(28)
        }
        .onAppear { apiKeyDraft = settings.apiKey }
    }

    // MARK: Auth mode switcher

    private var authModeSwitcher: some View {
        section(title: "Sign-in method",
                subtitle: "Pick how OpenDesk talks to Claude.",
                icon: "person.crop.circle.fill.badge.checkmark",
                tint: Theme.brandStart) {
            HStack(spacing: 12) {
                ForEach(SettingsStore.AuthMode.allCases) { mode in
                    authModeCard(mode)
                }
            }
        }
    }

    private func authModeCard(_ mode: SettingsStore.AuthMode) -> some View {
        let selected = settings.authMode == mode
        return Button { settings.authMode = mode } label: {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Image(systemName: mode.icon).foregroundStyle(selected ? Theme.brandStart : .secondary)
                    Text(mode.label).font(.system(size: 13, weight: .semibold))
                    if mode == .subscription {
                        Text("Recommended")
                            .font(.system(size: 9, weight: .bold))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.brandStart.opacity(0.15)))
                            .foregroundStyle(Theme.brandStart)
                    }
                    Spacer()
                    Image(systemName: selected ? "largecircle.fill.circle" : "circle")
                        .foregroundStyle(selected ? Theme.brandStart : Color.primary.opacity(0.3))
                }
                Text(mode.blurb).font(.system(size: 11)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 12)
                .fill(selected ? Theme.brandStart.opacity(0.08) : Color.primary.opacity(0.03)))
            .overlay(RoundedRectangle(cornerRadius: 12)
                .strokeBorder(selected ? Theme.brandStart.opacity(0.35) : Color.primary.opacity(0.06)))
        }
        .buttonStyle(.plain)
    }

    // MARK: Subscription section

    private var subscriptionSection: some View {
        section(title: "Claude Code",
                subtitle: "OpenDesk drives Claude Code under the hood — your subscription handles auth and billing.",
                icon: "terminal.fill",
                tint: Theme.brandEnd) {
            VStack(alignment: .leading, spacing: 14) {
                stepRow(
                    number: 1,
                    title: "Install Claude Code",
                    done: claudeCode.isInstalled,
                    detail: claudeCode.isInstalled
                        ? "Detected at \(claudeCode.claudePath ?? "—") (\(claudeCode.claudeVersion ?? "version?"))"
                        : "Not detected on this Mac.",
                    action: claudeCode.isInstalled ? nil : "Install in Terminal",
                    onAction: { claudeCode.runInstallerInTerminal() }
                )
                stepRow(
                    number: 2,
                    title: "Sign in with your Claude account",
                    done: claudeCode.isAuthenticated,
                    detail: claudeCode.isAuthenticated
                        ? "Credentials detected. No API key needed."
                        : "Sign in with your Pro/Max plan via the Claude Code login flow.",
                    action: claudeCode.isAuthenticated ? "Re-sign in" : "Sign in",
                    onAction: { claudeCode.runLoginInTerminal() },
                    actionEnabled: claudeCode.isInstalled
                )
                stepRow(
                    number: 3,
                    title: "Test the connection",
                    done: probeOK,
                    detail: probeMessage ?? "Run a tiny probe to confirm OpenDesk can talk to Claude.",
                    action: claudeCode.isCheckingAuth ? "Checking…" : "Run probe",
                    onAction: { Task { await runProbe() } },
                    actionEnabled: claudeCode.isInstalled && !claudeCode.isCheckingAuth
                )
                if let probeMessage, !probeOK {
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "doc.text").foregroundStyle(.secondary)
                        ScrollView {
                            Text(probeMessage)
                                .font(.system(size: 11, design: .monospaced))
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .frame(maxHeight: 120)
                        Button {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(probeMessage, forType: .string)
                        } label: { Image(systemName: "doc.on.doc") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                    }
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
                }
                Divider().opacity(0.5)
                VStack(alignment: .leading, spacing: 6) {
                    Label("MCP runtime", systemImage: "gearshape.2.fill")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Text(MCPRegistration.describeRuntime())
                        .font(.system(size: 11, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
                }
                HStack {
                    Button {
                        Task { await claudeCode.refresh() }
                    } label: {
                        Label("Re-check status", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.plain).modifier(SecondaryButton())
                    Spacer()
                    Link("Claude Code docs ↗",
                         destination: URL(string: "https://docs.claude.com/en/docs/claude-code")!)
                        .font(.system(size: 11))
                }
            }
        }
    }

    private func stepRow(number: Int,
                         title: String,
                         done: Bool,
                         detail: String,
                         action: String?,
                         onAction: (() -> Void)? = nil,
                         actionEnabled: Bool = true) -> some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(done ? Theme.mint.opacity(0.18) : Theme.brandStart.opacity(0.18))
                    .frame(width: 30, height: 30)
                if done {
                    Image(systemName: "checkmark")
                        .font(.system(size: 13, weight: .bold))
                        .foregroundStyle(Theme.mint)
                } else {
                    Text("\(number)")
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundStyle(Theme.brandStart)
                }
            }
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.system(size: 13, weight: .semibold))
                Text(detail).font(.system(size: 11)).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)
            }
            Spacer()
            if let action, let onAction {
                Group {
                    if done {
                        Button(action: onAction) {
                            Text(action).font(.system(size: 12, weight: .semibold))
                        }
                        .buttonStyle(.plain)
                        .modifier(SecondaryButton())
                    } else {
                        Button(action: onAction) {
                            Text(action).font(.system(size: 12, weight: .semibold))
                        }
                        .buttonStyle(.plain)
                        .modifier(PrimaryButton())
                    }
                }
                .disabled(!actionEnabled)
            }
        }
        .padding(.vertical, 4)
    }

    private func runProbe() async {
        probeMessage = "Probing…"
        let r = await claudeCode.liveAuthProbe()
        switch r {
        case .success(let s):
            probeOK = true
            probeMessage = "OK — Claude replied: \(s.prefix(60))"
        case .failure(let e):
            probeOK = false
            probeMessage = "Failed: \(e.localizedDescription)"
        }
    }

    // MARK: Tool permissions

    private var toolPermissionsSection: some View {
        section(title: "Tool permissions",
                subtitle: "Pre-approve which MCP tools Claude may use without prompting each time.",
                icon: "checkmark.shield.fill",
                tint: Theme.mint) {
            VStack(alignment: .leading, spacing: 12) {
                yoloCard
                if settings.autoApprove { yoloOnBanner }
                toolPermissionsHeader
                    .disabled(settings.autoApprove)
                    .opacity(settings.autoApprove ? 0.4 : 1)
                Divider().opacity(0.5)
                VStack(spacing: 6) {
                    ForEach(MCPTool.openDeskCatalog) { tool in
                        toolPermissionRow(tool)
                            .disabled(settings.autoApprove)
                            .opacity(settings.autoApprove ? 0.35 : 1)
                    }
                }
                summaryLine
            }
        }
    }

    // MARK: Yolo (dangerously skip permissions)

    @State private var yoloConfirming = false

    private var yoloCard: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 11, style: .continuous)
                    .fill(settings.autoApprove
                          ? LinearGradient(colors: [Theme.danger, Theme.amber],
                                           startPoint: .topLeading, endPoint: .bottomTrailing)
                          : LinearGradient(colors: [Theme.danger.opacity(0.18),
                                                    Theme.danger.opacity(0.18)],
                                           startPoint: .top, endPoint: .bottom))
                    .frame(width: 44, height: 44)
                Image(systemName: settings.autoApprove ? "bolt.fill" : "exclamationmark.shield.fill")
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(settings.autoApprove ? .white : Theme.danger)
            }
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(settings.autoApprove ? "Yolo Mode is ON" : "Yolo Mode")
                        .font(.system(size: 14, weight: .bold, design: .rounded))
                        .foregroundStyle(settings.autoApprove ? Theme.danger : .primary)
                    Text("--dangerously-skip-permissions")
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(Color.primary.opacity(0.06)))
                        .foregroundStyle(.secondary)
                }
                Text(settings.autoApprove
                     ? "Every tool runs without a single prompt. Per-tool rules below are ignored."
                     : "Skip every permission prompt for OpenDesk MCP tools. The Claude Code subprocess runs with --dangerously-skip-permissions in the background. Convenient. Risky.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            Spacer(minLength: 12)
            Toggle("", isOn: Binding(
                get: { settings.autoApprove },
                set: { newValue in
                    if newValue {
                        yoloConfirming = true   // confirm before enabling
                    } else {
                        settings.autoApprove = false
                    }
                }
            ))
            .toggleStyle(.switch)
            .labelsHidden()
        }
        .padding(14)
        .background(RoundedRectangle(cornerRadius: 12)
            .fill(settings.autoApprove ? Theme.danger.opacity(0.10) : Color.primary.opacity(0.03)))
        .overlay(RoundedRectangle(cornerRadius: 12)
            .strokeBorder(Theme.danger.opacity(settings.autoApprove ? 0.55 : 0.22),
                          lineWidth: settings.autoApprove ? 1.5 : 1))
        .alert("Enable Yolo Mode?",
               isPresented: $yoloConfirming) {
            Button("Cancel", role: .cancel) { }
            Button("Enable", role: .destructive) { settings.autoApprove = true }
        } message: {
            Text("OpenDesk will pass --dangerously-skip-permissions to every Claude Code chat. Claude will be able to run any OpenDesk MCP tool — including app launch, mouse, keyboard and clipboard — with no further prompts. Only enable this when you fully trust the prompts you'll write.")
        }
    }

    private var yoloOnBanner: some View {
        HStack(spacing: 8) {
            Image(systemName: "bolt.shield.fill").foregroundStyle(Theme.danger)
            Text("Per-tool rules disabled while Yolo Mode is on.")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.danger)
            Spacer()
            Button("Turn off") { settings.autoApprove = false }
                .buttonStyle(.plain)
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(Theme.danger)
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 9).fill(Theme.danger.opacity(0.08)))
    }

    private var toolPermissionsHeader: some View {
        HStack(spacing: 8) {
            Button {
                settings.setPermissionForAllOpenDeskTools(.allow)
            } label: {
                Label("Allow all OpenDesk tools", systemImage: "checkmark.seal.fill")
            }
            .buttonStyle(.plain).modifier(PrimaryButton())

            Button {
                settings.setPermissionForAllOpenDeskTools(.deny)
            } label: {
                Label("Deny all", systemImage: "hand.raised.fill")
            }
            .buttonStyle(.plain).modifier(SecondaryButton())

            Button {
                settings.resetToolPermissions()
            } label: {
                Label("Reset to ask", systemImage: "arrow.uturn.backward")
            }
            .buttonStyle(.plain).modifier(SecondaryButton())
            Spacer()
        }
    }

    private func toolPermissionRow(_ tool: MCPTool) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 8).fill(tool.tint.opacity(0.18))
                    .frame(width: 30, height: 30)
                Image(systemName: tool.icon).foregroundStyle(tool.tint)
            }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 8) {
                    Text(tool.name).font(.system(size: 13, weight: .semibold))
                    Text(tool.risk.label)
                        .font(.system(size: 9, weight: .bold))
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(tool.risk.color.opacity(0.15)))
                        .foregroundStyle(tool.risk.color)
                    Text(tool.id)
                        .font(.system(size: 10, design: .monospaced))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                Text(tool.blurb).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 12)
            permissionPicker(for: tool.id)
        }
        .padding(.vertical, 4)
    }

    private func permissionPicker(for toolId: String) -> some View {
        let current = settings.permission(for: toolId)
        return HStack(spacing: 6) {
            ForEach(ToolPermission.allCases) { p in
                Button {
                    settings.setPermission(toolId, p)
                } label: {
                    HStack(spacing: 4) {
                        Image(systemName: p.icon).font(.system(size: 10, weight: .bold))
                        Text(p.label).font(.system(size: 11, weight: .semibold))
                    }
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(Capsule().fill(current == p ? p.tint.opacity(0.22) : Color.primary.opacity(0.04)))
                    .overlay(Capsule().strokeBorder(current == p ? p.tint.opacity(0.5) : Color.primary.opacity(0.08), lineWidth: 0.5))
                    .foregroundStyle(current == p ? p.tint : .secondary)
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var summaryLine: some View {
        HStack(spacing: 8) {
            Image(systemName: "info.circle").font(.system(size: 11)).foregroundStyle(.secondary)
            Text("\(settings.allowedToolIds.count) allowed · \(settings.disallowedToolIds.count) denied · \(MCPTool.openDeskCatalog.count - settings.allowedToolIds.count - settings.disallowedToolIds.count) will ask")
                .font(.system(size: 11)).foregroundStyle(.secondary)
            Spacer()
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Settings").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("Everything OpenDesk needs to operate.")
                .font(.system(size: 13)).foregroundStyle(.secondary)
        }
    }

    // MARK: API key

    private var apiKeySection: some View {
        section(title: "Anthropic API Key",
                subtitle: "Stored locally in macOS Keychain — never sent anywhere but Anthropic's API.",
                icon: "key.fill",
                tint: Theme.brandStart) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 8) {
                    Group {
                        if apiKeyRevealed {
                            TextField("sk-ant-...", text: $apiKeyDraft)
                        } else {
                            SecureField("sk-ant-...", text: $apiKeyDraft)
                        }
                    }
                    .textFieldStyle(.plain)
                    .font(.system(size: 12, design: .monospaced))
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: 9).fill(Color.primary.opacity(0.05)))

                    Button { apiKeyRevealed.toggle() } label: {
                        Image(systemName: apiKeyRevealed ? "eye.slash" : "eye")
                    }
                    .buttonStyle(.plain).foregroundStyle(.secondary)

                    Button {
                        settings.setAPIKey(apiKeyDraft)
                        apiKeySaved = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { apiKeySaved = false }
                    } label: {
                        Label(apiKeySaved ? "Saved" : "Save", systemImage: apiKeySaved ? "checkmark" : "lock.fill")
                    }
                    .buttonStyle(.plain).modifier(PrimaryButton())

                    if settings.hasAPIKey {
                        Button {
                            settings.setAPIKey("")
                            apiKeyDraft = ""
                        } label: { Image(systemName: "trash") }
                            .buttonStyle(.plain).foregroundStyle(Theme.danger)
                    }
                }
                HStack(spacing: 6) {
                    Circle()
                        .fill(settings.hasAPIKey ? Theme.mint : Theme.amber)
                        .frame(width: 8, height: 8)
                    Text(settings.hasAPIKey ? "Key is set." : "No key configured.")
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Link("Get one from console.anthropic.com →",
                         destination: URL(string: "https://console.anthropic.com/settings/keys")!)
                        .font(.system(size: 11))
                }
            }
        }
    }

    // MARK: Model

    private var modelSection: some View {
        section(title: "Model",
                subtitle: "Choose which Claude drives computer use.",
                icon: "cpu.fill",
                tint: Theme.brandEnd) {
            VStack(spacing: 10) {
                ForEach(SettingsStore.availableModels) { m in
                    modelRow(m)
                }
            }
        }
    }

    private func modelRow(_ m: SettingsStore.ModelOption) -> some View {
        Button { settings.modelId = m.id } label: {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .strokeBorder(settings.modelId == m.id ? Theme.brandStart : Color.primary.opacity(0.2),
                                      lineWidth: settings.modelId == m.id ? 5 : 1.2)
                        .frame(width: 16, height: 16)
                }
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text(m.label).font(.system(size: 13, weight: .semibold))
                        Text(m.tier)
                            .font(.system(size: 10, weight: .bold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(tier(m.tier)))
                        if m.recommended {
                            Text("Recommended").font(.system(size: 10, weight: .semibold))
                                .foregroundStyle(Theme.brandStart)
                                .padding(.horizontal, 6).padding(.vertical, 2)
                                .background(Capsule().fill(Theme.brandStart.opacity(0.15)))
                        }
                    }
                    Text(m.blurb).font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
                Text(m.id).font(.system(size: 10, design: .monospaced)).foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 10)
                .fill(settings.modelId == m.id ? Theme.brandStart.opacity(0.08) : Color.primary.opacity(0.03)))
            .overlay(RoundedRectangle(cornerRadius: 10)
                .strokeBorder(settings.modelId == m.id ? Theme.brandStart.opacity(0.3) : Color.primary.opacity(0.06)))
        }
        .buttonStyle(.plain)
    }

    private func tier(_ name: String) -> Color {
        switch name {
        case "Opus":   return Theme.brandStart
        case "Sonnet": return Theme.accent
        case "Haiku":  return Theme.mint
        default:       return .secondary
        }
    }

    // MARK: Loop

    private var loopSection: some View {
        section(title: "Computer-use loop",
                subtitle: "Behaviour when Claude is operating the computer.",
                icon: "arrow.triangle.2.circlepath",
                tint: Theme.accent) {
            VStack(alignment: .leading, spacing: 14) {
                HStack {
                    Text("Max steps per turn").font(.system(size: 12, weight: .medium))
                    Spacer()
                    Stepper("\(settings.maxLoopSteps)", value: $settings.maxLoopSteps, in: 5...100, step: 5)
                        .labelsHidden()
                    Text("\(settings.maxLoopSteps)").font(.system(size: 12, design: .monospaced)).frame(width: 30)
                }
                Toggle(isOn: $settings.includeMarks) {
                    VStack(alignment: .leading) {
                        Text("Set-of-Marks overlay on screenshots").font(.system(size: 12, weight: .medium))
                        Text("Numbers interactive elements 1–N so Claude can refer to them precisely.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
                .toggleStyle(.switch)
                Toggle(isOn: $settings.hideWhileRunning) {
                    VStack(alignment: .leading) {
                        Text("Hide OpenDesk window while Claude is running")
                            .font(.system(size: 12, weight: .medium))
                        Text("Stops OpenDesk's menu bar from intercepting ⌘N / ⌘S meant for Chrome, Safari, etc. The window comes back automatically when the run ends.")
                            .font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                }
                .toggleStyle(.switch)
            }
        }
    }

    // MARK: Permissions

    private var permissionsSection: some View {
        section(title: "Permissions",
                subtitle: "macOS privacy approvals OpenDesk needs to work.",
                icon: "lock.shield.fill",
                tint: permissions.allGranted ? Theme.mint : Theme.amber) {
            VStack(spacing: 10) {
                ForEach(permissions.statuses) { s in permissionRow(s) }
                HStack {
                    Spacer()
                    Button { Task { await permissions.refresh() } } label: {
                        Label("Re-check", systemImage: "arrow.clockwise")
                    }
                    .buttonStyle(.plain).modifier(SecondaryButton())
                }
            }
        }
    }

    private func permissionRow(_ s: PermissionsService.Status) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 9).fill((s.granted ? Theme.mint : Theme.amber).opacity(0.18))
                    .frame(width: 32, height: 32)
                Image(systemName: s.icon).foregroundStyle(s.granted ? Theme.mint : Theme.amber)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(s.name).font(.system(size: 13, weight: .semibold))
                Text(s.description).font(.system(size: 11)).foregroundStyle(.secondary)
                    .frame(maxWidth: 360, alignment: .leading)
            }
            Spacer()
            if s.granted {
                Label("Granted", systemImage: "checkmark.seal.fill")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Theme.mint)
            } else {
                Button {
                    if s.id == "accessibility" { permissions.requestAccessibility() }
                    else if s.id == "screen"   { permissions.requestScreenRecording() }
                    if let url = s.settingsURL { permissions.open(url) }
                } label: {
                    Text("Open System Settings").font(.system(size: 11, weight: .semibold))
                }
                .buttonStyle(.plain).modifier(SecondaryButton())
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: Helper Binary Permissions
    //
    // Background: macOS grants Accessibility to *binaries*, not to process
    // trees. OpenDesk.app's Accessibility grant doesn't carry over to the
    // Python interpreter that runs opendesk-mcp — the user must also add
    // that binary to Accessibility (System Settings → Privacy & Security
    // → Accessibility). Same for Terminal: it works because Terminal /
    // Python was already in that list from previous shell-driven sessions.

    private var helperBinarySection: some View {
        section(title: "Desktop control diagnostic",
                subtitle: "OpenDesk drives the mouse, keyboard and screen itself — no separate helper binary. One Accessibility grant in System Settings (above) covers everything.",
                icon: "checkmark.shield.fill",
                tint: Theme.mint) {
            VStack(alignment: .leading, spacing: 14) {
                testControlRow
                Divider().opacity(0.5)
                architectureNote
            }
        }
    }

    private var architectureNote: some View {
        VStack(alignment: .leading, spacing: 6) {
            Label("How tool calls actually reach your desktop", systemImage: "rectangle.connected.to.line.below")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
            Text("""
            Claude Code spawns OpenDesk itself as the MCP server (via `OpenDesk --mcp`). Every screenshot, mouse click and keystroke runs inside the same OpenDesk binary that has the Accessibility / Screen Recording grants you authorized above. No Python interpreter to grant separately, no symlinks to chase. This is the same pattern used by Karabiner, BetterTouchTool and Rectangle.
            """)
                .font(.system(size: 11))
                .foregroundStyle(.secondary)
        }
    }

    private var testControlRow: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9).fill((controlOK ? Theme.mint : Theme.amber).opacity(0.18))
                        .frame(width: 32, height: 32)
                    Image(systemName: controlOK ? "checkmark.seal.fill" : "computermouse.fill")
                        .foregroundStyle(controlOK ? Theme.mint : Theme.amber)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text("Test desktop control")
                        .font(.system(size: 13, weight: .semibold))
                    Text(controlMessage ?? "Moves the mouse a few hundred pixels and reads back to confirm input events are reaching macOS. Non-destructive.")
                        .font(.system(size: 11))
                        .foregroundStyle(controlOK ? Theme.mint : .secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                Spacer()
                Button {
                    Task { await runDesktopTest() }
                } label: {
                    HStack(spacing: 6) {
                        if controlTesting { ProgressView().controlSize(.small) }
                        Text(controlTesting ? "Testing…" : "Test now")
                    }
                }
                .buttonStyle(.plain).modifier(PrimaryButton())
                .disabled(controlTesting)
            }

            if controlNeedsRelaunch {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 10) {
                        Image(systemName: "arrow.triangle.2.circlepath.circle.fill")
                            .font(.system(size: 18))
                            .foregroundStyle(Theme.amber)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Restart required to apply Accessibility grant")
                                .font(.system(size: 12, weight: .semibold))
                            Text("This process started before you granted permission. macOS only refreshes TCC on launch.")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button {
                            relaunchError = NativeDesktopProbe.quitAndRelaunch()
                        } label: {
                            Label("Quit & Relaunch", systemImage: "power")
                        }
                        .buttonStyle(.plain).modifier(PrimaryButton())
                    }
                    if let relaunchError {
                        Text(relaunchError)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(Theme.danger)
                            .textSelection(.enabled)
                    }
                    // Second escape hatch for cdhash-mismatch TCC stalemate.
                    HStack(spacing: 10) {
                        Image(systemName: "arrow.uturn.backward.circle.fill")
                            .font(.system(size: 18))
                            .foregroundStyle(Theme.danger)
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Still not trusted after a clean restart?")
                                .font(.system(size: 12, weight: .semibold))
                            Text("Ad-hoc-signed dev builds change cdhash on every `./build.sh`. macOS silently denies the new cdhash even when the toggle looks ON. Resetting forces a fresh prompt.")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        Button {
                            tccResetReport = NativeDesktopProbe.resetTCCEntries()
                        } label: {
                            Label("Reset OpenDesk's TCC entries", systemImage: "trash")
                        }
                        .buttonStyle(.plain).modifier(SecondaryButton())
                    }
                    if let tccResetReport {
                        Text(tccResetReport)
                            .font(.system(size: 10, design: .monospaced))
                            .foregroundStyle(.secondary)
                            .textSelection(.enabled)
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: 6).fill(Color.primary.opacity(0.04)))
                    }
                }
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 10).fill(Theme.amber.opacity(0.10)))
                .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Theme.amber.opacity(0.35)))
            }

            if !controlDetail.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Label("Detail", systemImage: "text.alignleft")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.secondary)
                        Spacer()
                        Button {
                            let payload = """
                            Test desktop control — \(controlOK ? "OK" : "FAILED")
                            \(controlMessage ?? "")

                            Detail:
                            \(controlDetail)

                            Helper binary:   \(MCPRegistration.describeRuntime())
                            """
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(payload, forType: .string)
                        } label: {
                            Label("Copy diagnostic", systemImage: "doc.on.doc")
                                .font(.system(size: 11, weight: .semibold))
                        }
                        .buttonStyle(.plain).modifier(SecondaryButton())
                    }
                    ScrollView {
                        Text(controlDetail)
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.primary)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 180)
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.04)))
                    .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(Color.primary.opacity(0.06)))
                }
            }
        }
    }


    private func runDesktopTest() async {
        // Visible feedback FIRST so the user knows the click registered,
        // before any of the test work happens.
        controlMessage = "Running test…"
        controlDetail  = ""
        controlOK      = false
        controlNeedsRelaunch = false
        controlTesting = true
        defer { controlTesting = false }
        let r = await NativeDesktopProbe.runMouseTest()
        controlOK = r.ok
        controlNeedsRelaunch = false
        let bx = Int(r.before.x), by = Int(r.before.y)
        let ax = Int(r.after.x),  ay = Int(r.after.y)
        let tx = Int(r.target.x), ty = Int(r.target.y)

        if r.ok {
            controlMessage = "Desktop control works."
            controlDetail = """
            Mouse moved from (\(bx), \(by)) → (\(ax), \(ay)). Target was (\(tx), \(ty)).
            AXIsProcessTrusted: true
            Running binary: \(r.bundlePath)
            """
            return
        }

        if !r.trusted {
            // macOS doesn't see this process as authorised — either no grant
            // for THIS binary or the grant predates the running process.
            controlNeedsRelaunch = true
            controlMessage = "OpenDesk isn't trusted by macOS Accessibility yet."
            controlDetail = """
            AXIsProcessTrusted: false
            Running binary: \(r.bundlePath)
            Bundle id:      \(r.bundleId)

            Most likely cause — this process started BEFORE you granted Accessibility. macOS doesn't update TCC for already-running processes, so the grant won't take effect until OpenDesk is restarted.

            Click "Quit & Relaunch OpenDesk" below — it kills this process and reopens the same bundle 1 s later. Then come back here and click Test now.

            If the relaunch doesn't fix it:
              • Open System Settings → Privacy & Security → Accessibility.
              • Remove every entry whose path is NOT `\(r.bundlePath)` (you may have stale entries from the dev-build path).
              • Click "+", navigate to `\(r.bundlePath)`, add it, toggle ON.
              • Quit & Relaunch again.
            """
            return
        }

        // TCC says trusted but the cursor didn't move. Unusual.
        controlMessage = "Trusted by TCC but the cursor didn't move."
        controlDetail = """
        AXIsProcessTrusted: true   (so the permission grant is valid)
        Before: (\(bx), \(by))   After: (\(ax), \(ay))   Target: (\(tx), \(ty))
        Running binary: \(r.bundlePath)

        macOS reports OpenDesk is authorised, but the CGEventPost didn't move the cursor. Things to check:
          • Screen Time / parental controls blocking input synthesis.
          • A remote-desktop or screen-mirroring session that intercepts events.
          • The screen is locked or showing the login window.
          • A focus-mode or "Stage Manager" quirk on macOS 26.
        Try moving the mouse manually first, then re-run the test.
        """
    }

    // MARK: Advanced

    private var advancedSection: some View {
        section(title: "Advanced",
                subtitle: "Tell OpenDesk where to find your Python toolchain.",
                icon: "wrench.and.screwdriver.fill",
                tint: .gray) {
            VStack(alignment: .leading, spacing: 12) {
                pathField(title: "Python 3.10+ executable",
                          binding: $settings.pythonPath,
                          placeholder: "/Users/.../envs/py3.10/bin/python")
                pathField(title: "OpenDesk source root (optional)",
                          binding: $settings.opendeskSource,
                          placeholder: "/path/to/opendesk/python")
                Text("If left blank, OpenDesk will try `~/mambaforge/envs/py3.10/bin/python`, then Homebrew, then `/usr/bin/python3`.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }

    private func pathField(title: String, binding: Binding<String>, placeholder: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            HStack(spacing: 6) {
                TextField(placeholder, text: binding)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12, design: .monospaced))
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
                Button {
                    let p = NSOpenPanel()
                    p.allowsMultipleSelection = false
                    p.canChooseDirectories = title.contains("source")
                    p.canChooseFiles = !title.contains("source")
                    if p.runModal() == .OK, let url = p.url {
                        binding.wrappedValue = url.path
                    }
                } label: { Image(systemName: "folder.fill") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: About

    private var aboutSection: some View {
        section(title: "About",
                subtitle: "OpenDesk v0.2.0 — MIT licensed.",
                icon: "info.circle.fill",
                tint: .secondary) {
            VStack(alignment: .leading, spacing: 8) {
                Link("github.com/vitalops/opendesk", destination: URL(string: "https://github.com/vitalops/opendesk")!)
                    .font(.system(size: 12))
                Link("docs", destination: URL(string: "https://opendesk.vitalops.ai")!)
                    .font(.system(size: 12))
                Text("Built with Claude Opus 4.7.")
                    .font(.system(size: 11)).foregroundStyle(.secondary)
            }
        }
    }

    // MARK: Section helper

    @ViewBuilder
    private func section<C: View>(title: String, subtitle: String, icon: String, tint: Color, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9).fill(tint.opacity(0.18)).frame(width: 32, height: 32)
                    Image(systemName: icon).foregroundStyle(tint)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(title).font(.system(size: 14, weight: .semibold))
                    Text(subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
            }
            content()
        }
        .odCard()
    }
}
