# Local models: screen memory and computer use

`opendesk agent` runs a local text model that selects and executes OpenDesk
commands, reads results, and continues until it answers or reaches its step limit.
The initial backend uses MLX on Apple Silicon. The default is
`LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit`, approximately 628 MB of weights.

## Install and run

From this repository:

```sh
uv venv --python 3.11 .venv-memory
uv pip install --python .venv-memory/bin/python -e './python[local,memory]'
source .venv-memory/bin/activate
```

Model files download on first use. Inference runs on the Mac; captured text is
passed directly to the local model. Normal model-cache checks may use the
network; after downloading, set `HF_HUB_OFFLINE=1` to disable those checks.

Record history in a separate terminal, then ask questions:

```sh
opendesk memory start
# In another terminal:
opendesk agent 'Search screen memory for invoice today and report the matching moments'
opendesk agent 'Summarize my recent screen history using the timeline'
```

The agent queries the existing memory tools. It does not start recording by
itself. Use `--home PATH` on both commands for an isolated history store.

## Desktop mode

```sh
opendesk agent 'List the running applications' --mode desktop
opendesk agent 'Open Calculator and inspect its accessibility tree' --mode desktop --allow-actions
```

Desktop mode exposes application lists and accessibility-tree observations, in
addition to memory. `--allow-actions` enables opening/focusing applications,
accessibility clicks and typing, menu actions, and keyboard input. Calls execute
sequentially through OpenDesk's existing safety guard, policy, audit, and stop /
takeover controls. macOS Accessibility permission is required for UI operations.
The local model is text-only: it cannot interpret screenshot pixels. Apps with
poor accessibility support will be harder to control.

`--max-steps 8` is the default (range 1–30). Ctrl-C ends the agent. Each tool call
has a 60-second timeout. Each generation is limited to 512 tokens. The prompt
retains the original task and two recent command/result pairs; tool output is
truncated at 6,000 characters and memory queries return at most eight frames.
Use `--model` to choose another MLX-compatible text model.
Use `--tools app,ui` to restrict the available commands and reduce model confusion.

## Reliability and scope

This is an experimental Python CLI feature. Existing Python/JavaScript MCP tool
names and parameters are unchanged. MLX remains an optional dependency.

The model must return a validated JSON command; unknown tools, disabled actions,
and unsupported parameters are rejected before dispatch. Screen and memory text
are identified as untrusted data. This is not a guarantee against prompt
injection or incorrect actions. Generated answers and frame citations may be
wrong; inspect source frames with `opendesk memory show ID`.

On an 8 GB Apple Silicon Mac, the initial recall prototype used 0.77–1.35 GiB of
peak Metal allocations with short contexts (not total process/system memory).
The integrated agent has been tested on real memory search and application
listing. The 1.2B model can confuse tool names, omit arguments, or stop early;
the broad open-and-inspect desktop task did not complete in live testing.
Complex autonomous workflows are not validated. Errors are returned to the
model for bounded correction. Reaching the step limit exits unsuccessfully
rather than claiming completion.

Liquid model details: https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit
