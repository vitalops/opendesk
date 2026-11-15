import Foundation
import SwiftUI
import AppKit
import ApplicationServices
import CoreGraphics
import AVFoundation

@MainActor
final class PermissionsService: ObservableObject {

    struct Status: Identifiable {
        let id: String
        let name: String
        let description: String
        let granted: Bool
        let settingsURL: URL?
        let icon: String
    }

    @Published var statuses: [Status] = []

    var allGranted: Bool {
        !statuses.isEmpty && statuses.allSatisfy(\.granted)
    }

    func refresh() async {
        let acc = checkAccessibility()
        let scr = checkScreenRecording()
        let auto = checkAutomation()

        statuses = [
            Status(id: "accessibility",
                   name: "Accessibility",
                   description: "Required to control the mouse, keyboard and read the focused app's UI tree.",
                   granted: acc,
                   settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"),
                   icon: "hand.tap.fill"),
            Status(id: "screen",
                   name: "Screen Recording",
                   description: "Required to capture screenshots so Claude can see what's on your screen.",
                   granted: scr,
                   settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"),
                   icon: "rectangle.dashed.badge.record"),
            Status(id: "automation",
                   name: "AppleEvents / Automation",
                   description: "Used to query application accessibility trees via AppleScript.",
                   granted: auto,
                   settingsURL: URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation"),
                   icon: "applescript.fill"),
        ]
    }

    // MARK: Probes

    private func checkAccessibility() -> Bool {
        AXIsProcessTrusted()
    }

    /// CGPreflightScreenCaptureAccess is available since macOS 10.15 and reports the current state.
    private func checkScreenRecording() -> Bool {
        if #available(macOS 11.0, *) {
            return CGPreflightScreenCaptureAccess()
        }
        return true
    }

    /// AppleEvents/Automation has no clean public probe; we treat this as advisory.
    /// In practice the OS shows the prompt the first time the app sends an Apple event.
    private func checkAutomation() -> Bool {
        return true
    }

    // MARK: Triggers

    func requestAccessibility() {
        let opts: NSDictionary = [kAXTrustedCheckOptionPrompt.takeUnretainedValue(): true]
        _ = AXIsProcessTrustedWithOptions(opts)
    }

    func requestScreenRecording() {
        if #available(macOS 11.0, *) {
            _ = CGRequestScreenCaptureAccess()
        }
    }

    func open(_ url: URL) {
        NSWorkspace.shared.open(url)
    }
}
