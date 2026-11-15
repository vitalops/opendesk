import Foundation

func check(_ value: Bool, _ message: String = "Assertion failed") {
    precondition(value, message)
}

@main
struct LocalAgentSmoke {
    @MainActor static func main() async throws {
        let tests = LocalAgentSmoke()
        try await tests.testLocalProcessResultAndDiagnostics()
        try await tests.testMalformedResultIsFailure()
        try await tests.testStopCancelsChild()
        try await tests.testRealLocalModelWhenRequested()
        print("Local app service checks passed")
    }
    @MainActor
    private func fixture(_ code: String) throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let package = root.appendingPathComponent("opendesk")
        try FileManager.default.createDirectory(at: package, withIntermediateDirectories: true)
        try "".write(to: package.appendingPathComponent("__init__.py"), atomically: true, encoding: .utf8)
        try code.write(to: package.appendingPathComponent("cli.py"), atomically: true, encoding: .utf8)
        return root
    }
    @MainActor
    func testLocalProcessResultAndDiagnostics() async throws {
        let root = try fixture("import json,sys,os\nprint('Step 1: app.list', file=sys.stderr)\nprint(json.dumps({'output': os.environ['HF_HUB_OFFLINE'], 'error':False}))")
        defer { try? FileManager.default.removeItem(at: root) }
        let service = LocalAgentService()
        await service.run(python: "/usr/bin/python3", source: root.path, arguments: ["agent", "test"])
        check(service.answer == "1")
        check(service.log.contains("app.list"))
        check(!service.running)
        check(!service.failed)
    }
    @MainActor
    func testMalformedResultIsFailure() async throws {
        let root = try fixture("print('invalid response')")
        defer { try? FileManager.default.removeItem(at: root) }
        let service = LocalAgentService()
        await service.run(python: "/usr/bin/python3", source: root.path, arguments: [])
        check(service.failed)
    }
    @MainActor
    func testStopCancelsChild() async throws {
        let root = try fixture("import time\ntime.sleep(60)")
        defer { try? FileManager.default.removeItem(at: root) }
        let service = LocalAgentService()
        let run = Task { await service.run(python: "/usr/bin/python3", source: root.path, arguments: []) }
        try await Task.sleep(for: .milliseconds(300))
        service.stop()
        await run.value
        check(service.status == "Stopped")
        check(!service.running)
    }
    @MainActor
    func testRealLocalModelWhenRequested() async throws {
        guard ProcessInfo.processInfo.environment["OPENDESK_LIVE_TEST"] == "1" else {
            print("Skipping live model: set OPENDESK_LIVE_TEST=1 to enable"); return
        }
        let service = LocalAgentService()
        await service.run(python: NSHomeDirectory() + "/Library/Application Support/OpenDesk/local-venv/bin/python",
                          source: "", arguments: ["agent", "List running applications.", "--json", "--tools", "app", "--model", "mlx-community/Qwen2.5-3B-Instruct-4bit", "--max-steps", "4"])
        check(!service.failed, service.answer + service.log)
        check(service.log.contains("app.list"))
        check(!service.answer.isEmpty)
    }
}
