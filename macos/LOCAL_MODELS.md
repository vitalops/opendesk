# Local Models workspace

The app opens on **Local Models**. Select Qwen2.5 3B, Liquid LFM2.5 1.2B,
or Qwen3 1.7B, enter a task, and press **Run locally** (⌘Return). Example
buttons fill the composer; they do not execute until you press Run.

- **Desktop**, **Screen memory**, and **All tools** select the Python agent scope.
- **Allow actions** enables changes through the existing Python safety policy.
  The older cloud chat's approval preferences do not override that policy.
- **See screenshots** uses Liquid LFM2.5-VL 1.6B to observe images, then loads
  the selected text model to plan. Loading is sequential.
- **Stop** (⌘.) cancels the local process tree. Runs also have a five-minute
  deadline. Stopping cannot undo completed actions.
- Results and diagnostics stay in this app session; each run starts fresh.
  The existing OpenDesk tools may persist audit logs or memory as configured.

## Setup and build

Requires Apple Silicon, macOS 14+, Swift Command Line Tools and `uv`.

```sh
./macos/setup-local.sh
./macos/build.sh local
open macos/build/OpenDesk.app
```

Setup installs the editable Python source with local inference and memory extras
into `~/Library/Application Support/OpenDesk/local-venv`. It downloads the four
model repositories into the Hugging Face cache (several GB on a fresh setup).
The GUI uses cached models only (`HF_HUB_OFFLINE=1`). Keep the checkout in place;
this development build is not a self-contained, notarized distribution.
Runtime settings can override the Python executable and Python source directory.

macOS may require Accessibility and Screen Recording permission for desktop
operations. Use the Privacy & Security button in Runtime settings.

Memory capture is separate and is not enabled just by opening the app:

```sh
"$HOME/Library/Application Support/OpenDesk/local-venv/bin/opendesk" memory start
```

Then select Recall history in the app. Existing cloud chat remains a separate
workspace and still uses its configured Claude credentials. Local Models does
not call that service or fall back to it.

## Checks

```sh
./macos/test-local.sh
OPENDESK_LIVE_TEST=1 ./macos/test-local.sh
```

The standalone Swift runner works without XCTest. It checks result parsing,
stderr capture, offline configuration, malformed responses, and cancellation.
The optional live check uses cached Qwen2.5 3B and verifies an `app.list` call.
Run it when the app is idle to avoid loading two models on a small Mac.
