import SwiftUI

struct LocalModelsView: View {
    @EnvironmentObject var local: LocalAgentService
    @AppStorage("localPython") private var python = ""
    @AppStorage("localSource") private var source = ""
    @AppStorage("localModel") private var model = "mlx-community/Qwen2.5-3B-Instruct-4bit"
    @AppStorage("localScope") private var scope = "desktop"
    @State private var task = "List running applications."
    @State private var allowActions = false
    @State private var vision = false
    @State private var runtimeExpanded = false
    @State private var steps = 8

    private var runtime: String {
        python.isEmpty ? NSHomeDirectory() + "/Library/Application Support/OpenDesk/local-venv/bin/python" : python
    }
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                HStack {
                    SectionHeader("Local Models", subtitle: "Screen memory and computer use, powered by models on this Mac.")
                    Label("On device", systemImage: "desktopcomputer")
                        .font(.callout.weight(.medium)).foregroundStyle(Theme.mint)
                }
                VStack(alignment: .leading, spacing: 16) {
                    HStack {
                        Picker("Model", selection: $model) {
                            Text("Qwen2.5 3B · best in our tests").tag("mlx-community/Qwen2.5-3B-Instruct-4bit")
                            Text("Liquid LFM2.5 1.2B · smallest").tag("LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit")
                            Text("Qwen3 1.7B").tag("mlx-community/Qwen3-1.7B-4bit")
                        }
                        Picker("Tools", selection: $scope) {
                            Text("Desktop").tag("desktop")
                            Text("Screen memory").tag("memory")
                            Text("All tools").tag("all")
                        }.frame(width: 230)
                    }
                    HStack(spacing: 24) {
                        Toggle("See screenshots", isOn: $vision)
                        Toggle("Allow actions", isOn: $allowActions)
                        Stepper("\(steps) turns", value: $steps, in: 1...30).frame(width: 150)
                    }
                    Text(vision ? "Liquid’s vision model reads images; the selected model plans. They load one at a time." : "Text models read tool results, accessibility text and screen history. Enable vision for images.")
                        .font(.caption).foregroundStyle(.secondary)
                    if allowActions {
                        Text("Actions can change apps, files and settings within the selected tools. OpenDesk’s safety policy still applies.")
                            .font(.caption).foregroundStyle(Theme.amber)
                    }
                }.odCard().disabled(local.running)

                VStack(alignment: .leading, spacing: 12) {
                    Text("What would you like to try?").font(.headline)
                    HStack {
                        example("List apps", prompt: "List running applications.", actions: false, images: false)
                        example("Open Calculator", prompt: "Open Calculator, then list applications to verify it is running.", actions: true, images: false)
                        example("Describe screen", prompt: "Take a screenshot and name the foreground application you can see.", actions: false, images: true)
                        example("Recall history", prompt: "Show my recent screen memory and cite frame IDs.", actions: false, images: false, memory: true)
                    }.disabled(local.running)
                    TextEditor(text: $task).font(.body).frame(height: 85)
                        .padding(8).background(.background).clipShape(RoundedRectangle(cornerRadius: 8))
                        .disabled(local.running)
                    HStack {
                        if local.running { ProgressView().controlSize(.small) }
                        Text(local.status).foregroundStyle(local.failed ? Theme.amber : .secondary)
                        Spacer()
                        if local.running {
                            Button("Stop", systemImage: "stop.fill") { local.stop() }
                                .keyboardShortcut(".", modifiers: .command)
                        } else {
                            Button("Run locally", systemImage: "play.fill") { run() }
                                .buttonStyle(.borderedProminent).tint(Theme.brandStart)
                                .keyboardShortcut(.return, modifiers: .command)
                                .disabled(task.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }
                    Text("Each run starts fresh. Cached models only; no cloud fallback. Answers may be wrong—check the tool results.")
                        .font(.caption).foregroundStyle(.secondary)
                }.odCard()
                if !local.answer.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Label(local.failed ? "Run result" : "Answer", systemImage: local.failed ? "exclamationmark.circle" : "text.bubble")
                            .font(.headline)
                        Text(local.answer).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                        Button("Copy result") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(local.answer, forType: .string) }
                    }.odCard()
                }
                if !local.log.isEmpty {
                    DisclosureGroup("Tool activity and diagnostics") {
                        Text(local.log).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
                    }.odCard()
                }
                DisclosureGroup("Runtime settings", isExpanded: $runtimeExpanded) {
                    VStack(alignment: .leading, spacing: 12) {
                        TextField("Python executable", text: $python, prompt: Text(runtime))
                        TextField("Source directory (optional, path to python/)", text: $source)
                        Text("Run macos/setup-local.sh from the repository to install the runtime and cache the tested models. Screen memory recording is managed separately with opendesk memory start; recall needs recorded history.")
                            .font(.caption).foregroundStyle(.secondary)
                        Button("Open Privacy & Security") {
                            NSWorkspace.shared.open(URL(string: "x-apple.systempreferences:com.apple.preference.security")!)
                        }
                    }.padding(.top, 10)
                }.odCard().disabled(local.running)
            }.padding(28)
        }
    }
    private func example(_ title: String, prompt: String, actions: Bool, images: Bool, memory: Bool = false) -> some View {
        Button(title) { task = prompt; allowActions = actions; vision = images; scope = memory ? "memory" : "desktop" }
            .buttonStyle(.bordered)
    }
    private func run() {
        var args = ["agent", task, "--json", "--mode", scope, "--max-steps", String(steps)]
        if vision { args += ["--vision", "--planner-model", model] }
        else { args += ["--model", model] }
        if allowActions { args.append("--allow-actions") }
        Task { await local.run(python: runtime, source: source, arguments: args) }
    }
}
