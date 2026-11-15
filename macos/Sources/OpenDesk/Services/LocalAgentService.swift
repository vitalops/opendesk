import Foundation
import SwiftUI

/// Runs the packaged local agent directly, without a shell or cloud fallback.
@MainActor
final class LocalAgentService: ObservableObject {
    static let shared = LocalAgentService()
    @Published var running = false
    @Published var log = ""
    @Published var answer = ""
    @Published var status = "Ready"
    @Published var failed = false
    private var child: CancellableProcess?

    func stop() { child?.cancel() }

    func run(python: String, source: String, arguments: [String], module: String = "opendesk.cli") async {
        guard !running else { return }
        guard FileManager.default.isExecutableFile(atPath: python) else {
            failed = true; status = "Setup needed"
            answer = "OpenDesk needs its support files restored. Please run the setup included with the app and reopen it."
            return
        }
        running = true; failed = false; answer = ""; log = ""; status = "Getting ready…"
        let process = CancellableProcess()
        child = process
        let output = LocalOutputBuffer()
        let errors = LocalOutputBuffer()
        process.stdout.fileHandleForReading.readabilityHandler = { handle in output.append(handle.availableData) }
        process.stderr.fileHandleForReading.readabilityHandler = { handle in errors.append(handle.availableData) }
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONUNBUFFERED"] = "1"
        environment["HF_HUB_OFFLINE"] = "1"
        if !source.isEmpty { environment["PYTHONPATH"] = source }
        let monitor = Task { @MainActor in
            while !Task.isCancelled {
                self.log = errors.text
                if self.log.contains("Step ") { self.status = "Working on it…" }
                try? await Task.sleep(for: .milliseconds(200))
            }
        }
        // Independent deadline also covers a model that never yields a tool call.
        let deadline = Task {
            try? await Task.sleep(for: .seconds(300))
            if !Task.isCancelled { process.cancel() }
        }
        let outcome = await process.run(executable: URL(fileURLWithPath: python),
                                        arguments: ["-m", module] + arguments,
                                        environment: environment)
        monitor.cancel(); deadline.cancel()
        // Handlers stop on termination; drain remaining bytes only after a normal exit.
        if case .exited = outcome {
            output.append(process.stdout.fileHandleForReading.readDataToEndOfFile())
            errors.append(process.stderr.fileHandleForReading.readDataToEndOfFile())
        }
        log = errors.text
        switch outcome {
        case .cancelled:
            failed = true; status = "Stopped"; answer = "Run stopped (or reached the five-minute limit). Completed actions are not undone."
        case .spawnFailed(let error):
            failed = true; status = "Could not start"; answer = error.localizedDescription
        case .exited(let code):
            if let data = output.text.data(using: .utf8),
               let result = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let text = result["output"] as? String, let error = result["error"] as? Bool {
                answer = text; failed = error || code != 0
            } else {
                answer = "I could not complete that request. Please try again, or check access in Preferences."
                failed = true
            }
            status = failed ? "Needs attention" : "Finished"
        }
        child = nil; running = false
    }
}

/// Pipe callbacks run off the main actor. Bound retained text to 1 MiB.
final class LocalOutputBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    func append(_ bytes: Data) {
        lock.lock(); defer { lock.unlock() }
        data.append(bytes)
        if data.count > 1_048_576 { data.removeFirst(data.count - 1_048_576) }
    }
    var text: String {
        lock.lock(); defer { lock.unlock() }
        return String(decoding: data, as: UTF8.self)
    }
}
