import SwiftUI
import AppKit

struct ToolsView: View {
    @EnvironmentObject var bridge:   OpenDeskBridge
    @EnvironmentObject var settings: SettingsStore

    enum Tool: String, CaseIterable, Identifiable {
        case screenshot, mouse, keyboard, app, clipboard, ocr, ui
        var id: String { rawValue }
        var title: String {
            switch self {
            case .screenshot: "Screenshot"
            case .mouse:      "Mouse"
            case .keyboard:   "Keyboard"
            case .app:        "App"
            case .clipboard:  "Clipboard"
            case .ocr:        "OCR"
            case .ui:         "UI (Accessibility)"
            }
        }
        var icon: String {
            switch self {
            case .screenshot: "viewfinder"
            case .mouse:      "computermouse.fill"
            case .keyboard:   "keyboard.fill"
            case .app:        "app.gift.fill"
            case .clipboard:  "doc.on.clipboard.fill"
            case .ocr:        "text.viewfinder"
            case .ui:         "cursorarrow.click.2"
            }
        }
        var tint: Color {
            switch self {
            case .screenshot: Theme.brandStart
            case .mouse:      Theme.accent
            case .keyboard:   Theme.mint
            case .app:        Theme.amber
            case .clipboard:  .cyan
            case .ocr:        .indigo
            case .ui:         Theme.brandEnd
            }
        }
    }

    @State private var selected: Tool = .screenshot
    @State private var busy = false
    @State private var resultText = ""
    @State private var resultImage: NSImage?
    @State private var error: String?

    // Tool params
    @State private var includeMarks = true
    @State private var mouseAction = "click"
    @State private var mouseX = ""
    @State private var mouseY = ""
    @State private var mouseButton = "left"
    @State private var mouseClicks = "1"
    @State private var kbAction = "type"
    @State private var kbText = ""
    @State private var appAction = "open"
    @State private var appName = ""
    @State private var clipAction = "read"
    @State private var clipText = ""
    @State private var ocrRegion = ""
    @State private var uiAction = "click"
    @State private var uiApp = ""
    @State private var uiTitle = ""
    @State private var uiValue = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            HStack(spacing: 0) {
                toolPicker
                Divider()
                detail
            }
        }
        .onAppear {
            NotificationCenter.default.addObserver(
                forName: Notification.Name("OpenDesk.openTools"),
                object: nil, queue: .main) { note in
                    if let name = note.object as? String,
                       let t = Tool(rawValue: name) {
                        selected = t
                    }
                }
        }
    }

    // MARK: Header

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Tools").font(.system(size: 18, weight: .bold, design: .rounded))
                Text("Manually invoke any OpenDesk tool. Great for testing.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 20).padding(.vertical, 14)
    }

    private var toolPicker: some View {
        ScrollView {
            VStack(spacing: 4) {
                ForEach(Tool.allCases) { t in
                    Button {
                        selected = t
                        resetResult()
                    } label: {
                        HStack(spacing: 10) {
                            ZStack {
                                RoundedRectangle(cornerRadius: 7, style: .continuous)
                                    .fill(t.tint.opacity(selected == t ? 0.22 : 0.10))
                                    .frame(width: 26, height: 26)
                                Image(systemName: t.icon)
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(t.tint)
                            }
                            Text(t.title)
                                .font(.system(size: 13, weight: selected == t ? .semibold : .medium))
                            Spacer()
                        }
                        .padding(.horizontal, 11).padding(.vertical, 7)
                        .background(RoundedRectangle(cornerRadius: 8).fill(selected == t ? Color.primary.opacity(0.06) : .clear))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(10)
        }
        .frame(width: 220)
        .background(.regularMaterial)
    }

    // MARK: Detail

    private var detail: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                paramsCard
                resultCard
            }
            .padding(20)
        }
    }

    private var paramsCard: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 9) {
                Image(systemName: selected.icon).foregroundStyle(selected.tint)
                Text(selected.title).font(.system(size: 14, weight: .semibold))
                Spacer()
                if busy {
                    Button {
                        bridge.cancelAll()
                    } label: {
                        Label("Cancel", systemImage: "stop.fill")
                            .foregroundStyle(.white)
                    }
                    .buttonStyle(.plain)
                    .padding(.horizontal, 14).padding(.vertical, 7)
                    .background(Capsule().fill(Theme.danger))
                    .shadow(color: Theme.danger.opacity(0.4), radius: 6, y: 2)
                }
                Button(action: { Task { await run() } }) {
                    HStack(spacing: 6) {
                        if busy { ProgressView().controlSize(.small) }
                        Text(busy ? "Running…" : "Run")
                    }
                }
                .buttonStyle(.plain)
                .modifier(PrimaryButton())
                .disabled(busy)
            }
            paramFields
        }
        .odCard()
    }

    @ViewBuilder
    private var paramFields: some View {
        switch selected {
        case .screenshot:
            Toggle("Include Set-of-Marks overlay", isOn: $includeMarks)
                .toggleStyle(.switch)
        case .mouse:
            HStack {
                picker("Action", selection: $mouseAction, options: ["click","move","down","up","scroll","drag","position"])
                picker("Button", selection: $mouseButton, options: ["left","right","middle"])
            }
            HStack {
                textField("X", value: $mouseX)
                textField("Y", value: $mouseY)
                textField("Clicks", value: $mouseClicks)
            }
        case .keyboard:
            picker("Action", selection: $kbAction, options: ["type","press","hotkey"])
            textField(kbAction == "type" ? "Text" : "Keys (e.g. cmd+c)", value: $kbText, multiline: kbAction == "type")
        case .app:
            picker("Action", selection: $appAction, options: ["open","close","focus","list"])
            if appAction != "list" {
                textField("App name", value: $appName)
            }
        case .clipboard:
            picker("Action", selection: $clipAction, options: ["read","write"])
            if clipAction == "write" {
                textField("Text", value: $clipText, multiline: true)
            }
        case .ocr:
            textField("Region: x,y,w,h (optional)", value: $ocrRegion)
        case .ui:
            picker("Action", selection: $uiAction, options: ["click","type","read","press"])
            HStack {
                textField("App", value: $uiApp)
                textField("Element title", value: $uiTitle)
            }
            if uiAction == "type" {
                textField("Value", value: $uiValue, multiline: true)
            }
        }
    }

    private func picker(_ label: String, selection: Binding<String>, options: [String]) -> some View {
        HStack(spacing: 6) {
            Text(label).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            Menu {
                ForEach(options, id: \.self) { opt in
                    Button(opt) { selection.wrappedValue = opt }
                }
            } label: {
                HStack(spacing: 4) {
                    Text(selection.wrappedValue)
                    Image(systemName: "chevron.down").font(.system(size: 9, weight: .bold))
                }
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(.primary)
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(Capsule().fill(Color.primary.opacity(0.06)))
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
    }

    private func textField(_ label: String, value: Binding<String>, multiline: Bool = false) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.system(size: 11, weight: .semibold)).foregroundStyle(.secondary)
            if multiline {
                TextEditor(text: value)
                    .font(.system(size: 12, design: .monospaced))
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 60)
                    .padding(6)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
            } else {
                TextField("", text: value)
                    .textFieldStyle(.plain)
                    .font(.system(size: 12, design: .monospaced))
                    .padding(.horizontal, 9).padding(.vertical, 7)
                    .background(RoundedRectangle(cornerRadius: 8).fill(Color.primary.opacity(0.05)))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: Result

    private var resultCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 7) {
                Image(systemName: "checkmark.bubble.fill")
                    .foregroundStyle(error == nil ? Theme.mint : Theme.danger)
                Text("Result").font(.system(size: 14, weight: .semibold))
                Spacer()
            }
            if let err = error {
                Text(err)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(Theme.danger)
                    .textSelection(.enabled)
            } else if let img = resultImage {
                Image(nsImage: img)
                    .resizable().scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else if !resultText.isEmpty {
                ScrollView {
                    Text(resultText)
                        .font(.system(size: 11.5, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .textSelection(.enabled)
                }
                .frame(maxHeight: 240)
            } else {
                Text("No result yet.")
                    .font(.system(size: 12)).foregroundStyle(.secondary)
            }
        }
        .odCard()
    }

    // MARK: Run

    private func resetResult() {
        resultText = ""; resultImage = nil; error = nil
    }

    private func run() async {
        busy = true; resetResult()
        defer { busy = false }
        do {
            let (tool, params) = buildRequest()
            let resp = try await bridge.run(tool, params: params)
            if let b64 = resp.imageB64, let d = Data(base64Encoded: b64), let img = NSImage(data: d) {
                resultImage = img
            }
            if let any = resp.result,
               let data = try? JSONSerialization.data(withJSONObject: any, options: [.prettyPrinted, .sortedKeys]),
               let s = String(data: data, encoding: .utf8) {
                resultText = s
            } else {
                resultText = "ok"
            }
        } catch {
            self.error = error.localizedDescription
        }
    }

    private func buildRequest() -> (String, [String: Any]) {
        switch selected {
        case .screenshot:
            return ("screenshot", ["marks": includeMarks])
        case .mouse:
            var p: [String: Any] = ["action": mouseAction]
            if let x = Int(mouseX) { p["x"] = x }
            if let y = Int(mouseY) { p["y"] = y }
            p["button"] = mouseButton
            if let c = Int(mouseClicks) { p["clicks"] = c }
            return ("mouse", p)
        case .keyboard:
            if kbAction == "type" { return ("keyboard", ["action": "type", "text": kbText]) }
            return ("keyboard", ["action": "hotkey", "keys": kbText])
        case .app:
            var p: [String: Any] = ["action": appAction]
            if !appName.isEmpty { p["name"] = appName }
            return ("app", p)
        case .clipboard:
            if clipAction == "read" { return ("clipboard", ["action": "read"]) }
            return ("clipboard", ["action": "write", "text": clipText])
        case .ocr:
            var p: [String: Any] = [:]
            let parts = ocrRegion.split(separator: ",").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            if parts.count == 4 { p["region"] = parts }
            return ("ocr", p)
        case .ui:
            var p: [String: Any] = ["action": uiAction, "app": uiApp, "title": uiTitle]
            if uiAction == "type" { p["value"] = uiValue }
            return ("ui", p)
        }
    }
}
