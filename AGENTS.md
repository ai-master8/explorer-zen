# AGENTS.md

## What this is

Single-file Python 3 agent (`explorer_zen.py`) that loops forever, pulls a Russian Wikipedia article on its current `next_query`, asks an OpenRouter LLM to reflect on it as the character "Калипсо" / "Calypso", appends extracted "laws / paradoxes / links" to a persistent "world picture" in `memory.json`, and writes a Markdown session report to `reports/`. Launcher is `explorer-zen.bat` (Windows).

Standard library only. No third-party deps.

## Run

```bat
explorer-zen.bat
```

The bat hardcodes `OPENROUTER_API_KEY` inline and calls `python G:\Projects\explorer-zen\explorer_zen.py`. The Python script reads the key from the env var first (`os.getenv("OPENROUTER_API_KEY")`), so overriding it in the shell works. Exits with a critical-error banner if the var is unset when the bat isn't used.

The script is an infinite loop (`main()` -> `execute_session()` -> `LOOP_INTERVAL` second sleep with a live countdown dashboard). Stop with Ctrl+C. There is no graceful "run one session and exit" mode.

## No build / test / lint / typecheck / CI

There is none. Do not invent one. If you add deps, keep `urllib`/`json`/`os`/`time` style — stdlib only is the convention.

## Files

- `explorer_zen.py` — entire program. All prompts, dashboard text, and log strings are in Russian. Constants to tune live near the top: `AI_MODEL`, `LOOP_INTERVAL`, `API_TIMEOUT`, `WIKI_SEARCH_TIMEOUT`, `WIKI_SUMMARY_TIMEOUT`, `MAX_RETRIES`, `BASE_DELAY`, `MAX_SESSIONS` (None = infinite), `MEMORY_FILE`, `REPORTS_DIR`. Helper functions: `parse_llm_response`, `update_world_picture`, `write_session_report`, `invalidate_dashboard_cache` (read the function before changing `execute_session`).
- `explorer-zen.bat` — Windows launcher. Hardcodes the install path `G:\Projects\explorer-zen`; if the project moves, edit this file. It also embeds an API key — treat as a secret, do not commit, prefer the env var.
- `memory.json` — persistent "world picture" and run state. Schema:
  - `character_name`, `biography` — used verbatim in the LLM system prompt.
  - `session_counter` — incremented every session.
  - `world_picture.core_principles` / `unresolved_paradoxes` / `conceptual_links` — each list is capped at the last 20 entries on every save.
  - `next_query` — string the next session will search on Wikipedia (ru).
  - `long_term_knowledge` — append-only topic titles, capped at last 50 entries on every save.
  - `wiki_fallback_count` — consecutive Wikipedia fallbacks; reset to 0 on a successful real fetch. Bumped in `memory.json` on every stub use, visible in the dashboard.
  Editing `next_query` redirects the agent; editing the lists shapes its "memories".
- `reports/report_YYYYMMDD_HHMMSS.md` — one Markdown file per session. Treated as output, not source.
- `memory.json.bak.YYYYMMDD_HHMMSS` — backup of a corrupted `memory.json` written by `init_system` before resetting to defaults. Not auto-cleaned.

## External services

- `https://ru.wikipedia.org` — search + REST summary endpoint. 15s timeout, 1 result.
- `https://openrouter.ai/api/v1/chat/completions` — model `google/gemma-4-31b-it:free` by default; 30s timeout; retries 429 with exponential backoff (`BASE_DELAY` 15s, doubled per attempt, `MAX_RETRIES` 3).
- The free Gemma model is rate-limited and occasionally overloaded; long 429 pauses are normal, not a bug.
- Falls back to a hardcoded "Теория информации" stub discovery if Wikipedia returns nothing — by design, not an error.

## LLM output contract

The prompt requires the model to return five `##` sections: `Научный анализ`, `Новые принципы вселенной`, `Обнаруженные парадаоксы`, `Сеть связей`, `Следующая цель исследования`. The parser splits on these headers and bullet points (`-`, `*`, `•`); anything else is silently dropped. If you change the headers, update `extract_section` calls in `execute_session()` and the report writer below them.

## Conventions

- Keep Russian for user-facing strings (dashboard, prompts, reports). Code identifiers stay English.
- Dashboard redraws via `cls` + `print`; any new status states should call `render_dashboard(status, details, discovery)` for consistency.
- All file I/O is UTF-8, `ensure_ascii=False` for JSON dumps.
- No logging framework; status flows through the dashboard renderer.

## Security

- `explorer-zen.bat` line 6 contains a live `OPENROUTER_API_KEY`. If you must modify the bat, prefer setting the key via the environment and removing the inline value before sharing the repo.
- The script does no filesystem writes outside `REPORTS_DIR` and `MEMORY_FILE` (both relative to CWD). Don't change CWD between runs.
