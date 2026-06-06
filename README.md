# Explorer-Zen

> [Русская версия](README.ru.md)

An autonomous AI researcher named **"Calypso" (Калипсо)** that endlessly reads Russian Wikipedia, reflects on articles through an LLM, and accumulates a "world picture" — its own network of laws, paradoxes, and conceptual links.

Each session ends with a Markdown report in `reports/`. The agent's state lives in `memory.json` and survives restarts.

## Features

- 🔁 **Infinite research loop** — 2-minute pause between sessions; stop at any time (Ctrl+C) or set a hard limit with `MAX_SESSIONS`.
- 🧠 **Cumulative memory** — last 20 laws, 20 paradoxes, 20 links, and 50 studied topics persist across sessions.
- 📝 **Markdown reports** — one file per session with the agent's reflections, source material, and world-picture evolution.
- 🛡 **Resilient to failures** — retries 429/5xx/network errors from OpenRouter, survives Wikipedia outages (with a visible fallback counter).
- 📦 **Python standard library only** — no third-party dependencies.

## Requirements

- **Python 3.x** (tested on 3.x on Windows; the code is cross-platform, but `explorer-zen.bat` is Windows-only).
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

> ⚠ **Never paste your key directly into `explorer-zen.bat` or `explorer_zen.py`** — these files may end up in a public repository, and the key would leak.

## Running

**Windows:**
```cmd
explorer-zen.bat
```

The bat file invokes `python G:\Projects\explorer-zen\explorer_zen.py`. If the project moves, edit the path in `.bat` (line 8).

**Linux / macOS:**
```bash
python3 explorer_zen.py
```

An infinite loop starts: a terminal dashboard refreshes every second, showing the current session, status, object of analysis, and state of the world picture. Stop with `Ctrl+C`.

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
            │    (or fallback stub)    │
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
            │    (cap-20 + cap-50)     │
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
├── explorer-zen.bat        # Windows launcher
├── memory.json             # world picture + session counter (created on first run)
├── reports/                # Markdown reports per session
│   └── report_YYYYMMDD_HHMMSS.md
├── AGENTS.md               # instructions for AI agents (English)
├── README.md               # this file
└── README.ru.md            # Russian version
```

`memory.json` is runtime state, gitignored. You can edit it — for example, change `next_query` to redirect the agent to another topic, or tweak `character_name`/`biography`.

## Security

- 🔐 The OpenRouter key is set **only via environment variable**. Never paste it into `explorer-zen.bat`, `explorer_zen.py`, or any commit.
- 🛡 Backups of a corrupted `memory.json` are written as `memory.json.bak.<timestamp>`; not auto-cleaned.
- 📂 The agent writes only to `REPORTS_DIR` and `MEMORY_FILE` (relative to CWD). Do not change CWD between runs.

## Known limitations

- The free Gemma 4 31B model on OpenRouter often returns 429 — this is normal, the agent retries with exponential backoff.
- Wikipedia search sometimes returns no results or times out. In that case, a fallback stub ("Теория информации" / Information Theory) kicks in (visible on the dashboard as "Сбоев Википедии подряд: N" / consecutive Wikipedia failures). Resets on the first successful real search.
- The LLM-response parser is strictly tied to the five-`##`-section template. If the model reorders or renames the sections, those sections are simply lost — the agent does not crash.

## License

Not specified. Use at your own risk.
