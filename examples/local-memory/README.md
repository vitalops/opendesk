# Local AI over OpenDesk screen memory (Apple Silicon prototype)

This example adds questions and short activity summaries over OpenDesk's existing
local history using LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit. It runs inference on
the Mac. The initial model download requires internet; recorded text is passed
to the model in-process. No cloud inference endpoint is used.

From the repository root:

```sh
uv venv --python 3.11 .venv-memory
uv pip install --python .venv-memory/bin/python -e './python[memory]' mlx-lm
.venv-memory/bin/python examples/local-memory/ask.py 'Why did checkout fail?' --smoke-test
```

For real activity, start the recorder in another terminal (Ctrl-C stops it):

```sh
.venv-memory/bin/opendesk memory start
.venv-memory/bin/python examples/local-memory/ask.py 'Summarize my recent activity'
.venv-memory/bin/python examples/local-memory/ask.py 'What error occurred?' --query error --app Terminal
```

Use `--home PATH` for an isolated OpenDesk store, and `--since 1h` to narrow the
period. Answers include frame references; inspect original moments with
`opendesk memory show ID --home PATH`.

The model weights are approximately 628 MB according to Liquid's model card:
https://huggingface.co/LiquidAI/LFM2.5-1.2B-Instruct-MLX-4bit
Runtime memory is higher. The script reports peak Metal allocation (not total
process or system memory) and generation time, excluding model loading.

This is an experimental Python example, not a new MCP tool. It retrieves at
most eight frames and truncates each text to 1,000 characters to bound memory.
Without a keyword it uses recent frames; with a keyword it uses existing lexical
search. It does not yet implement semantic retrieval, audio recording, or a
persistent chat interface. Generated statements and citations can be wrong;
compare them with the listed sources. Missing or truncated evidence can prevent
answers. Screen content is treated as untrusted data and the model has no tools.

## First measurements on an 8 GB Apple Silicon Mac

Using mlx-lm 0.32.2 and mlx 0.32.4:

- Synthetic checkout-error question: correct cause, 2.54 seconds generation,
  0.77 GiB peak Metal allocation.
- Eight real captured moments: 6.0 seconds generation, 1.35 GiB peak Metal
  allocation. The summary overemphasized browser content and missed some
  foreground app activity. This is a baseline, not a validated activity report.
- Empty history: returns a no-matches message without loading the model.

The model did not consistently follow the requested citation formatting. Source
IDs are printed separately by the application so evidence remains inspectable.
Next implementation steps are stronger retrieval/reranking, citation validation,
activity grouping, and exposing a tested local inference backend consistently
through the Python and JavaScript tools.
