# Explorer-Zen

> [Русская версия](README.ru.md)

An autonomous AI researcher named **"Calypso" (Калипсо)** that endlessly reads Russian Wikipedia, reflects on articles through an LLM, and accumulates a "world picture" — its own network of laws, paradoxes, and conceptual links.

Each session ends with a Markdown report in `reports/`. The agent's state lives in `memory.json` and survives restarts.

## Features

- 🔁 **Infinite research loop** — configurable pause between sessions; exit at any time with `Q` (no Enter required) or set a hard limit with `MAX_SESSIONS`.
- 🧠 **Cumulative memory** — capped lists of laws, paradoxes, conceptual links, and studied topics persist across sessions.
- 📝 **Markdown reports** — one file per session with the agent's reflections, source material, and world-picture evolution.
- 🛡 **Resilient to failures** — retries 429/5xx/network errors from OpenRouter, skips the session on persistent Wikipedia or OpenRouter failures (nothing is written to memory or reports; the session counter is not incremented).
- 📦 **Python standard library only** — no third-party dependencies.

## Requirements

- **Python 3.x** (tested on 3.x on Windows; the code is cross-platform).
- **OpenRouter API key** with access to the free model `google/gemma-4-31b-it:free` (changeable — see the "Configuration" section).
- **Internet access** to `ru.wikipedia.org` and `openrouter.ai`.

## Installation

```bash
git clone https://github.com/ai-master8/explorer-zen.git
cd explorer-zen
```

No `pip install` required — no third-party dependencies.

## Setting up the API key

The key is **not stored in the repository** and not hardcoded. Use an environment variable:

**Windows (cmd, persistent):**
```cmd
setx OPENROUTER_API_KEY your-openrouter-key
```

**Windows (PowerShell, persistent):**
```powershell
[Environment]::SetEnvironmentVariable("OPENROUTER_API_KEY", "your-key", "User")
```

**Linux / macOS (add to `~/.bashrc` / `~/.zshrc`):**
```bash
export OPENROUTER_API_KEY=your-openrouter-key
```

Get a key at <https://openrouter.ai/keys>.

> ⚠ **Never paste your key directly into `explorer_zen.py` or any committed file** — they may end up in a public repository, and the key would leak.

## Running

```bash
python explorer_zen.py          # infinite loop (default)
python explorer_zen.py --once   # one session, then exit
```

(On Linux/macOS, use `python3` if `python` is not aliased to Python 3.)

Run from the project root. An infinite loop starts: a terminal dashboard refreshes every second, showing the current session, status, object of analysis, and state of the world picture. The dashboard's bottom line shows `Управление: Q — выход` — press `Q` (case-insensitive, no Enter) during the sleep to stop cleanly. `--once` runs a single session and exits — useful for smoke-testing on a fresh VPS deploy.

## Configuration

All knobs live at the top of `explorer_zen.py`, in the "ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ АГЕНТА" block:

| Parameter | Purpose | Default |
|---|---|---|
| `AI_MODEL` | OpenRouter model ID | `google/gemma-4-31b-it:free` |
| `LOOP_INTERVAL` | Pause between sessions (sec) | `120` |
| `API_TIMEOUT` | OpenRouter request timeout (sec) | `30` |
| `WIKI_SEARCH_TIMEOUT` | Wikipedia search timeout (sec) | `8` |
| `WIKI_SUMMARY_TIMEOUT` | Wikipedia summary fetch timeout (sec) | `12` |
| `MAX_RETRIES` | Retries on transient OpenRouter errors | `3` |
| `BASE_DELAY` | Initial pause on 429/5xx (sec, doubled per retry) | `15` |
| `MAX_SESSIONS` | `None` = infinite; otherwise stop after N sessions | `None` |
| `MAX_WORLD_PICTURE_ENTRIES` | Cap on world-picture lists (laws / paradoxes / links) | `20` |
| `MAX_LONG_TERM_KNOWLEDGE_ENTRIES` | Cap on the long-term knowledge list (studied topics) | `50` |
| `MAX_TITLE_LENGTH` | Max title length in the dashboard (chars) | `40` |
| `MAX_EXTRACT_LENGTH` | Max extract (article text) length in the dashboard (chars) | `40` |
| `BAR_WIDTH` | Progress-bar width in the dashboard (chars) | `20` |
| `MEMORY_FILE` | Memory file path | `memory.json` |
| `REPORTS_DIR` | Markdown reports directory | `reports/` |

## How it works

```
        ┌──────────────────────────────────────────┐
        │           main() — infinite loop         │
        └──────────────────┬───────────────────────┘
                           ▼
              ┌────────────────────────┐
              │  execute_session()     │
              └────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │ 1. Load memory.json      │
            └──────────────┬───────────┘
                           ▼
             ┌──────────────────────────┐
             │ 2. Wikipedia search      │
             │    (skip on failure)     │
             └──────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │ 3. OpenRouter request    │
            │    (LLM reflects)        │
            └──────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │ 4. Parse 5 ## sections   │
            │    → laws/paradoxes/     │
            │    links/next target     │
            └──────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │ 5. Update memory.json    │
            │    (configurable caps)  │
            └──────────────┬───────────┘
                           ▼
            ┌──────────────────────────┐
            │ 6. Write report.md       │
            └──────────────┬───────────┘
                           ▼
                  pause LOOP_INTERVAL
```

The LLM receives a system prompt with the already-accumulated world picture and is asked to strictly follow a template of five `##`-sections. The parser splits the response and appends new entities to `memory.json`.

## Files

```
explorer-zen/
├── explorer_zen.py         # the whole program
├── memory.json             # world picture + session counter (created on first run)
├── reports/                # Markdown reports per session
│   └── report_YYYYMMDD_HHMMSS.md
├── AGENTS.md               # instructions for AI agents (English)
├── README.md               # this file
└── README.ru.md            # Russian version
```

`memory.json` is runtime state, gitignored. You can edit it — for example, change `next_query` to redirect the agent to another topic, or tweak `character_name`/`biography`.

## Security

- 🔐 The OpenRouter key is set **only via environment variable**. Never paste it into `explorer_zen.py` or any commit.
- 🛡 Backups of a corrupted `memory.json` are written as `memory.json.bak.<timestamp>`; not auto-cleaned.
- 📂 The agent writes only to `REPORTS_DIR` and `MEMORY_FILE` (relative to CWD). Do not change CWD between runs.

## Known limitations

- The free Gemma 4 31B model on OpenRouter often returns 429 — this is normal, the agent retries with exponential backoff.
- Wikipedia search sometimes returns no results or times out. In that case the session is skipped: nothing is written to `memory.json` or `reports/`, the session counter is not incremented, and the agent retries the same `next_query` next session. The dashboard's `Сервисы:` row shows `OK` (green) when both services are healthy, or `Wikipedia N / OpenRouter M` (yellow) when either has consecutive failures.
- The LLM can get stuck suggesting the same `next_query` over and over (e.g. when Wikipedia redirects it). The last `MAX_RECENT_QUERIES` topics are kept in `memory.json["recent_queries"]`; if the LLM repeats one, `_pick_next_query` replaces it with the most recent topic from `long_term_knowledge` or a hardcoded fallback (`Голографический принцип`, `Квантовая запутанность`, `Тёмная материя`, `Стрела времени`).
- The LLM-response parser is strictly tied to the five-`##`-section template. If the model reorders or renames the sections, those sections are simply lost — the agent does not crash.

## License

Not specified. Use at your own risk.
