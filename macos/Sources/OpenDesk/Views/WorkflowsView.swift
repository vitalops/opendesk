import SwiftUI

struct WorkflowsView: View {
    @EnvironmentObject var bridge: OpenDeskBridge

    @State private var procedures: [Procedure] = []
    @State private var newName = ""
    @State private var busy = false
    @State private var error: String?
    @State private var loaded = false

    struct Procedure: Identifiable, Hashable {
        let id: String   // file name without extension
        let name: String
        let path: String
        let steps: Int
        let created: Date?
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                recorder
                library
            }
            .padding(28)
        }
        .onAppear { Task { await loadProcedures() } }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Workflows").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("Teach OpenDesk a routine once — replay it whenever you (or Claude) want.")
                .font(.system(size: 13)).foregroundStyle(.secondary)
        }
    }

    private var recorder: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 9) {
                Image(systemName: "record.circle.fill")
                    .foregroundStyle(Theme.danger)
                Text("Record a new workflow").font(.system(size: 14, weight: .semibold))
                Spacer()
            }

            HStack(spacing: 10) {
                TextField("Workflow name (e.g. \"morning standup\")", text: $newName)
                    .textFieldStyle(.plain)
                    .font(.system(size: 13))
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(RoundedRectangle(cornerRadius: 10).fill(Color.primary.opacity(0.05)))

                Button {
                    Task { await startRecording() }
                } label: {
                    Label("Start Recording", systemImage: "record.circle")
                }
                .buttonStyle(.plain)
                .modifier(PrimaryButton())
                .disabled(busy || newName.trimmingCharacters(in: .whitespaces).isEmpty)
            }

            Text("Recording captures your clicks and keystrokes via the OpenDesk `learn` tool. Coordinates adapt to screen state on replay.")
                .font(.system(size: 12))
                .foregroundStyle(.secondary)

            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 12)).foregroundStyle(Theme.amber)
            }
        }
        .odCard()
    }

    private var library: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Library").font(.system(size: 15, weight: .semibold))
                Spacer()
                Button {
                    Task { await loadProcedures() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain).foregroundStyle(.secondary)
            }

            if !loaded {
                placeholderCard(icon: "hourglass", text: "Loading…")
            } else if procedures.isEmpty {
                placeholderCard(
                    icon: "rectangle.stack.badge.play",
                    text: "No workflows yet. Record one above, or run `opendesk learn` from the CLI."
                )
            } else {
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 260), spacing: 12)], spacing: 12) {
                    ForEach(procedures) { p in
                        procedureCard(p)
                    }
                }
            }
        }
    }

    private func procedureCard(_ p: Procedure) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                ZStack {
                    RoundedRectangle(cornerRadius: 9).fill(Theme.mint.opacity(0.18))
                        .frame(width: 32, height: 32)
                    Image(systemName: "play.fill").foregroundStyle(Theme.mint)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(p.name).font(.system(size: 13, weight: .semibold))
                    Text("\(p.steps) step\(p.steps == 1 ? "" : "s")")
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                }
                Spacer()
            }
            HStack {
                Button("Replay") { Task { await replay(p) } }
                    .buttonStyle(.plain).modifier(SecondaryButton())
                Spacer()
                Button {
                    NSWorkspace.shared.selectFile(p.path, inFileViewerRootedAtPath: "")
                } label: { Image(systemName: "folder.fill") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
            }
        }
        .odCard()
    }

    private func placeholderCard(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).font(.system(size: 18)).foregroundStyle(.secondary)
            Text(text).font(.system(size: 12)).foregroundStyle(.secondary)
            Spacer()
        }
        .odCard()
    }

    // MARK: Actions

    private func startRecording() async {
        busy = true; defer { busy = false }
        error = nil
        do {
            _ = try await bridge.run("learn", params: ["action": "start", "name": newName])
            newName = ""
            await loadProcedures()
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func replay(_ p: Procedure) async {
        busy = true; defer { busy = false }
        do {
            _ = try await bridge.run("learn", params: ["action": "replay", "name": p.name])
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func loadProcedures() async {
        loaded = false
        defer { loaded = true }
        // Read directly from ~/.opendesk/procedures (best-effort)
        let dir = NSString("~/.opendesk/procedures").expandingTildeInPath
        guard let urls = try? FileManager.default.contentsOfDirectory(
            at: URL(fileURLWithPath: dir),
            includingPropertiesForKeys: [.creationDateKey]) else {
            procedures = []
            return
        }
        procedures = urls
            .filter { $0.pathExtension == "json" }
            .map { url in
                let name = url.deletingPathExtension().lastPathComponent
                var steps = 0
                if let data = try? Data(contentsOf: url),
                   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let s = obj["steps"] as? [Any] {
                    steps = s.count
                }
                let created = (try? url.resourceValues(forKeys: [.creationDateKey]))?.creationDate
                return Procedure(id: name, name: name, path: url.path, steps: steps, created: created)
            }
            .sorted { ($0.created ?? .distantPast) > ($1.created ?? .distantPast) }
    }
}
