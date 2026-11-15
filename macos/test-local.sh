#!/usr/bin/env bash
# Standalone checks also work with Command Line Tools, which omit XCTest.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TEST_BIN="$(mktemp -d)/local-agent-tests"
trap 'rm -rf "$(dirname "$TEST_BIN")"' EXIT
swiftc -parse-as-library \
  "$HERE/Sources/OpenDesk/Services/CancellableProcess.swift" \
  "$HERE/Sources/OpenDesk/Services/LocalAgentService.swift" \
  "$HERE/Tests/LocalAgentSmoke.swift" -o "$TEST_BIN"
"$TEST_BIN"
