# Local models across OpenDesk

OpenDesk's tools are model-independent. `opendesk agent` provides a local agent
loop over the **complete Python registry**, including screen memory, screenshots,
OCR, accessibility, mouse/keyboard, apps, clipboard, browser, scripts, learned
procedures, schedules, audit, and fleet operations. `opendesk-js agent` provides
the same local-server workflow over every tool in the JavaScript registry.

The model chooses commands; the existing tools perform the work. Local inference
support does not imply that every model can reliably complete every task.

## Apple Silicon: run directly with MLX

From this repository:

```sh
uv venv --python 3.11 .venv-memory
uv pip install --python .venv-memory/bin/python -e './python[local,memory]'
source .venv-memory/bin/activate

opendesk agent 'List running applications' --tools app
opendesk agent 'Open Calculator, then list apps to verify it is running' \
  --model mlx-community/Qwen2.5-3B-Instruct-4bit --tools app --allow-actions
```

The default model remains `LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit`. Models are
loaded once per invocation. MLX generation is constrained to the enabled tools'
JSON schemas; the dispatcher independently validates parameters before execution.
This prevents malformed command structures, not incorrect argument values or plans.

`--mode all` is the default. `--mode memory` limits tools to recall;
`--mode desktop` limits tools to desktop observations/input plus memory.
`--tools app,ui` further restricts the catalog and helps small models. For larger
catalogs, the agent can request a tool's full schema before invoking it.

Observation commands are enabled by default. `--allow-actions` enables all
registered actions within the selected scope, including scripts, destructive
operations, scheduling, and remote fleet dispatch. Every executed command still
passes through OpenDesk's safety policy, approval, audit, and stop/takeover guard.
Optional tool dependencies, native OS permissions, and remote pairing still apply.

## Local screen history

```sh
opendesk memory start --home /tmp/my-opendesk
# In another terminal:
opendesk agent 'Search screen memory for invoice today' \
  --mode memory --home /tmp/my-opendesk
```

The recorder remains a separate process. It already uses local accessibility/OCR;
no LLM is required for capturing and indexing history. The agent can also control
it through `memory_manage` when actions are enabled. Inspect source moments with
`opendesk memory show ID --home /tmp/my-opendesk`.

## Local screenshot vision

```sh
uv pip install --python .venv-memory/bin/python -e './python[local-vision]'
opendesk agent 'Take a screenshot and describe the visible application' \
  --vision --planner-model mlx-community/Qwen2.5-3B-Instruct-4bit --tools screenshot
```

`--vision` with MLX defaults to `mlx-community/LFM2.5-VL-1.6B-4bit`. It receives
actual image attachments from screenshots, browser captures, or memory recall.
The optional `--planner-model` uses the vision model to describe each image and
then loads the text planner. Models load sequentially to limit resident memory.
Direct vision-only planning is supported but failed our live completion test.
Text-only models receive tool text and an explicit image-omitted notice; use OCR
or accessibility observations with those models. Only the newest observation's
images are retained, at most two images of at most 8 MiB each.

## Local HTTP servers: Python and JavaScript

Start the built-in MLX bridge to share local inference with either SDK:

```sh
opendesk agent-server --model mlx-community/Qwen2.5-3B-Instruct-4bit --port 1234
```

Use `--structured` on the client with this bridge. It binds to loopback, handles
one inference request at a time, and executes no tools itself. Browser origins
are rejected. Clients execute the validated tool calls through their own guards.

Alternatively, use an OpenAI-compatible local server such as Ollama, LM Studio,
or llama.cpp; compatibility depends on its chat and structured-output support.
No OpenAI account or cloud API key is required. The model must be loaded in that
server; replace `YOUR_LOCAL_MODEL` with its model identifier.

```sh
opendesk agent 'List running applications' --backend http \
  --base-url http://127.0.0.1:1234/v1 --model YOUR_LOCAL_MODEL --tools app

opendesk-js agent 'List running applications' \
  --base-url http://127.0.0.1:1234/v1 --model YOUR_LOCAL_MODEL --tools app
```

Add `--vision` only for a vision-capable model/server. Add `--structured` to ask a
server that supports `response_format: json_schema` for constrained decoding.
Server support varies; command validation is always enforced by the runner.

Only loopback URLs are accepted and HTTP redirects are disabled. There is no
cloud fallback. The model server's own configuration determines its inference
behavior. Model downloads/cache checks may access the network; after downloading,
`HF_HUB_OFFLINE=1` disables Hugging Face network access for the MLX backends.

The JS SDK exports `LocalAgent` and `LocalHTTPBackend`. The Python SDK exposes
`LocalAgent` in `opendesk.integrations.local` and backend constructors in
`opendesk.integrations.local_backends`. Existing tool names and parameter schemas
are unchanged. Python-only tools such as learned workflows, scheduling, and fleet
remain Python-only; the JS agent exposes its existing 12-tool registry.

## Scheduled tasks and replay fallback

Select local inference for natural-language scheduled tasks and learned-procedure
fallbacks by setting these variables **when starting the scheduler**:

```sh
export OPENDESK_AGENT_BACKEND=local-mlx
export OPENDESK_MODEL=mlx-community/Qwen2.5-3B-Instruct-4bit
opendesk scheduler start
```

For a local server use `OPENDESK_AGENT_BACKEND=local-http` and
`OPENDESK_LOCAL_URL=http://127.0.0.1:1234/v1`. Set `OPENDESK_LOCAL_VISION=1` only
with a compatible model. Set `OPENDESK_LOCAL_STRUCTURED=1` for the built-in
bridge, and `OPENDESK_LOCAL_PLANNER` for hybrid MLX vision/planning. Existing compiled replays remain deterministic and
model-free. A local failure is returned as an error and never falls back to Claude.
Unset the variable (or select `cloud`) to retain the existing cloud behavior.

## Bounds and verification

The default is eight model turns, configurable with `--max-steps 1..30`. Each
model generation is limited to 512 tokens. The loop retains the task plus two
recent command/result pairs, truncates tool text to 6,000 characters, and limits
memory queries to eight frames. It requires a tool observation before accepting
a final answer. `--json` on the Python CLI returns the structured result.

Python tool calls have a 60-second timeout; local HTTP requests have a 120-second
timeout. Direct MLX inference is token-bounded, not wall-clock bounded. Scheduled
runs execute in a subprocess with a 300-second limit; evaluations use each task's
configured timeout. Killing inference cannot undo tool effects already performed.

Screen content and tool results are untrusted input. Schema validation and the
existing guard do not guarantee protection from prompt injection, factual errors,
or incorrect actions. Check important outcomes and cited memory frames.

## Reproduce model tests

Command-generation tests cover all 15 Python tools using their real schemas,
without executing the generated commands:

```sh
python -m opendesk.eval.local_models --model mlx-community/Qwen2.5-3B-Instruct-4bit \
  --out /tmp/commands.json
python -m opendesk.eval.local_models --model mlx-community/Qwen2.5-3B-Instruct-4bit \
  --full-catalog --out /tmp/catalog.json
python -m opendesk.eval.local_models --vision --model mlx-community/LFM2.5-VL-1.6B-4bit \
  --out /tmp/vision.json
```

The first run scopes each case to its target tool; `--full-catalog` requires the
model to select among all tools. Each case permits up to three model turns.
The vision test reads a code from a generated image. These are smoke tests, not
broad benchmarks. See [measured results](local-results.md).

End-to-end tasks can use the existing evaluation harness and its independent
outcome checks:

```sh
opendesk eval run YOUR_TASKS.json --backend local-mlx \
  --model mlx-community/Qwen2.5-3B-Instruct-4bit
opendesk eval run YOUR_TASKS.json --backend local-http --model YOUR_LOCAL_MODEL
```

Use `OPENDESK_LOCAL_URL` and `OPENDESK_LOCAL_VISION` for local HTTP/vision evals.
