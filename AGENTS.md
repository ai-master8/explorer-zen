# AGENTS.md

## What this is

Single-file Python 3 agent (`explorer_zen.py`) that loops forever, pulls a Russian Wikipedia article on its current `next_query`, asks an OpenRouter LLM to reflect on it as the character "Калипсо" / "Calypso", appends extracted "laws / paradoxes / links" to a persistent "world picture" in `memory.json`, and writes a Markdown session report to `reports/`.

Standard library only. No third-party deps.

## Run

```bash
python explorer_zen.py          # infinite loop (default)
python explorer_zen.py --once   # one session, then exit
```

The Python script reads `OPENROUTER_API_KEY` from the env var first (`os.getenv("OPENROUTER_API_KEY")`). Exits with a critical-error banner if the var is unset.

The script is an infinite loop (`main()` -> `execute_session()` -> `LOOP_INTERVAL` second sleep with a live countdown dashboard). Stop with `Q` (case-insensitive, no Enter required) during the sleep, or `Ctrl+C` at any time. Both paths print a clean dashboard status instead of a stack trace. `--once` runs a single session and exits cleanly (used for smoke-testing on a fresh VPS deploy).

## No build / test / lint / typecheck / CI

There is none. Do not invent one. If you add deps, keep `urllib`/`json`/`os`/`time` style — stdlib only is the convention.

## Files

- `explorer_zen.py` — entire program. All prompts, dashboard text, and log strings are in Russian. Constants to tune live near the top: `AI_MODEL`, `LOOP_INTERVAL`, `API_TIMEOUT`, `WIKI_SEARCH_TIMEOUT`, `WIKI_SUMMARY_TIMEOUT`, `MAX_RETRIES`, `BASE_DELAY`, `MAX_SESSIONS` (None = infinite), `MAX_WORLD_PICTURE_ENTRIES`, `MAX_LONG_TERM_KNOWLEDGE_ENTRIES`, `MAX_TITLE_LENGTH`, `MAX_EXTRACT_LENGTH`, `BAR_WIDTH`, `MAX_RECENT_QUERIES`, `MEMORY_FILE`, `REPORTS_DIR`. Helper functions: `parse_llm_response`, `update_world_picture`, `write_session_report`, `invalidate_dashboard_cache` (read the function before changing `execute_session`).
- `explorer-zen.bat` — **removed**. Run `python explorer_zen.py` directly. (The old bat hardcoded the install path and an inline API key; both are gone.)
- `memory.json` — persistent "world picture" and run state. Schema:
  - `character_name`, `biography` — used verbatim in the LLM system prompt.
  - `session_counter` — incremented only on successful sessions (both Wikipedia and OpenRouter responded).
  - `world_picture.core_principles` / `unresolved_paradoxes` / `conceptual_links` — each list is capped on every save (see `MAX_WORLD_PICTURE_ENTRIES` in code).
  - `next_query` — string the next session will search on Wikipedia (ru).
  - `long_term_knowledge` — append-only topic titles, capped on every save (see `MAX_LONG_TERM_KNOWLEDGE_ENTRIES` in code).
  - `wiki_fallback_count` — consecutive Wikipedia connection failures; reset to 0 on a successful real fetch. Bumped in `memory.json` on every failed session, visible in the dashboard. Not persisted on failure (resets on the next successful read).
  - `openrouter_fallback_count` — consecutive OpenRouter connection failures (only persisted on a successful session write). Visible in the dashboard together with `wiki_fallback_count`.
  - `recent_queries` — ring buffer of the last `MAX_RECENT_QUERIES` `next_query` values. Used by `_pick_next_query` to detect a loop: if the LLM suggests a topic already in `recent_queries`, it's replaced by a topic from `long_term_knowledge` (most recent first) or from `CYCLE_FALLBACK_TOPICS`.
  Editing `next_query` redirects the agent; editing the lists shapes its "memories".
- `reports/report_YYYYMMDD_HHMMSS.md` — one Markdown file per session. Treated as output, not source.
- `memory.json.bak.YYYYMMDD_HHMMSS` — backup of a corrupted `memory.json` written by `init_system` before resetting to defaults. Not auto-cleaned.

## External services

- `https://ru.wikipedia.org` — search + REST summary endpoint. 15s timeout, 1 result.
- `https://openrouter.ai/api/v1/chat/completions` — model `google/gemma-4-31b-it:free` by default; 30s timeout; retries 429 with exponential backoff (`BASE_DELAY` 15s, doubled per attempt, `MAX_RETRIES` 3).
- The free Gemma model is rate-limited and occasionally overloaded; long 429 pauses are normal, not a bug.
- If Wikipedia returns nothing (network error, timeout, empty search), the session is **skipped**: nothing is written to `memory.json` or `reports/`, and `session_counter` is not incremented. The agent will retry the same `next_query` next session.
- If OpenRouter returns an error (after exhausting `MAX_RETRIES`), the session is also **skipped** for the same reason.

## LLM output contract

The prompt requires the model to return five `##` sections: `Научный анализ`, `Новые принципы вселенной`, `Обнаруженные парадаоксы`, `Сеть связей`, `Следующая цель исследования`. The parser splits on these headers and bullet points (`-`, `*`, `•`); anything else is silently dropped. If you change the headers, update `extract_section` calls in `execute_session()` and the report writer below them.

## Conventions

- Keep Russian for user-facing strings (dashboard, prompts, reports). Code identifiers stay English.
- Dashboard redraws via `cls` + `print`; any new status states should call `render_dashboard(status, details, discovery)` for consistency.
- All file I/O is UTF-8, `ensure_ascii=False` for JSON dumps.
- No logging framework; status flows through the dashboard renderer.

## Security

- The OpenRouter API key is read from the `OPENROUTER_API_KEY` environment variable only — never hardcode it in `explorer_zen.py` or any committed file.
- The script does no filesystem writes outside `REPORTS_DIR` and `MEMORY_FILE` (both relative to CWD). Don't change CWD between runs.
