import SwiftUI

struct PeersView: View {
    @EnvironmentObject var bridge: OpenDeskBridge

    @State private var peers: [Peer] = []
    @State private var discovered: [Peer] = []
    @State private var error: String?
    @State private var pairingCode: String?
    @State private var busy = false
    @State private var pairHost = ""
    @State private var pairCode = ""
    @State private var pairName = ""

    struct Peer: Identifiable, Hashable {
        let id = UUID()
        let name: String
        let host: String?
        let connected: Bool
        let trusted: Bool
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                header
                actions
                trustedSection
                discoverSection
            }
            .padding(28)
        }
        .onAppear { Task { await refresh() } }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Remote Peers").font(.system(size: 24, weight: .bold, design: .rounded))
            Text("Pair with other OpenDesk machines on your LAN. Sessions are end-to-end encrypted (X25519 + ChaCha20-Poly1305).")
                .font(.system(size: 13)).foregroundStyle(.secondary)
        }
    }

    private var actions: some View {
        HStack(spacing: 12) {
            actionCard(title: "Generate pairing code",
                       subtitle: pairingCode ?? "Show a 6-digit code so another Mac can pair with this one.",
                       icon: "qrcode.viewfinder",
                       tint: Theme.brandStart) {
                Task { await beginPairing() }
            }
            actionCard(title: "Discover peers on LAN",
                       subtitle: "Scan for other OpenDesk Macs on this network.",
                       icon: "antenna.radiowaves.left.and.right",
                       tint: .cyan) {
                Task { await discover() }
            }
        }
    }

    private func actionCard(title: String, subtitle: String, icon: String, tint: Color, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: 11).fill(tint.opacity(0.18))
                        .frame(width: 42, height: 42)
                    Image(systemName: icon).foregroundStyle(tint)
                }
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.system(size: 13, weight: .semibold))
                    Text(subtitle).font(.system(size: 11)).foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Spacer()
            }
            .odCard()
        }
        .buttonStyle(.plain)
    }

    private var trustedSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Trusted peers").font(.system(size: 15, weight: .semibold))
            if peers.isEmpty {
                emptyRow("No trusted peers yet.")
            } else {
                ForEach(peers) { peerRow($0) }
            }
        }
    }

    private var discoverSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("On your LAN").font(.system(size: 15, weight: .semibold))
                Spacer()
                Button { Task { await discover() } } label: { Image(systemName: "arrow.clockwise") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
            }
            if discovered.isEmpty {
                emptyRow("No peers discovered. Click Discover to scan again.")
            } else {
                ForEach(discovered) { peerRow($0) }
            }
            pairForm
        }
    }

    private var pairForm: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                Image(systemName: "link").foregroundStyle(Theme.accent)
                Text("Pair with a discovered peer").font(.system(size: 13, weight: .semibold))
                Spacer()
            }
            HStack {
                TextField("host or IP", text: $pairHost).textFieldStyle(.plain).styledMonoField2()
                TextField("code (6 digits)", text: $pairCode).textFieldStyle(.plain).styledMonoField2()
                TextField("name", text: $pairName).textFieldStyle(.plain).styledMonoField2()
                Button {
                    Task { await pair() }
                } label: { Label("Pair", systemImage: "checkmark") }
                    .buttonStyle(.plain).modifier(PrimaryButton())
                    .disabled(pairHost.isEmpty || pairCode.isEmpty || pairName.isEmpty)
            }
            if let error {
                Label(error, systemImage: "exclamationmark.triangle.fill")
                    .font(.system(size: 12)).foregroundStyle(Theme.amber)
            }
        }
        .odCard()
    }

    private func peerRow(_ p: Peer) -> some View {
        HStack(spacing: 12) {
            ZStack {
                Circle().fill(p.connected ? Theme.mint.opacity(0.2) : .gray.opacity(0.15))
                    .frame(width: 32, height: 32)
                Image(systemName: p.connected ? "wifi" : "wifi.slash")
                    .foregroundStyle(p.connected ? Theme.mint : .secondary)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(p.name).font(.system(size: 13, weight: .semibold))
                if let host = p.host {
                    Text(host).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if p.trusted {
                Text("trusted").font(.system(size: 10, weight: .semibold))
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(Capsule().fill(Theme.mint.opacity(0.18)))
                    .foregroundStyle(Theme.mint)
            }
        }
        .odCard()
    }

    private func emptyRow(_ text: String) -> some View {
        HStack {
            Image(systemName: "tray").foregroundStyle(.secondary)
            Text(text).font(.system(size: 12)).foregroundStyle(.secondary)
            Spacer()
        }
        .odCard()
    }

    // MARK: Actions

    private func refresh() async {
        do {
            let resp = try await bridge.run("opendesk_peers", params: [:])
            if let arr = (resp.result as? [String: Any])?["peers"] as? [[String: Any]] {
                peers = arr.map { d in
                    Peer(name: (d["name"] as? String) ?? "?",
                         host: d["host"] as? String,
                         connected: (d["connected"] as? Bool) ?? false,
                         trusted: (d["trusted"] as? Bool) ?? true)
                }
            }
        } catch { self.error = error.localizedDescription }
    }

    private func discover() async {
        busy = true; defer { busy = false }
        do {
            let resp = try await bridge.run("opendesk_discover", params: [:])
            if let arr = (resp.result as? [String: Any])?["peers"] as? [[String: Any]] {
                discovered = arr.map { d in
                    Peer(name: (d["name"] as? String) ?? "?",
                         host: d["host"] as? String,
                         connected: (d["connected"] as? Bool) ?? false,
                         trusted: false)
                }
            }
        } catch { self.error = error.localizedDescription }
    }

    private func beginPairing() async {
        do {
            let resp = try await bridge.run("opendesk_pair_begin", params: [:])
            pairingCode = (resp.result as? [String: Any])?["code"] as? String
        } catch {
            // Fallback informative
            pairingCode = "Run `opendesk pair` in a terminal to print the 6-digit code."
        }
    }

    private func pair() async {
        do {
            _ = try await bridge.run("opendesk_pair_with", params: [
                "host": pairHost, "code": pairCode, "name": pairName
            ])
            pairHost = ""; pairCode = ""; pairName = ""
            await refresh()
        } catch { self.error = error.localizedDescription }
    }
}

private extension View {
    func styledMonoField2() -> some View {
        self
            .font(.system(size: 12, design: .monospaced))
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
    }
}
