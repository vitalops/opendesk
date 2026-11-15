import SwiftUI

struct LocalModelsView: View {
    @EnvironmentObject var local: LocalAgentService
    @AppStorage("workFolder") private var folder = ""
    @State private var request = ""
    @State private var allowChanges = false
    private let suggestions = [
        ("folder", "Explore my files", "What are the files in my GitHub folder?"),
        ("rectangle.on.rectangle", "See what’s open", "List running applications."),
        ("sparkles", "Help with this screen", "Describe what is on my screen now."),
        ("clock", "Pick up where I left off", "What was I working on earlier?")
    ]
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("A little help with your day.").font(.system(size: 30, weight: .semibold, design: .rounded))
                    Text("Find your work, understand what’s in front of you, and take the next step.")
                        .foregroundStyle(.secondary)
                }.padding(.top, 12)
                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                    ForEach(suggestions, id: \.1) { item in
                        Button { request = item.2 } label: {
                            HStack(spacing: 12) {
                                Image(systemName: item.0).foregroundStyle(Theme.brandStart).font(.title2)
                                Text(item.1).font(.headline)
                                Spacer()
                                Image(systemName: "arrow.up.left").foregroundStyle(.tertiary)
                            }.frame(maxWidth: .infinity, minHeight: 44).odCard()
                        }.buttonStyle(.plain).disabled(local.running)
                    }
                }
                VStack(alignment: .leading, spacing: 14) {
                    Text("What would you like to get done?").font(.headline)
                    TextEditor(text: $request).font(.body).frame(height: 105).padding(8)
                        .background(.background).clipShape(RoundedRectangle(cornerRadius: 10))
                        .disabled(local.running)
                    HStack {
                        Button(action: chooseFolder) {
                            Label(folder.isEmpty ? "Choose folder" : URL(fileURLWithPath: folder).lastPathComponent, systemImage: "folder")
                        }.disabled(local.running).help(folder.isEmpty ? "Choose a folder to explore" : folder)
                        if !folder.isEmpty {
                            Button("Show in Finder") { NSWorkspace.shared.open(URL(fileURLWithPath: folder)) }
                        }
                        Spacer()
                        Toggle("Let OpenDesk make changes", isOn: $allowChanges).toggleStyle(.checkbox).disabled(local.running)
                    }
                    HStack {
                        if local.running { ProgressView().controlSize(.small) }
                        Text(local.status).font(.callout).foregroundStyle(.secondary)
                        Spacer()
                        if local.running {
                            Button("Stop", systemImage: "stop.fill") { local.stop() }
                        } else {
                            Button("Help me", systemImage: "arrow.up") { submit() }
                                .buttonStyle(.borderedProminent).tint(Theme.brandStart)
                                .keyboardShortcut(.return, modifiers: .command)
                                .disabled(request.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                    Text(allowChanges ? "OpenDesk can make changes for this request. You can stop at any time." : "OpenDesk will look things up without changing your files or apps.")
                        .font(.caption).foregroundStyle(.secondary)
                }.odCard()
                if !local.answer.isEmpty {
                    VStack(alignment: .leading, spacing: 14) {
                        Label(local.failed ? "Let’s try another way" : "Here’s what I found", systemImage: local.failed ? "arrow.turn.up.right" : "checkmark.circle")
                            .font(.headline)
                        Text(local.answer).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        Button("Copy") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(local.answer, forType: .string)
                        }
                    }.odCard()
                }
            }.padding(32).frame(maxWidth: 1000).frame(maxWidth: .infinity)
        }
    }
    private func chooseFolder() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.allowsMultipleSelection = false; panel.prompt = "Choose folder"
        if panel.runModal() == .OK, let url = panel.url { folder = url.path }
    }
    private func submit() {
        var arguments = [request]
        if !folder.isEmpty { arguments += ["--folder", folder] }
        if allowChanges { arguments.append("--allow-actions") }
        let python = NSHomeDirectory() + "/Library/Application Support/OpenDesk/local-venv/bin/python"
        Task { await local.run(python: python, source: "", arguments: arguments, module: "opendesk.integrations.workspace") }
    }
}

struct WorkspacePreferences: View {
    @EnvironmentObject var permissions: PermissionsService
    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            SectionHeader("Preferences", subtitle: "Choose what OpenDesk can help you with.")
            VStack(alignment: .leading, spacing: 16) {
                Text("Access to your Mac").font(.headline)
                Text("To help with what’s on your screen or work in your apps, OpenDesk needs your permission in macOS Settings.")
                Button("Allow help in my apps") { permissions.requestAccessibility() }
                Button("Allow viewing my screen") { permissions.requestScreenRecording() }
                Button("Open Privacy & Security") {
                    NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security")!)
                }
            }.odCard()
            VStack(alignment: .leading, spacing: 12) {
                Text("Your work stays on this Mac").font(.headline)
                Text("Opening OpenDesk does not start recording your screen. Questions about your folders work without saved activity.")
                Text("Each request starts fresh. Choose a folder to explore, or tell OpenDesk what you need help with.")
                    .foregroundStyle(.secondary)
            }.odCard()
            Spacer()
        }.padding(32)
    }
}
