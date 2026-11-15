# Local model test results

Measured on this 8 GiB Apple Silicon Mac on November 15, 2026, using the source
changes in PR #39. Inference ran locally with cached 4-bit MLX models. These small
smoke tests establish integration coverage, not general autonomous task accuracy.

## Command generation

Each scoped case exposes one target tool and checks a command against its real
parameter model and expected argument subset. There is one case per Python tool,
up to three model turns per case, greedy decoding, and a 512-token generation cap.
Schema-constrained decoding is enabled. **Generated commands are not executed.**
Extra valid optional arguments are permitted, so passing does not certify the
complete semantic correctness of a command (for example, a screenshot crop).

| Model | Scoped cases passed | Peak Metal allocation | Raw report |
| --- | --- | --- | --- |
| Liquid LFM2.5 1.2B Instruct, 4-bit | 12/15 | 1.28 GiB | [JSON](local-results/liquid-1.2b.json) |
| Qwen3 1.7B, 4-bit | 13/15 | 1.69 GiB | [JSON](local-results/qwen3-1.7b.json) |
| Qwen2.5 3B Instruct, 4-bit | 14/15 | 2.26 GiB | [JSON](local-results/qwen25-3b.json) |

Qwen2.5 3B passed **13/15 with all 15 tools exposed** ([report](local-results/qwen25-3b-full.json)).
All models failed the fleet argument case. Liquid also failed memory-query and
shell-command arguments; Qwen3 failed the memory-query case. Qwen2.5's full-catalog
run failed memory-query arguments as well. Schema constraints ensure structure,
not correct plans or values. Qwen2.5 3B was the strongest text planner in these runs;
Liquid remains the smaller default.

Peak Metal allocation is measured by `mlx.core.get_peak_memory()`, not total
process or system memory. Python, other applications, caches and model switching
also consume memory. Versions: MLX 0.32.4, MLX-LM 0.32.2, llguidance 1.9.1. Reports
preserve the environment's stale installed-package metadata (`opendesk: 0.1.2`);
the editable repository source identifies as 0.3.0. The latest Liquid report also
records that source version. Earlier reports predate the scorer's normalization
of omitted default arguments; their reported failures are not default omissions.

## Vision and live execution

Liquid LFM2.5-VL 1.6B 4-bit read `4826` correctly from the generated image fixture
in 1.54 seconds, with 1.80 GiB peak Metal allocation and MLX-VLM 0.7.12
([report](local-results/liquid-vision.json)). This is a synthetic image-reading test.

Separate live checks on the Mac:

- Qwen2.5 3B opened Calculator and called `app.list`; an independent process check
  confirmed Calculator was running.
- Qwen2.5 3B through the built-in HTTP bridge executed `app.list` from both the
  Python and JavaScript CLIs and returned a final answer. Python listed twice.
- Liquid vision with Qwen2.5 3B as the sequentially loaded planner took two
  screenshots and identified Calculator, then finished. Its answer also included
  unnecessary speculation, so visual answers still need verification.
- Direct Liquid vision-only planning repeatedly captured screenshots and reached
  its step limit without completing. Plain unconstrained MLX HTTP inference also
  failed the JavaScript completion trial; the structured bridge succeeded.

Captured desktop images and application lists are intentionally not included in
these artifacts. Fleet pairing, every tool action, unattended scheduled tasks,
and long multi-step workflows have not been validated end to end with these models.
Scheduling/evaluation dispatch and all registry entries are covered by automated
integration tests with controlled backends. There is no cloud fallback on a local
failure. See [setup and reproduction commands](local.md).
