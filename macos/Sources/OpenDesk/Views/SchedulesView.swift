import SwiftUI

struct SchedulesView: View {
    @EnvironmentObject var bridge: OpenDeskBridge
    @State private var jobs: [Job] = []
    @State private var name = ""
    @State private var prompt = ""
    @State private var cron = "0 9 * * *"   // every day at 09:00
    @State private var error: String?
    @State private var busy = false

    struct Job: Identifiable, Hashable {
        let id = UUID()
        let name: String
        let cron: String
        let task: String
        let next: String?
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                creator
                list
            }
            .padding(28)
        }
        .onAppear { Task { await refresh() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Schedules").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("Run workflows, tasks or Claude prompts on a timer.")
                .font(.system(size: 13)).foregroundStyle(.secondary)
        }
    }

    private var creator: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 9) {
                Image(systemName: "calendar.badge.plus").foregroundStyle(Theme.amber)
                Text("New schedule").font(.system(size: 14, weight: .semibold))
                Spacer()
            }
            HStack(spacing: 10) {
                labelled("Name") { TextField("daily standup", text: $name).textFieldStyle(.plain).styledMonoField() }
                labelled("Cron") { TextField("0 9 * * *", text: $cron).textFieldStyle(.plain).styledMonoField() }
            }
            labelled("Task — a prompt for Claude or `<workflow:name>`") {
                TextField("Open Mail and summarize today's unread", text: $prompt)
                    .textFieldStyle(.plain).styledMonoField()
            }
            HStack {
                Spacer()
                Button {
                    Task { await add() }
                } label: {
                    Label("Schedule", systemImage: "plus")
                }
                .buttonStyle(.plain).modifier(PrimaryButton())
                .disabled(busy || name.isEmpty || prompt.isEmpty)
            }
            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 12)).foregroundStyle(Theme.amber)
            }
        }
        .odCard()
    }

    private var list: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Active jobs").font(.system(size: 15, weight: .semibold))
                Spacer()
                Button { Task { await refresh() } } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.plain).foregroundStyle(.secondary)
            }
            if jobs.isEmpty {
                HStack {
                    Image(systemName: "calendar").foregroundStyle(.secondary)
                    Text("No jobs scheduled yet.").font(.system(size: 12)).foregroundStyle(.secondary)
                    Spacer()
                }.odCard()
            } else {
                ForEach(jobs) { j in jobRow(j) }
            }
        }
    }

    private func jobRow(_ j: Job) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 9).fill(Theme.amber.opacity(0.18)).frame(width: 32, height: 32)
                Image(systemName: "clock.fill").foregroundStyle(Theme.amber)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(j.name).font(.system(size: 13, weight: .semibold))
                Text("\(j.cron)  ·  \(j.task)")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(1).truncationMode(.tail)
            }
            Spacer()
            if let next = j.next {
                Text(next).font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .background(Capsule().fill(Theme.amber.opacity(0.15)))
            }
            Button { Task { await remove(j) } } label: {
                Image(systemName: "trash")
            }.buttonStyle(.plain).foregroundStyle(Theme.danger)
        }
        .odCard()
    }

    @ViewBuilder
    private func labelled<C: View>(_ title: String, @ViewBuilder content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Actions

    private func add() async {
        busy = true; defer { busy = false }
        error = nil
        do {
            _ = try await bridge.run("schedule", params: [
                "action": "add",
                "name": name,
                "cron": cron,
                "task": prompt
            ])
            name = ""; prompt = ""
            await refresh()
        } catch { self.error = error.localizedDescription }
    }

    private func remove(_ j: Job) async {
        do {
            _ = try await bridge.run("schedule", params: ["action": "remove", "name": j.name])
            await refresh()
        } catch { self.error = error.localizedDescription }
    }

    private func refresh() async {
        do {
            let resp = try await bridge.run("schedule", params: ["action": "list"])
            guard let arr = (resp.result as? [String: Any])?["jobs"] as? [[String: Any]] else {
                jobs = []; return
            }
            jobs = arr.map { d in
                Job(name: (d["name"] as? String) ?? "",
                    cron: (d["cron"] as? String) ?? "",
                    task: (d["task"] as? String) ?? "",
                    next: d["next_run"] as? String)
            }
        } catch {
            // schedule extra may not be installed — silent fallback to empty
            jobs = []
        }
    }
}

private extension View {
    func styledMonoField() -> some View {
        self
            .font(.system(size: 12, design: .monospaced))
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
    }
}
