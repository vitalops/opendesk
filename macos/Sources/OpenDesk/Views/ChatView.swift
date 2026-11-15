import SwiftUI
import AppKit

struct ChatView: View {
    @EnvironmentObject var settings:    SettingsStore
    @EnvironmentObject var bridge:      OpenDeskBridge
    @EnvironmentObject var claudeCode:  ClaudeCodeService
    @StateObject private var claude  = ClaudeService()

    @State private var draft = ""
    @State private var steps: [ClaudeService.LoopStep] = []
    @State private var history: [[String: Any]] = []
    @State private var showInspector = true
    @State private var sessionID = UUID()
    @State private var copiedToastVisible = false
    @State private var copiedToastMessage = "Copied!"
    @FocusState private var inputFocused: Bool

    private var anyBusy: Bool { claude.isRunning || claudeCode.isRunning }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            HStack(spacing: 0) {
                transcript
                if showInspector {
                    Divider()
                    inspector
                        .frame(width: 320)
                        .transition(.move(edge: .trailing).combined(with: .opacity))
                }
            }
            Divider()
            composer
        }
        .onReceive(NotificationCenter.default.publisher(for: .copySession))   { _ in copySession() }
        .onReceive(NotificationCenter.default.publisher(for: .exportSession)) { _ in exportSession() }
        .overlay(alignment: .top) {
            if copiedToastVisible {
                HStack(spacing: 8) {
                    Image(systemName: "doc.on.doc.fill")
                        .font(.system(size: 12, weight: .bold))
                    Text(copiedToastMessage)
                        .font(.system(size: 12, weight: .semibold))
                }
                .padding(.horizontal, 14).padding(.vertical, 9)
                .foregroundStyle(.white)
                .background(Capsule().fill(Theme.mint))
                .shadow(color: Theme.mint.opacity(0.4), radius: 12, y: 4)
                .padding(.top, 60)
                .transition(.move(edge: .top).combined(with: .opacity))
                .animation(.easeOut(duration: 0.18), value: copiedToastVisible)
            }
        }
    }

    // MARK: Header

    @State private var confirmingYolo = false

    private var header: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Computer Use")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                Text("Claude can see your screen and operate it via OpenDesk.")
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
            Spacer()

            if anyBusy { stopPill }
            yoloPill
            modelPicker

            Button { copySession() } label: {
                Label("Copy", systemImage: "doc.on.doc")
            }
            .buttonStyle(.plain)
            .modifier(SecondaryButton())
            .help("Copy entire session as Markdown — screenshots written to /tmp (⌘⇧C)")
            .keyboardShortcut("c", modifiers: [.command, .shift])
            .disabled(steps.isEmpty)

            Button { exportSession() } label: {
                Label("Export", systemImage: "square.and.arrow.up")
            }
            .buttonStyle(.plain)
            .modifier(SecondaryButton())
            .help("Save chat + screenshots to a folder (⌘⇧E)")
            .keyboardShortcut("e", modifiers: [.command, .shift])
            .disabled(steps.isEmpty)

            Button {
                steps.removeAll()
                history.removeAll()
                sessionID = UUID()
            } label: {
                Label("New Chat", systemImage: "plus.message")
            }
            .buttonStyle(.plain)
            .modifier(SecondaryButton())

            Button {
                withAnimation(.easeOut(duration: 0.18)) { showInspector.toggle() }
            } label: {
                Image(systemName: "sidebar.right")
            }
            .buttonStyle(.plain)
            .modifier(SecondaryButton())
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 14)
        .alert("Enable Yolo Mode?",
               isPresented: $confirmingYolo) {
            Button("Cancel", role: .cancel) { }
            Button("Enable", role: .destructive) { settings.autoApprove = true }
        } message: {
            Text("Every chat will run claude with --dangerously-skip-permissions. Tool calls will execute without prompts. Continue?")
        }
    }

    private var stopPill: some View {
        Button { stop() } label: {
            HStack(spacing: 5) {
                Image(systemName: "stop.circle.fill")
                    .font(.system(size: 11, weight: .bold))
                Text("Stop")
                    .font(.system(size: 11, weight: .bold, design: .rounded))
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(Capsule().fill(Theme.danger))
            .foregroundStyle(.white)
            .shadow(color: Theme.danger.opacity(0.45), radius: 8, y: 3)
        }
        .buttonStyle(.plain)
        .help("Stop the running chat and kill opendesk-mcp (⌘.)")
    }

    private var yoloPill: some View {
        Button {
            if settings.autoApprove {
                settings.autoApprove = false
            } else {
                confirmingYolo = true
            }
        } label: {
            HStack(spacing: 5) {
                Image(systemName: settings.autoApprove ? "bolt.fill" : "bolt.shield")
                    .font(.system(size: 10, weight: .bold))
                Text(settings.autoApprove ? "YOLO ON" : "Yolo")
                    .font(.system(size: 11, weight: .bold, design: .rounded))
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(Capsule().fill(
                settings.autoApprove
                ? LinearGradient(colors: [Theme.danger, Theme.amber],
                                 startPoint: .leading, endPoint: .trailing)
                : LinearGradient(colors: [Color.primary.opacity(0.06), Color.primary.opacity(0.06)],
                                 startPoint: .top, endPoint: .bottom)))
            .overlay(Capsule().strokeBorder(
                settings.autoApprove ? .white.opacity(0.25) : Theme.danger.opacity(0.25),
                lineWidth: 0.6))
            .foregroundStyle(settings.autoApprove ? .white : Theme.danger)
            .shadow(color: settings.autoApprove ? Theme.danger.opacity(0.45) : .clear,
                    radius: 8, y: 3)
        }
        .buttonStyle(.plain)
        .help(settings.autoApprove
              ? "Yolo on — claude runs with --dangerously-skip-permissions. Click to turn off."
              : "Yolo off — pre-approved tools run silently, others prompt. Click to enable skip-all-permissions.")
    }

    private var modelPicker: some View {
        Menu {
            ForEach(SettingsStore.availableModels) { m in
                Button {
                    settings.modelId = m.id
                } label: {
                    HStack {
                        Text(m.label)
                        if m.recommended { Text("· Recommended").foregroundStyle(.secondary) }
                    }
                }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "cpu.fill")
                    .font(.system(size: 11, weight: .semibold))
                Text(settings.selectedModel.label)
                    .font(.system(size: 12, weight: .semibold))
                Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .background(Capsule().fill(Theme.brandStart.opacity(0.12)))
            .foregroundStyle(Theme.brandStart)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
    }

    // MARK: Transcript

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if steps.isEmpty { emptyState }
                    ForEach(steps) { step in
                        StepBubble(step: step).id(step.id)
                    }
                    if anyBusy {
                        HStack(spacing: 8) {
                            ProgressView().controlSize(.small)
                            Text("Claude is thinking…")
                                .font(.system(size: 12))
                                .foregroundStyle(.secondary)
                        }
                        .padding(.leading, 8)
                    }
                }
                .padding(20)
            }
            .background(Color.primary.opacity(0.02))
            .onChange(of: steps.count) { _, _ in
                if let last = steps.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(Theme.brandGradient)
                    .frame(width: 72, height: 72)
                    .shadow(color: Theme.brandStart.opacity(0.4), radius: 18, y: 8)
                Image(systemName: "sparkles")
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(.white)
            }
            Text("What should Claude do on your Mac?")
                .font(.system(size: 17, weight: .semibold, design: .rounded))
            Text("Try: \"Open Safari and search Anthropic\", or \"Read the latest unread Mail\".")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            if !isReady {
                Label(notReadyHint, systemImage: notReadyIcon)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Theme.amber)
                    .padding(.top, 6)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 80)
    }

    // MARK: Inspector

    private var inspector: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Inspector").font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 10)

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    inspectorBlock(title: "Last screenshot",
                                   icon: "rectangle.dashed.badge.record",
                                   tint: Theme.brandStart) {
                        if let b64 = steps.last(where: { $0.imageB64 != nil })?.imageB64,
                           let data = Data(base64Encoded: b64),
                           let img = NSImage(data: data) {
                            Image(nsImage: img)
                                .resizable()
                                .scaledToFit()
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        } else {
                            Text("No screenshot yet.").font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                    }
                    inspectorBlock(title: "Tool calls",
                                   icon: "hammer.fill",
                                   tint: Theme.accent) {
                        let calls = steps.filter { $0.kind == .tool }
                        if calls.isEmpty {
                            Text("None yet.").font(.system(size: 11)).foregroundStyle(.secondary)
                        } else {
                            VStack(alignment: .leading, spacing: 5) {
                                ForEach(calls.suffix(8)) { c in
                                    Text(c.detail)
                                        .font(.system(size: 11, design: .monospaced))
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                        .truncationMode(.middle)
                                }
                            }
                        }
                    }
                    inspectorBlock(title: "Conversation",
                                   icon: "text.bubble.fill",
                                   tint: Theme.brandEnd) {
                        VStack(alignment: .leading, spacing: 5) {
                            Text("\(history.count) message blocks")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                            Text("\(steps.count) loop steps")
                                .font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 20)
            }
        }
        .background(.regularMaterial)
    }

    @ViewBuilder
    private func inspectorBlock<C: View>(title: String, icon: String, tint: Color, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 7) {
                Image(systemName: icon).font(.system(size: 11, weight: .semibold)).foregroundStyle(tint)
                Text(title).font(.system(size: 11, weight: .semibold))
            }
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .odCard(padding: 12)
    }

    // MARK: Composer

    private var composer: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 10) {
                TextField("Ask Claude to do something on your Mac…  (Enter to send · Shift-Enter for newline)",
                          text: $draft, axis: .vertical)
                    .focused($inputFocused)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .lineLimit(1...6)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 11)
                    .background(RoundedRectangle(cornerRadius: 12).fill(Color.primary.opacity(0.05)))
                    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.primary.opacity(0.08)))
                    // Vertical TextField on macOS eats Return for newlines and
                    // doesn't reliably fire .onSubmit. Catch Return ourselves
                    // and let Shift-Return fall through as a newline.
                    .onKeyPress(.return) {
                        if NSEvent.modifierFlags.contains(.shift) { return .ignored }
                        if canSend { Task { await send() } }
                        return .handled
                    }
                    .onSubmit { Task { await send() } }

                if anyBusy {
                    Button {
                        stop()
                    } label: {
                        ZStack {
                            Circle().fill(Theme.danger).frame(width: 28, height: 28)
                                .shadow(color: Theme.danger.opacity(0.45), radius: 8, y: 3)
                            Image(systemName: "stop.fill")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(.white)
                        }
                    }
                    .buttonStyle(.plain)
                    .help("Stop the running chat (⌘.)")
                    .keyboardShortcut(".", modifiers: .command)
                } else {
                    Button {
                        Task { await send() }
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 24, weight: .bold))
                            .foregroundStyle(canSend ? Theme.brandStart : .secondary)
                    }
                    .buttonStyle(.plain)
                    .disabled(!canSend)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
        }
        .background(.regularMaterial)
        .onAppear { inputFocused = true }
    }

    private var isReady: Bool {
        switch settings.authMode {
        case .subscription: return claudeCode.isInstalled
        case .apiKey:       return settings.hasAPIKey
        }
    }

    private var notReadyHint: String {
        switch settings.authMode {
        case .subscription:
            return claudeCode.isInstalled
                ? "Sign in to Claude Code in Settings to enable chat."
                : "Install Claude Code from Settings → Sign-in method to enable chat."
        case .apiKey:
            return "Add an API key in Settings to start a chat."
        }
    }
    private var notReadyIcon: String {
        settings.authMode == .subscription ? "terminal.fill" : "key.fill"
    }

    private func stop() {
        claudeCode.stop()
        bridge.cancelAll()
        steps.append(.init(kind: .error, detail: "Stop requested — killing claude + opendesk-mcp…", imageB64: nil))
    }

    // MARK: Transcript export

    /// Build a Markdown document representing the whole chat (text,
    /// tool calls, errors, screenshots referenced by absolute path).
    /// Screenshots are written to `/tmp/opendesk-exports/<session>/`.
    private func transcriptMarkdown() -> (String, URL) {
        let sessionDir = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("opendesk-exports")
            .appendingPathComponent(sessionID.uuidString.prefix(8) + "")
        try? FileManager.default.createDirectory(at: sessionDir,
                                                 withIntermediateDirectories: true)

        var out: [String] = []
        let df = DateFormatter()
        df.dateFormat = "yyyy-MM-dd HH:mm:ss"

        out.append("# OpenDesk session — \(df.string(from: Date()))")
        out.append("")
        out.append("| | |")
        out.append("|---|---|")
        out.append("| Session ID | `\(sessionID.uuidString.prefix(8))` |")
        out.append("| Auth mode  | \(settings.authMode.label) |")
        out.append("| Model      | \(settings.selectedModel.label) (`\(settings.modelId)`) |")
        out.append("| Yolo       | \(settings.autoApprove ? "ON (--dangerously-skip-permissions)" : "off") |")
        out.append("| Allowed tools  | \(settings.allowedToolIds.isEmpty ? "—" : settings.allowedToolIds.joined(separator: ", ")) |")
        out.append("| Denied tools   | \(settings.disallowedToolIds.isEmpty ? "—" : settings.disallowedToolIds.joined(separator: ", ")) |")
        out.append("| Screenshots dir | `\(sessionDir.path)` |")
        out.append("")
        out.append("---")
        out.append("")

        var shotIdx = 0
        for step in steps {
            switch step.kind {
            case .thought:
                if step.detail.hasPrefix("🧑") {
                    let body = step.detail.dropFirst(1).trimmingCharacters(in: .whitespaces)
                    out.append("### 🧑 You")
                    out.append("")
                    out.append(body)
                } else {
                    out.append("### ✨ Claude")
                    out.append("")
                    out.append(step.detail)
                }
            case .tool:
                out.append("### 🔧 Tool call")
                out.append("")
                out.append("```")
                out.append(step.detail)
                out.append("```")
            case .observation:
                if let b64 = step.imageB64, let data = Data(base64Encoded: b64) {
                    shotIdx += 1
                    let path = sessionDir.appendingPathComponent("screenshot-\(shotIdx).png")
                    try? data.write(to: path)
                    out.append("### 👁 Screenshot \(shotIdx)")
                    out.append("")
                    out.append("![screenshot \(shotIdx)](\(path.path))")
                } else if !step.detail.isEmpty {
                    out.append("### 👁 Observation")
                    out.append("")
                    out.append(step.detail)
                }
            case .error:
                out.append("### ❌ Error")
                out.append("")
                let quoted = step.detail
                    .split(separator: "\n", omittingEmptySubsequences: false)
                    .map { "> " + $0 }
                    .joined(separator: "\n")
                out.append(quoted)
            case .done:
                out.append("### ✅ \(step.detail)")
            }
            out.append("")
        }

        // Audit trail (each opendesk tool call this session)
        if !bridge.auditTrail.isEmpty {
            out.append("---")
            out.append("")
            out.append("## OpenDesk audit trail (\(bridge.auditTrail.count) calls)")
            out.append("")
            for entry in bridge.auditTrail.reversed() {
                let status = entry.ok ? "OK" : "FAIL"
                out.append("- `\(df.string(from: entry.timestamp))` **\(entry.tool)** [\(status)] — `\(entry.params)`\(entry.note.isEmpty ? "" : " — \(entry.note)")")
            }
            out.append("")
        }

        return (out.joined(separator: "\n"), sessionDir)
    }

    private func copySession() {
        let (md, dir) = transcriptMarkdown()
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(md, forType: .string)
        let kb = md.utf8.count / 1024
        copiedToastMessage = "Copied \(kb)KB · screenshots in \(dir.lastPathComponent)"
        copiedToastVisible = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.8) { copiedToastVisible = false }
    }

    private func exportSession() {
        let panel = NSSavePanel()
        panel.title = "Export OpenDesk session"
        let df = DateFormatter(); df.dateFormat = "yyyyMMdd-HHmmss"
        panel.nameFieldStringValue = "opendesk-session-\(df.string(from: Date()))"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let folder = panel.url else { return }

        try? FileManager.default.createDirectory(at: folder,
                                                 withIntermediateDirectories: true)
        let (md, tmpDir) = transcriptMarkdown()
        // Rewrite the screenshot paths to point at the export folder instead of /tmp,
        // then copy the PNGs over.
        let target = folder.appendingPathComponent("screenshots")
        try? FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
        if let files = try? FileManager.default.contentsOfDirectory(at: tmpDir, includingPropertiesForKeys: nil) {
            for f in files where f.pathExtension == "png" {
                let dest = target.appendingPathComponent(f.lastPathComponent)
                try? FileManager.default.removeItem(at: dest)
                try? FileManager.default.copyItem(at: f, to: dest)
            }
        }
        let rewritten = md.replacingOccurrences(of: tmpDir.path, with: target.path)
        try? rewritten.data(using: .utf8)?
            .write(to: folder.appendingPathComponent("chat.md"))
        NSWorkspace.shared.activateFileViewerSelecting([folder])
    }

    private var canSend: Bool {
        !draft.trimmingCharacters(in: .whitespaces).isEmpty && isReady && !anyBusy
    }

    private func send() async {
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, isReady else { return }
        draft = ""
        steps.append(.init(kind: .thought, detail: "🧑  " + text, imageB64: nil))

        switch settings.authMode {
        case .subscription: await sendViaClaudeCode(text)
        case .apiKey:       await sendViaAPIKey(text)
        }
    }

    private func sendViaClaudeCode(_ text: String) async {
        // Always block these — they break the in-app loop:
        //   Bash               — not in the opendesk MCP allow-list; would just hit
        //                        a permission wall every time, wasting model turns.
        //   AskUserQuestion    — `claude -p` is non-interactive; the question is
        //                        rendered as text then times out with a stderr warning.
        let extraDeny = ["Bash", "AskUserQuestion"]
        let deny = (settings.disallowedToolIds + extraDeny).uniqued()

        // Get out of Claude's way so it can actually drive other apps.
        let hid = hideIfPolicy()
        defer { if hid { unhide() } }

        do {
            let mcpPath = try MCPRegistration.writeOpenDeskConfig()
            await claudeCode.chat(
                prompt: text,
                modelId: settings.modelId,
                mcpConfigPath: mcpPath,
                maxTurns: settings.maxLoopSteps,
                allowedTools: settings.allowedToolIds,
                disallowedTools: deny,
                bypassAllPermissions: settings.autoApprove
            ) { event in
                Task { @MainActor in self.appendClaudeCodeEvent(event) }
            }
        } catch {
            steps.append(.init(kind: .error, detail: error.localizedDescription, imageB64: nil))
        }
    }

    /// Send OpenDesk to the back so its menu bar (and `⌘N`/`⌘S` shortcuts)
    /// can't intercept input meant for the app Claude is operating.
    /// Returns true if we actually hid the window.
    private func hideIfPolicy() -> Bool {
        guard settings.hideWhileRunning else { return false }
        // Hide a touch later so the user sees the "Claude is thinking…" frame
        // before the window disappears.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
            NSApp.hide(nil)
        }
        return true
    }

    private func unhide() {
        // Bring OpenDesk back when the chat ends so the user sees results.
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) {
            NSApp.unhide(nil)
            NSApp.activate(ignoringOtherApps: true)
        }
    }

    private func appendClaudeCodeEvent(_ event: ClaudeCodeService.Event) {
        switch event {
        case .text(let t):
            steps.append(.init(kind: .thought, detail: t, imageB64: nil))
        case .toolUse(let name, let input):
            if isNoisyToolCall(name) { return }
            let desc = "\(name) \(prettyInput(input))"
            steps.append(.init(kind: .tool, detail: desc, imageB64: nil))
        case .toolResult(let text, let img):
            if let img {
                steps.append(.init(kind: .observation, detail: "Screen captured.", imageB64: img))
            }
            if !text.isEmpty {
                steps.append(.init(kind: .observation, detail: text, imageB64: nil))
            }
        case .error(let m):
            steps.append(.init(kind: .error, detail: m, imageB64: nil))
        case .done(let summary):
            steps.append(.init(kind: .done, detail: summary ?? "Done.", imageB64: nil))
        }
    }

    /// Filter noisy tool calls that the user doesn't need to see (Claude Code's
    /// internal `ToolSearch`, plus any non-opendesk MCP calls we'd rather not
    /// surface as observations).
    private func isNoisyToolCall(_ name: String) -> Bool {
        if name == "ToolSearch" { return true }
        return false
    }

    private func prettyInput(_ input: [String: Any]) -> String {
        guard !input.isEmpty,
              let data = try? JSONSerialization.data(withJSONObject: input, options: [.sortedKeys]),
              let s = String(data: data, encoding: .utf8) else { return "" }
        return s.count > 140 ? String(s.prefix(137)) + "…" : s
    }

    private func sendViaAPIKey(_ text: String) async {
        let screen = NSScreen.main?.frame.size ?? CGSize(width: 1920, height: 1080)
        history = await claude.sendTurn(
            apiKey: settings.apiKey,
            modelId: settings.modelId,
            userText: text,
            history: history,
            maxSteps: settings.maxLoopSteps,
            includeMarks: settings.includeMarks,
            bridge: bridge,
            screenSize: screen,
            onStep: { step in
                Task { @MainActor in steps.append(step) }
            }
        )
    }
}

// MARK: Bubble

struct StepBubble: View {
    let step: ClaudeService.LoopStep

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            iconBubble
            VStack(alignment: .leading, spacing: 6) {
                Text(step.detail)
                    .font(.system(size: 13))
                    .textSelection(.enabled)
                if let b64 = step.imageB64,
                   let data = Data(base64Encoded: b64),
                   let img = NSImage(data: data) {
                    Image(nsImage: img)
                        .resizable()
                        .scaledToFit()
                        .frame(maxWidth: 480)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.primary.opacity(0.08)))
                }
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 12).fill(bubbleColor))
            .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(strokeColor, lineWidth: 0.5))
            Spacer(minLength: 0)
        }
    }

    private var iconBubble: some View {
        ZStack {
            Circle().fill(iconTint.opacity(0.18)).frame(width: 28, height: 28)
            Image(systemName: iconName)
                .font(.system(size: 12, weight: .bold))
                .foregroundStyle(iconTint)
        }
    }

    private var iconName: String {
        switch step.kind {
        case .thought:     return "sparkles"
        case .tool:        return "hammer.fill"
        case .observation: return "eye.fill"
        case .error:       return "exclamationmark.triangle.fill"
        case .done:        return "checkmark.seal.fill"
        }
    }

    private var iconTint: Color {
        switch step.kind {
        case .thought:     return Theme.brandStart
        case .tool:        return Theme.accent
        case .observation: return Theme.mint
        case .error:       return Theme.danger
        case .done:        return Theme.mint
        }
    }

    private var bubbleColor: Color {
        switch step.kind {
        case .error: return Theme.danger.opacity(0.08)
        case .done:  return Theme.mint.opacity(0.08)
        default:     return Color.primary.opacity(0.04)
        }
    }

    private var strokeColor: Color { Color.primary.opacity(0.06) }
}
