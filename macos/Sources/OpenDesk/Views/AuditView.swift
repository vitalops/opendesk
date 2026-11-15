import SwiftUI

struct AuditView: View {
    @EnvironmentObject var bridge: OpenDeskBridge
    @State private var query = ""

    private var filtered: [OpenDeskBridge.AuditEntry] {
        if query.trimmingCharacters(in: .whitespaces).isEmpty { return bridge.auditTrail }
        return bridge.auditTrail.filter {
            $0.tool.localizedCaseInsensitiveContains(query) ||
            $0.params.localizedCaseInsensitiveContains(query) ||
            $0.note.localizedCaseInsensitiveContains(query)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if filtered.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(filtered) { entry in row(entry) }
                    }
                    .padding(18)
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Activity").font(.system(size: 18, weight: .bold, design: .rounded))
                Text("Every tool invocation this session, with parameters.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Spacer()
            HStack(spacing: 7) {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("filter", text: $query)
                    .textFieldStyle(.plain).font(.system(size: 12))
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .frame(width: 220)
            .background(Capsule().fill(Color.primary.opacity(0.06)))
            .overlay(Capsule().strokeBorder(Color.primary.opacity(0.08)))

            Button { bridge.auditTrail.removeAll() } label: {
                Label("Clear", systemImage: "trash")
            }.buttonStyle(.plain).modifier(SecondaryButton())
        }
        .padding(.horizontal, 20).padding(.vertical, 14)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Image(systemName: "list.bullet.rectangle.portrait.fill")
                .font(.system(size: 36)).foregroundStyle(.secondary)
            Text("No activity yet.").font(.system(size: 14, weight: .semibold))
            Text("Run a tool or start a chat to see entries here.")
                .font(.system(size: 12)).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func row(_ e: OpenDeskBridge.AuditEntry) -> some View {
        HStack(alignment: .top, spacing: 12) {
            VStack {
                Circle()
                    .fill(e.ok ? Theme.mint : Theme.danger)
                    .frame(width: 8, height: 8)
                    .padding(.top, 7)
                Spacer()
            }
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(e.tool)
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .padding(.horizontal, 7).padding(.vertical, 2)
                        .background(Capsule().fill(Theme.brandStart.opacity(0.12)))
                        .foregroundStyle(Theme.brandStart)
                    Text(e.timestamp, style: .time)
                        .font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer()
                    if !e.ok {
                        Text("error").font(.system(size: 10, weight: .bold))
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(Theme.danger.opacity(0.18)))
                            .foregroundStyle(Theme.danger)
                    }
                }
                Text(e.params).font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .lineLimit(2).truncationMode(.middle)
                if !e.note.isEmpty {
                    Text(e.note).font(.system(size: 11)).foregroundStyle(Theme.danger)
                }
            }
            Spacer()
        }
        .odCard(padding: 12)
    }
}
