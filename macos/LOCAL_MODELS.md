# Workspace developer guide

The consumer UI is **My workspace**, with a task composer, folder chooser,
workflow suggestions, an explicit change toggle, answers and Stop. Preferences
contains native access controls. No model, provider, CLI or tool terminology is
exposed in navigation, menus or the task composer. Legacy cloud views remain in
source but are not reachable from the app shell and are not initialized at launch.

## Routing

The Swift service invokes `python -m opendesk.integrations.workspace`.

- Current folder-list questions read immediate filesystem children directly;
  they do not depend on screen history or inference. GitHub resolves to the
  existing Documents/GitHub or home GitHub folder. Downloads, Documents and
  Desktop names are supported; other locations use the folder chooser.
- Liquid LFM2.5 1.2B selects current screen, applications, past activity, or a
  general task for other requests. JSON-schema constraints bound this selection.
- Current screen help captures through the existing safety guard, then uses
  Liquid LFM2.5-VL 1.6B for a visual answer. The routing model is released first.
- App/general requests use the text agent. Past activity alone can use screen
  memory; an empty history produces an everyday explanation, not daemon commands.
- Changes remain opt-in, with the existing Python safety guard. File listing
  never runs shell commands, opens file contents, or recursively traverses folders.

This is a bounded initial workflow surface, not a general filesystem search or
file editing UI. Models can misroute requests or give inaccurate answers.
Screen help requires macOS permissions. History recording is not started
implicitly; file questions work without it. Each request starts fresh.

## Setup

Requires Apple Silicon, macOS 14+, Swift Command Line Tools and `uv`.

```sh
./macos/setup-local.sh
./macos/build.sh local
open macos/build/OpenDesk.app
```

Setup installs the editable Python package under
`~/Library/Application Support/OpenDesk/local-venv` and caches the two Liquid
models. GUI inference uses `HF_HUB_OFFLINE=1`. Keep this checkout in place: this
is a development bundle, not a self-contained notarized installer. The build
with `local` preserves any existing `/Applications/OpenDesk.app`.

## Checks

```sh
./macos/test-local.sh
python -m pytest python/tests/test_workspace.py -q
```

The Swift checks cover process results, errors, cancellation and offline mode.
Python checks cover filesystem reads without inference/history, path selection,
limits, past-file routing, empty history, and guarded screenshot observation.
Live checks used Liquid for application listing and screenshot description;
the exact GitHub-folder request was checked against the real directory.
