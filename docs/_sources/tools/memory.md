# `memory` — Screen Memory (searchable desktop history)

A background daemon records what is on your screen when it changes, such as switching apps, windows, or tabs, plus an idle fallback timer. It reads each window's text from the **accessibility tree** (falling back to local OCR), **redacts secrets**, and stores the text and an **encrypted** thumbnail in `~/.opendesk/memory`. The agent then gets a recall tool over that history.

Nothing leaves the machine. There is no upload, no cloud index, no telemetry.

Two agent tools sit on top of the store:

| Tool | Actions | Side effects |
|---|---|---|
| `memory` | `search`, `show`, `timeline`, `status` | Read-only |
| `memory_manage` | `pause`, `resume`, `deny`, `config`, `delete`, `export` | Changes capture settings, deletes or exports history |

Keeping the read path separate lets you grant an agent recall without letting it switch capture off or erase anything.

```python
from opendesk.tools.memory import MemoryTool
tool = MemoryTool()
```

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
const client = new OpenDeskClient();
await client.memory({ action: "search", query: "invoice", since: "last week" });
```

## Ask Claude

> "What was the error message I saw in the terminal on Tuesday?"

> "Find the invoice number I had open last week"

> "Show me every time I opened that Grafana dashboard this month"

> "What was on my screen around 3pm yesterday?"

> "Pause screen memory for an hour"

> "Never record 1Password or anything with 'bank' in the title"

> "How much space is screen memory using, and is it encrypted?"

---

## Start recording

The tools only *read* and *configure* the index. Capture happens in a separate daemon:

**Python**

```bash
pip install 'opendesk[memory]'      # capture deps, pause hotkey, encryption
opendesk memory start                          # foreground, Ctrl-C to stop
```

**JavaScript / TypeScript**

```bash
npm install @vitalops/opendesk-sdk
npm install uiohook-napi             # optional: enables the global pause hotkey
npx opendesk-js memory start         # foreground, Ctrl-C to stop
```

To run it at login as a user service (launchd / systemd --user / Task Scheduler):

```bash
opendesk memory install-service          # Python
npx opendesk-js memory install-service   # JavaScript
```

On first run on macOS the native Vision OCR helper is compiled once (about a minute) into `~/.opendesk/bin`; both SDKs share that binary and each frame then takes well under a second. Python uses `pytesseract` instead when it is installed; the JS SDK falls back to the bundled `tesseract.js` on Linux (it downloads its English model once and caches it under `~/.opendesk/memory/tessdata`).

```bash
opendesk memory status
```

```
opendesk screen memory
  daemon:    running (pid 41233, last tick: captured)
  capture:   active
  store:     /Users/you/.opendesk/memory
  frames:    1,842  (2026-08-30 09:12:04 → 2026-09-05 11:40:31)
  size:      38.0 MB of 2048 MB cap
  trigger:   events — on app/window change (poll 1s, ≥2s apart), idle fallback 30s
  retention: 30 days
  text:      ax ×1,210, none ×31, ocr ×601   redaction on
  encrypt:   thumbnails on (1842/1842 stored encrypted); text off (0/1842); key: keychain
  redacted:  14 secret(s) this daemon run
  deny list: 1Password, Bitwarden, KeePassXC, Keychain Access, LastPass, Dashlane, Private Browsing, Incognito, InPrivate
  hotkey:    <cmd>+<shift>+<alt>+p
  search:    FTS5
```

---

## When frames are captured

The default `trigger: events` mode works like screenpipe or Windows Recall: it captures when what you are looking at changes, not every N seconds.

| Event | Captured? |
|---|---|
| Frontmost **app** changes | Yes, within about `poll_seconds` (1 s). Kept even if few pixels changed, for example a small window on a large display. |
| Same app, **window or tab title** changes | Yes, unless the screen is visually identical to the last frame. |
| Title changes only in digits or symbols, such as spinners `◐ ◑`, `(3) Slack`, `45%`, or clocks | No. The title is compared by its letters only. |
| Nothing changed for `interval_seconds` (30 s) | One attempt, kept only if the screen changed. This catches scrolling and typing in the same window. |
| Changes faster than `min_interval_seconds` (2 s) | Debounced. The next allowed poll captures the latest state. |

The frontmost probe is cheap. On macOS it uses the native accessibility helper when built, otherwise a single `osascript` call (about 0.2 s). It also returns the app's pid, which the text reader uses.

`trigger: interval` restores the v1 behaviour: one attempt every `interval_seconds`, with duplicates suppressed.

```bash
opendesk memory config --trigger events --poll 1 --min-interval 2 --interval 30
opendesk memory config --trigger interval --interval 60
```

## Where the text comes from

For each kept frame the daemon first asks the OS accessibility tree for the focused window's text (`window_text(pid, max_chars=20000)` on macOS). This is exact text with no OCR errors, it includes off-screen parts of long documents, and it costs no OCR CPU. When that yields at least `ax_min_chars` (40) characters it becomes the frame text and **OCR is skipped**. Otherwise the screenshot is OCR'd locally.

Every frame records its `text_source`:

| `text_source` | Meaning |
|---|---|
| `ax` | Accessibility text |
| `ocr` | OCR of the screenshot (all frames recorded before v2) |
| `none` | Neither produced text |

Set `ocr_backend: "always"` to run OCR even when accessibility text was read. The OCR text is appended to the AX text, which helps with canvas-rendered apps whose AX tree is sparse.

## Redaction

With `redact: true` (default) the text **and window title** of every frame are scrubbed *before* they are written:

| Kind | Example |
|---|---|
| `card` | `4111 1111 1111 1111`. Must pass the Luhn checksum, 13–19 digits. |
| `aws_key` | `AKIAIOSFODNN7EXAMPLE` |
| `github_token` | `ghp_…`, `gho_…`, `github_pat_…` |
| `anthropic_key` / `openai_key` | `sk-ant-…`, `sk-proj-…`, `sk-…` |
| `slack_token` | `xoxb-…`, `xoxp-…` |
| `jwt` | `eyJ….eyJ….…` |
| `private_key` | PEM `-----BEGIN … PRIVATE KEY-----` blocks, including ones OCR cut short |
| `password` / `secret` | `password: hunter2`, `DB_PASSWORD="…"`, `api_key=…`, `token: …`, `Bearer …` |

Each hit becomes `[REDACTED:<kind>]`, so `password: hunter2` is stored as `password: [REDACTED:password]`. Redaction is pattern-based. It catches common credential shapes, not every secret, so the deny list is still the right tool for sensitive apps. `opendesk memory reindex` applies redaction retroactively to frames recorded before it was on.

## Encryption at rest

| Setting | Default | What it does |
|---|---|---|
| `encrypt_thumbnails` | `true` | Thumbnails are written as `thumbs/YYYY-MM-DD/<id>.jpg.enc` (AES-256-GCM). `store.thumbnail()`, `memory show`, and `opendesk memory show <id> --save out.jpg` decrypt them transparently. |
| `encrypt_text` | `false` | Frame text is stored AES-256-GCM encrypted. The search index holds a **blind index**: sorted, de-duplicated HMAC-SHA256 tokens of the words, so word order and frequency are hidden. Query terms are tokenised and HMAC'd the same way, so exact-word search still works. Snippets are computed after decryption. |

Limits of `encrypt_text`:

- **No prefix search on encrypted text.** `invoice*` matches only the exact word `invoice` there. App names and titles still match by prefix.
- Matching is whole-word: `refused` finds "connection refused", `refu` does not. Quoted phrases must still be contiguous; they are re-checked after decryption.
- **App names and window titles stay plaintext** so `app=` filters and the timeline work. Titles are redacted, but not encrypted.
- Blind tokens are deterministic per key. Someone with the database but not the key can tell that two frames share a word, but not which word.

**The key.** One random 32-byte key, shared by both SDKs:

| Platform | Where |
|---|---|
| macOS | Login Keychain, generic password `service=opendesk`, `account=memory-key`. Written through `security -i`, so the secret never appears in `ps`. |
| Linux / Windows | The `keyring` package (Secret Service / Credential Manager) when installed. The JS SDK reads the Secret Service through `secret-tool`. |
| Otherwise | A `0600` file `~/.opendesk/memory/key`. **This is weaker**: anything that can read your home directory, including backups and sync tools, can read the key. |

The JS SDK cannot reach the Windows Credential Manager. If the Python SDK stored the key there, the JS SDK reports the key as unavailable rather than creating a second one; use `OPENDESK_MEMORY_KEYSTORE=file` on Windows if you run both SDKs. `~/.opendesk/memory/keyinfo.json` records which store holds the key, plus a non-secret key fingerprint, so both SDKs and later runs agree. `OPENDESK_MEMORY_KEYSTORE=keychain|keyring|file` forces a store. A custom `--home` keeps its key in the file store unless forced. That keeps test and sandbox homes out of your Keychain.

If the key is lost, encrypted text and thumbnails cannot be recovered. They show as empty text and no image, and the store keeps working. **Python needs the `cryptography` package for encryption.** Without it, frames are stored unencrypted with a warning, and `status` says so.

**Changing settings.** New frames follow the current config immediately; the daemon reloads it every 10 s. To convert what is already stored, run:

```bash
opendesk memory config --encrypt-text on
opendesk memory reindex            # encrypt/decrypt text + thumbnails, redact old secrets
```

Plaintext and encrypted frames can coexist in one store and are searched together. After rewriting text, `reindex` rebuilds the full-text index and `VACUUM`s the database (with `secure_delete` on) so the old plaintext does not linger in free pages.

---

## Privacy controls

| Control | How |
|---|---|
| **Per-app deny list** | `opendesk memory deny add "Signal"`. Matched case-insensitively against the frontmost app name *and* window title. Password managers **and private/incognito browser windows** (`Private Browsing`, `Incognito`, `InPrivate`) are excluded by default. A match skips the capture entirely; no pixels are read. Old config files get the private-browsing entries added once. |
| **Redaction** | On by default; see above. `opendesk memory config --redact off` to disable. |
| **Encryption** | Thumbnails by default, text opt-in; see above. |
| **Pause hotkey** | `Cmd+Shift+Alt+P` on macOS, `Ctrl+Shift+Alt+P` elsewhere. Toggles capture from anywhere. Change it with `opendesk memory config --hotkey '<ctrl>+<alt>+m'`. |
| **Pause for a while** | `opendesk memory pause 2h`, or ask the agent: `memory_manage(action="pause", duration="2h")`. |
| **Storage cap** | Default 2 GB. When exceeded, the oldest frames are deleted first until usage is back under 90% of the cap. |
| **Retention** | Default 30 days. Older frames are deleted on every housekeeping pass. |
| **Delete** | `opendesk memory clear --before 7d`, `--app Chrome`, or everything. The agent's `memory_manage(action="delete")` requires a scope and `confirm=true`. |
| **Export** | `opendesk memory export --format json\|csv\|html` writes a decrypted copy (text + thumbnails) to a new folder, owner-only. The agent's `memory_manage(action="export")` is high-risk, so it asks for approval first. |
| **Duplicate suppression** | Visually identical consecutive frames (idle screen) are not stored. |

Everything under `~/.opendesk/memory` is created with mode `0600`/`0700`.

---

## Parameters

### `memory` (read-only)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `action` | `search` \| `show` \| `timeline` \| `status` | required | What to do |
| `query` | str | null | Search terms (`search`). All terms must match; quote phrases; `invoice*` for prefix (plaintext frames only) |
| `since` | str | null | Start of the window: `2h`, `yesterday`, `tuesday`, `last week`, `this month`, `yesterday afternoon`, `2026-09-01` |
| `until` | str | null | End of the window (same formats) |
| `app` | str | null | Only frames whose app name or window title contains this |
| `limit` | int | 15 | Max results for `search` / `timeline` |
| `id` | int | null | Frame id (`show`) |
| `include_image` | bool | true | Attach the (decrypted) thumbnail on `show` |

`show` results carry `text_source` (`ax` / `ocr` / `none`) and `encrypted` in their metadata. `status` reports the trigger mode, per-source frame counts, and encryption state; see [Status fields](#status-fields).

### `memory_manage` (changes settings / deletes)

| Parameter | Type | Default | Description |
|---|---|---|---|
| `action` | `pause` \| `resume` \| `deny` \| `config` \| `delete` \| `export` | required | What to do |
| `duration` | str | null | `pause` length, e.g. `30m`, `2h` (omit = until resumed) |
| `deny_add` / `deny_remove` | str | null | Deny-list edits (`deny`) |
| `interval_seconds` / `storage_cap_mb` / `retention_days` | number | null | Settings (`config`) |
| `trigger` | `events` \| `interval` | null | Capture trigger (`config`) |
| `redact` / `encrypt_text` / `encrypt_thumbnails` | bool | null | Privacy settings (`config`). They apply to new frames; existing frames are converted with `opendesk memory reindex`. |
| `since` / `until` / `app` | str | null | Scope for `delete` and `export` |
| `confirm` | bool | false | Required for `delete` |
| `path` | str | `~/Downloads/opendesk-memory-<time>` | `export`: new or empty folder to write to |
| `format` | `json` \| `csv` \| `html` | `json` | `export`: `frames.json`, `frames.csv`, or a browsable `index.html` |
| `query` | str | null | `export`: only moments matching this search |
| `thumbnails` | bool | true | `export`: include decrypted JPEG thumbnails in `thumbs/` |

### Configuration keys (`config.json`)

Both SDKs share `~/.opendesk/memory/config.json` (snake_case keys). Older files keep working: missing keys take their defaults.

| Key | Default | Meaning |
|---|---|---|
| `trigger` | `"events"` | `events` or `interval` |
| `interval_seconds` | `30` | Interval mode: the period. Events mode: the idle fallback. |
| `poll_seconds` | `1.0` | Events mode: frontmost-window probe period (minimum 0.2) |
| `min_interval_seconds` | `2.0` | Events mode: minimum gap between captures |
| `ax_min_chars` | `40` | Accessibility text shorter than this falls back to OCR |
| `ocr_backend` | `"auto"` | `auto`, `tesseract`, `native`, … or `always` (OCR even when AX text exists) |
| `redact` | `true` | Scrub secrets before storing |
| `encrypt_thumbnails` | `true` | AES-GCM thumbnails |
| `encrypt_text` | `false` | AES-GCM text + blind index |
| `deny_apps` | password managers + private browsing | Deny-list patterns |
| `storage_cap_mb` / `retention_days` | `2048` / `30` | Housekeeping |
| `thumbnail_width` / `thumbnail_quality` | `480` / `60` | JPEG thumbnails |
| `dedupe_threshold` | `0.02` | Visual-difference threshold for duplicate suppression |
| `pause_hotkey` | platform default | `''` disables |
| `config_version` | `2` | Lets old files receive new defaults (e.g. private-browsing deny entries) once |

### Status fields

`MemoryStore.stats()` (Python) / `store.stats()` (JS, camelCase) report:

| Python | JS | Meaning |
|---|---|---|
| `frames`, `oldest`, `newest`, `apps` | same | Counts and span |
| `thumb_bytes`, `db_bytes`, `total_bytes` | `thumbBytes`, `indexBytes`, `totalBytes` | Disk use |
| `text_sources` | `textSources` | `{"ax": n, "ocr": n, "none": n}` |
| `encrypted_text_frames` | `encryptedTextFrames` | Frames whose text is encrypted |
| `thumbnails`, `encrypted_thumbnails` | `thumbnails`, `encryptedThumbnails` | Thumbnails stored / of those encrypted |
| `encrypt_text`, `encrypt_thumbnails` | `encryptText`, `encryptThumbnails` | Current settings for new frames |
| `key_store` | `keyStore` | `keychain` / `keyring` / `file`, or null before the first encrypted write |
| `encryption_available` | `encryptionAvailable` | False when Python lacks `cryptography` |

The daemon heartbeat (`daemon.json`) adds `trigger`, `poll_seconds`, `min_interval_seconds`, `last_reason` (`start` / `app_change` / `title_change` / `interval`), `last_text_source`, per-run `text_sources` and `reasons` counts, and `redactions`.

### Time phrases

| Phrase | Meaning |
|---|---|
| `2h`, `45m`, `3d`, `1w` | The last N hours / minutes / days / weeks |
| `today`, `yesterday`, `last night` | Whole day (or the evening) |
| `tuesday`, `last tuesday` | Most recent Tuesday; the one before if today is Tuesday |
| `tuesday afternoon`, `yesterday morning` | Day parts: morning 05–12, afternoon 12–17, evening 17–22, night 20–24 |
| `this week`, `last week`, `this month`, `last month` | Calendar periods |
| `3 days ago`, `an hour ago` | Relative points |
| `2026-09-01`, `2026-09-01 14:30` | ISO date (whole day) or datetime |

---

## SDK examples

```python
params = MemoryTool.Params

# "What was the error in the terminal on Tuesday?"
r = await tool.execute(ctx, params(action="search", query="error", app="Terminal", since="tuesday"))
print(r.output)
# Screen memory search 'error' — 2026-09-01 00:00:00 → 2026-09-02 00:00:00 — app~'Terminal'
# 2 match(es), best first:
#   #1412   2026-09-01 16:42:10  [Terminal] — zsh
#           npm ERR! code ELIFECYCLE … [Error]: connect ECONNREFUSED 127.0.0.1:5432
#   #1409   2026-09-01 16:40:31  [Terminal] — zsh
#           … [error] TS2345: Argument of type …

# Read one moment in full (text + decrypted thumbnail attachment)
r = await tool.execute(ctx, params(action="show", id=1412))
r.attachments[0].media_type  # "image/jpeg"
r.metadata["text_source"]    # "ax" | "ocr" | "none"

# "Every time the dashboard was open this month"
r = await tool.execute(ctx, params(action="timeline", app="Grafana", since="this month", limit=50))
```

Privacy controls go through `memory_manage`:

```python
from opendesk.tools.memory import MemoryManageTool
manage = MemoryManageTool()
mp = MemoryManageTool.Params
await manage.execute(ctx, mp(action="pause", duration="1h"))
await manage.execute(ctx, mp(action="deny", deny_add="bank"))
await manage.execute(ctx, mp(action="config", storage_cap_mb=512, retention_days=14))
await manage.execute(ctx, mp(action="delete", since="yesterday", app="Slack", confirm=True))
```

### JavaScript / TypeScript

```typescript
import { OpenDeskClient } from "@vitalops/opendesk-sdk";
const client = new OpenDeskClient();

// "What was the error in the terminal on Tuesday?"
const r = await client.memory({ action: "search", query: "error", app: "Terminal", since: "tuesday" });
console.log(r.output);

// Full text + thumbnail (image/jpeg Buffer, decrypted)
const moment = await client.memory({ action: "show", id: (r.metadata.ids as number[])[0] });

// "Every time the dashboard was open this month"
await client.memory({ action: "timeline", app: "Grafana", since: "this month", limit: 50 });
```

JS parameter names are camelCase (`denyAdd`, `includeImage`, `storageCapMb`, `encryptText`, …); everything else matches the tables above.

Lower-level access:

```typescript
import { MemoryStore, parseWhen, ScreenMemoryRecorder } from "@vitalops/opendesk-sdk";

const store = new MemoryStore();
const [start, end] = parseWhen("last week");
for (const f of store.search("invoice", { start, end })) console.log(f.ts, f.app, f.text_source, f.snippet);
console.log(store.stats().textSources, store.stats().encryptedThumbnails);

// Embed the capture loop in your own process (events trigger by default)
const rec = new ScreenMemoryRecorder({ intervalOverride: 60 });
await rec.run();   // rec.stop() to end
```

### Direct store access (Python)

```python
from opendesk.memory import MemoryStore, parse_when

with MemoryStore() as store:
    start, end = parse_when("last week")
    for frame in store.search("invoice", start=start, end=end):
        print(frame.when, frame.app, frame.title, frame.text_source, frame.snippet)
        jpeg = store.thumbnail(frame)      # decrypted JPEG bytes
    st = store.stats()
    print(st.text_sources, st.encrypted_thumbnails, st.key_store)
```

---

## CLI reference

The JS CLI mirrors every command as `opendesk-js memory …`.

```
opendesk memory start [--interval N] [--log-file PATH]   run the capture daemon
opendesk memory status                                   daemon / storage / trigger / encryption
opendesk memory pause [30m|2h]                           pause (optionally for a duration)
opendesk memory resume
opendesk memory search "<query>" [--since ..] [--until ..] [--app ..] [--limit N]
opendesk memory timeline [--since ..] [--app ..]
opendesk memory show <id> [--save out.jpg]               full text; --save writes the decrypted thumbnail
opendesk memory deny [list|add <pattern>|remove <pattern>]
opendesk memory config [--trigger events|interval] [--interval N] [--poll S] [--min-interval S]
                       [--redact on|off] [--encrypt-text on|off] [--encrypt-thumbnails on|off]
                       [--cap MB] [--retention DAYS] [--hotkey '<ctrl>+<alt>+m']
opendesk memory reindex [-y]                             re-encrypt / decrypt / redact existing frames
opendesk memory clear [--before <when>] [--app ..] [-y]
opendesk memory export [--out DIR] [--format json|csv|html] [--since ..] [--until ..]
                       [--app ..] [--query ..] [--limit N] [--no-thumbnails]
opendesk memory install-service | uninstall-service
```

All commands accept `--home DIR` (default `~/.opendesk`).

---

## How it works

```
poll every 1s ─► paused? ─► frontmost app / title / pid ─► changed? (or 30s idle) ─► deny list? ─► capture
                                                                                                  │
         duplicate of last frame? (skipped after app switches) ◄──────────────────────────────────┘
                 │
          accessibility text (≥40 chars) ── else ──► OCR (pytesseract → macOS Vision → Windows WinRT)
                 │
          redact secrets  ─►  encrypt (thumbnail always*, text if encrypt_text)
                 │
          SQLite index.db  ──  FTS5 over text (or blind tokens) + app + title
          thumbs/YYYY-MM-DD/<id>.jpg.enc
                 │
          housekeeping: retention_days, storage_cap_mb (oldest first)

  * when encrypt_thumbnails is on (default)
```

- **Storage.** Python writes `~/.opendesk/memory/index.db` (SQLite, WAL, `secure_delete`) and `thumbs/`. JS writes `~/.opendesk/memory/frames/YYYY-MM-DD.jsonl` (no native modules) with the same `thumbs/` layout and the same encryption formats. Both share `config.json`, `paused.json`, `keyinfo.json`, the key, and the daemon heartbeat, so settings and pause state apply to either daemon. Run only one daemon per home. In a test run on a Mac, a frame cost about 16 KB of encrypted thumbnail (480 px wide) plus 1–3 KB of text and index. Event-driven capture stores a frame per app or window switch rather than one every 30 s, so a focused hour in one window is a handful of frames.
- **Search.** Python uses FTS5 with BM25 ranking and highlighted snippets, falling back to `LIKE` without FTS5. JS scans only the day files inside the time window and ranks by term hits with title/app boosts. Encrypted frames are matched through the blind index and decrypted only when they are candidates. In both SDKs all terms are ANDed; if nothing matches, the query is retried as OR so near-misses still surface.
- **Processes.** The daemon and the agent's MCP server are separate processes. Pause state, config, and a daemon heartbeat are shared through small JSON files, so `status` can tell you whether capture is actually running.
- **Local only.** The tools always read the local index and are deliberately not peer-routable.

---

Next: [audit →](audit.md) — inspect everything the agent has done this session.
