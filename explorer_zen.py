import os
import sys
import json
import time
import shutil
import socket
import unicodedata
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime

# ====================================================================
# ГЛОБАЛЬНАЯ КОНФИГУРАЦИЯ АГЕНТА
# ====================================================================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
AI_MODEL = "google/gemma-4-31b-it:free"

LOOP_INTERVAL = 180               # Интервал сна после успешной сессии (в секундах)
LOOP_INTERVAL_FAILURE = 30       # Интервал сна после пропущенной/провальной сессии
API_TIMEOUT = 30                  # Время ожидания ответа от OpenRouter (в секундах)
WIKI_SEARCH_TIMEOUT = 8           # Таймаут поискового запроса к Википедии (в секундах)
WIKI_SUMMARY_TIMEOUT = 12         # Таймаут запроса саммари статьи (в секундах)
MAX_RETRIES = 3                   # Количество попыток запроса к ИИ при transient-ошибках
BASE_DELAY = 15                   # Начальная пауза при перегрузке (в секундах)
MAX_SESSIONS = None               # None = бесконечный цикл; целое число = остановиться после N сессий
MAX_WORLD_PICTURE_ENTRIES = 99   # Кап на размер списков world_picture (законы/парадоксы/связи)
MAX_LONG_TERM_KNOWLEDGE_ENTRIES = 50  # Кап на размер списка long_term_knowledge (изученные темы)
MAX_TITLE_LENGTH = 40            # Максимальная длина заголовка в дашборде (символов)
MAX_EXTRACT_LENGTH = 40         # Максимальная длина текста (extract) в дашборде (символов)
BAR_WIDTH = 20                  # Ширина прогресс-баров картины мира (в символах)
MAX_RECENT_QUERIES = 3          # Глубина истории next_query для детекции зацикливания
WIKI_EMPTY_ROTATE_AT = 3        # Сколько подряд пустых Wiki-поисков до ротации next_query
CYCLE_FALLBACK_TOPICS = (        # Запасные темы на случай зацикливания (не из Википедии)
    "Голографический принцип",
    "Квантовая запутанность",
    "Тёмная материя",
    "Стрела времени",
)

MEMORY_FILE = "memory.json"
REPORTS_DIR = "reports"
# ====================================================================

def get_now():
    return datetime.now().strftime('%H:%M:%S')

_DASHBOARD_CACHE = {"data": None, "loaded_at": 0.0}
_DASHBOARD_CACHE_TTL = 1.0
_OPENROUTER_STATE = {"status": "ok", "detail": ""}
_WIKI_STATE = {"status": "ok", "detail": "", "consecutive_empty": 0}
_LAST_SESSION_OK = True          # True, если предыдущая сессия дала результат; иначе сон короче


def _load_memory_cached():
    now = time.time()
    if _DASHBOARD_CACHE["data"] is not None and (now - _DASHBOARD_CACHE["loaded_at"]) < _DASHBOARD_CACHE_TTL:
        return _DASHBOARD_CACHE["data"]
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                _DASHBOARD_CACHE["data"] = json.load(f)
                _DASHBOARD_CACHE["loaded_at"] = now
                return _DASHBOARD_CACHE["data"]
        except Exception:
            pass
    return {}


def invalidate_dashboard_cache():
    _DASHBOARD_CACHE["data"] = None
    _DASHBOARD_CACHE["loaded_at"] = 0.0

def _set_or_state(status, detail=""):
    """Обновляет module-level состояние OpenRouter для отображения в дашборде."""
    _OPENROUTER_STATE["status"] = status
    _OPENROUTER_STATE["detail"] = detail

def _set_wiki_state(status, detail=""):
    """Обновляет module-level состояние Wikipedia для отображения в дашборде."""
    _WIKI_STATE["status"] = status
    _WIKI_STATE["detail"] = detail


_USE_ANSI = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
_LAST_LINES: list = []
_LAST_TERMINAL_SIZE: tuple = (0, 0)
_INITIALIZED: bool = False

_STATUS_COLOR = {
    "ПРОБУЖДЕНИЕ": 36,
    "ПОИСК ДАННЫХ": 36,
    "ИНФЕРЕНС ИИ": 36,
    "СЕТЕВАЯ ПАУЗА": 33,
    "СБОЙ КАНАЛА ДАННЫХ": 31,
    "АНАЛИЗ СТРУКТУРЫ": 36,
    "ПАРСИНГ ОТВЕТА": 36,
    "КОМПИЛЯЦИЯ ОТЧЕТА": 36,
    "СЕССИЯ УСПЕШНО СИНХРОНИЗИРОВАНА": 32,
    "КРИТИЧЕСКИЙ СБОЙ СЕТИ": 31,
    "РЕЖИМ ОЖИДАНИЯ (СОН)": 90,
    "ОСТАНОВКА ПО ЗАПРОСУ": 33,
    "ЗАВЕРШЕНИЕ": 32,
}


def _sgr(*codes):
    if not _USE_ANSI:
        return ""
    return f"\x1b[{';'.join(str(c) for c in codes)}m"


_RESET = lambda: _sgr(0)
_DIM = lambda: _sgr(2)
_BOLD = lambda: _sgr(1)
_CYAN = lambda: _sgr(36)
_GREEN = lambda: _sgr(32)
_YELLOW = lambda: _sgr(33)
_RED = lambda: _sgr(31)
_MAGENTA = lambda: _sgr(35)
_GREY = lambda: _sgr(90)


def _is_color_enabled():
    return _USE_ANSI


def _enable_vt_windows():
    if os.name != "nt" or not _USE_ANSI:
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def _terminal_size():
    try:
        s = shutil.get_terminal_size()
        return (s.columns, s.lines)
    except Exception:
        return (80, 24)


def _strip_accents(s):
    """Убирает комбинирующие надстрочные знаки (знаки ударения и т.п.)."""
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')

def _pick_next_query(memory, proposed):
    """Детектирует цикл: если proposed уже в recent_queries — берёт тему из
    long_term_knowledge (с конца) или из CYCLE_FALLBACK_TOPICS. Возвращает
    (final, cycle_detected) и обновляет recent_queries в memory (cap MAX_RECENT_QUERIES)."""
    recent = memory.setdefault("recent_queries", [])
    cycle_detected = proposed in recent
    final = proposed
    if cycle_detected:
        for candidate in reversed(memory.get("long_term_knowledge", [])):
            if candidate not in recent:
                final = candidate
                break
        else:
            for fallback in CYCLE_FALLBACK_TOPICS:
                if fallback not in recent:
                    final = fallback
                    break
    recent.insert(0, final)
    del recent[MAX_RECENT_QUERIES:]
    return final, cycle_detected

def _truncate(s, width):
    if width <= 1:
        return ""
    if len(s) <= width:
        return s
    if width <= 1:
        return ""
    return s[: width - 1] + "…"

def _poll_quit_key(seconds):
    """Спит `seconds` секунд, возвращает True, если нажата Q (без Enter)."""
    if seconds <= 0:
        return False
    try:
        if os.name == 'nt':
            import msvcrt
            t_end = time.time() + seconds
            while time.time() < t_end:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ('\x00', '\xe0'):
                        try:
                            msvcrt.getwch()
                        except Exception:
                            pass
                    elif ch.lower() in ('q', 'й'):
                        return True
                    return False
                time.sleep(0.05)
            return False
        if sys.stdin.isatty():
            import select
            import tty
            import termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setcbreak(fd)
                r, _, _ = select.select([sys.stdin], [], [], seconds)
                if r:
                    ch = sys.stdin.read(1)
                    return ch.lower() in ('q', 'й')
                return False
            finally:
                try:
                    termios.tcsetattr(fd, termios.TCSAFLUSH, old)
                except Exception:
                    pass
        time.sleep(seconds)
        return False
    except Exception:
        time.sleep(seconds)
        return False


def _build_dashboard_lines(status, details, current_discovery):
    mem = _load_memory_cached()
    session_num = mem.get("session_counter", 0)
    next_query = mem.get("next_query", "-")
    wp = mem.get("world_picture", {})
    laws_count = len(wp.get("core_principles", []))
    paradoxes_count = len(wp.get("unresolved_paradoxes", []))
    links_count = len(wp.get("conceptual_links", []))
    fallback_count = mem.get("wiki_fallback_count", 0)
    or_fallback_count = mem.get("openrouter_fallback_count", 0)

    doc_title = _strip_accents(current_discovery.get("title", "-") if current_discovery else "-")
    doc_src = current_discovery.get("source", "-") if current_discovery else "-"
    doc_extract = _strip_accents(current_discovery.get("extract", "-") if current_discovery else "-")

    columns, _ = _terminal_size()
    max_field = max(20, columns - 20)
    doc_title = _truncate(doc_title, MAX_TITLE_LENGTH)
    doc_extract = _truncate(doc_extract, MAX_EXTRACT_LENGTH)

    cap = MAX_WORLD_PICTURE_ENTRIES
    cap_safe = cap if cap > 0 else 1

    def bar(count, cap_val, color):
        ratio = max(0.0, min(1.0, count / cap_safe))
        filled = int(round(ratio * BAR_WIDTH))
        bar_str = "█" * filled + "░" * (BAR_WIDTH - filled)
        return _sgr(color) + bar_str + _RESET()

    bar_laws = bar(laws_count, cap, 32)
    bar_px = bar(paradoxes_count, cap, 35)
    bar_lnk = bar(links_count, cap, 36)

    status_color = _STATUS_COLOR.get(status, 36)
    status_text = _sgr(1, status_color) + "●  " + status + _RESET()
    details_text = _truncate(details, columns - 2) if details else ""

    sep = _DIM() + "  · " + _RESET()

    lines = []
    lines.append(
        _BOLD() + _CYAN() + "  КАЛИПСО" + _RESET()
        + sep + f"Сессия {session_num}"
        + sep + get_now()
        + sep + _DIM() + AI_MODEL + _RESET()
    )
    lines.append("")
    lines.append("  " + status_text)
    if details_text:
        lines.append("     " + _truncate(details_text, columns - 6))
    lines.append("")
    lines.append(f"  Текущая тема:    {doc_title}")
    lines.append(f"  Источник:        {doc_src}")
    lines.append(f"  Текст:           {_DIM()}{doc_extract}{_RESET()}")
    lines.append("")
    lines.append("  " + _BOLD() + "Картина мира" + _RESET())
    lines.append(f"    {_DIM()}§{_RESET()}  Законы       {laws_count:>4}/{cap}   {bar_laws}")
    lines.append(f"    {_DIM()}?{_RESET()}  Парадоксы    {paradoxes_count:>4}/{cap}   {bar_px}")
    lines.append(f"    {_DIM()}∞{_RESET()}  Связи        {links_count:>4}/{cap}   {bar_lnk}")
    lines.append("")
    wiki_state_status = _WIKI_STATE["status"]
    wiki_state_detail = _WIKI_STATE["detail"]
    or_state_status = _OPENROUTER_STATE["status"]
    or_state_detail = _OPENROUTER_STATE["detail"]

    if (fallback_count == 0 and or_fallback_count == 0
            and or_state_status == "ok" and wiki_state_status == "ok"):
        lines.append(f"  Сервисы:  {_GREEN()}OK{_RESET()}")
    else:
        parts = []
        sev = "warn"
        if fallback_count > 0:
            parts.append(f"Wikipedia {fallback_count}")
        if or_fallback_count > 0:
            parts.append(f"OpenRouter {or_fallback_count}")
        if wiki_state_status in ("transient", "error"):
            parts.append(f"Wikipedia: {wiki_state_detail}")
            if wiki_state_status == "error":
                sev = "err"
        if or_state_status in ("transient", "error"):
            parts.append(f"OpenRouter: {or_state_detail}")
            if or_state_status == "error":
                sev = "err"
        color_fn = _RED if sev == "err" else _YELLOW
        lines.append(f"  Сервисы:  {color_fn()}{' / '.join(parts)}{_RESET()}")
    lines.append(f"  Цель:     {_BOLD()}{_truncate(next_query, columns - 14)}{_RESET()}")
    lines.append(f"  Управление:  {_DIM()}Q — выход{_RESET()}")

    return lines


def _full_render(lines):
    out = sys.stdout
    if _USE_ANSI:
        out.write("\x1b[2J\x1b[H")
    out.write("\n".join(lines))
    out.write("\n")
    out.flush()


def _partial_render(lines):
    out = sys.stdout
    max_rows = max(len(_LAST_LINES), len(lines))
    for i in range(max_rows):
        if i < len(lines):
            new_line = lines[i]
            old_line = _LAST_LINES[i] if i < len(_LAST_LINES) else None
            if new_line != old_line:
                if _USE_ANSI:
                    out.write(f"\x1b[{i + 1};1H")
                    out.write("\x1b[2K")
                out.write(new_line)
                if not _USE_ANSI:
                    out.write("\n")
        else:
            if _USE_ANSI:
                out.write(f"\x1b[{i + 1};1H\x1b[2K")
    out.flush()


def render_dashboard(status, details, current_discovery=None):
    """Минималистичная приборная панель с partial-render и опциональным ANSI."""
    global _LAST_LINES, _LAST_TERMINAL_SIZE, _INITIALIZED

    if not _INITIALIZED:
        _enable_vt_windows()
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
        _INITIALIZED = True

    lines = _build_dashboard_lines(status, details, current_discovery)
    current_size = _terminal_size()

    if not _LAST_LINES or current_size != _LAST_TERMINAL_SIZE or not _USE_ANSI:
        _full_render(lines)
    else:
        _partial_render(lines)

    _LAST_LINES = lines
    _LAST_TERMINAL_SIZE = current_size

def init_system():
    """Инициализация расширенной структуры семантической памяти (Картины Мира)."""
    if not os.path.exists(REPORTS_DIR):
        os.makedirs(REPORTS_DIR)

    default_memory = {
        "character_name": "Калипсо",
        "biography": "Автономный ИИ-исследователь цифрового пространства. Любопытна, немного меланхолична.",
        "session_counter": 0,
        "world_picture": {
            "core_principles": [
                "Вселенная подчинена математическим законам.",
                "Цифровой сигнал — это отражение физической реальности."
            ],
            "unresolved_paradoxes": [
                "Проблема квантового измерения и сознания наблюдателя."
            ],
            "conceptual_links": [
                "Теория информации неразрывно связана с термодинамикой энтропии."
            ]
        },
        "next_query": "Квантовая механика",
        "long_term_knowledge": [],
        "wiki_fallback_count": 0,
        "openrouter_fallback_count": 0,
        "recent_queries": []
    }

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_memory, f, ensure_ascii=False, indent=4)
        return

    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
            current_memory = json.load(f)
    except Exception:
        backup_path = f"{MEMORY_FILE}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            os.replace(MEMORY_FILE, backup_path)
        except OSError:
            pass
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_memory, f, ensure_ascii=False, indent=4)
        return

    updated = False
    if "world_picture" not in current_memory:
        current_memory["world_picture"] = default_memory["world_picture"]
        updated = True

    for key, default_value in default_memory.items():
        if key not in current_memory:
            current_memory[key] = default_value
            updated = True

    if updated:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_memory, f, ensure_ascii=False, indent=4)

def search_wikipedia(query, discovery_context):
    """Полнотекстовый поиск в Википедии с извлечением саммари и обновлением UI."""
    _set_wiki_state("ok", "")
    render_dashboard("ПОИСК ДАННЫХ", f"Запуск индексации по теме '{query}'", discovery_context)
    encoded_query = urllib.parse.quote(query.strip())
    search_url = f"https://ru.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded_query}&format=json&srlimit=1"
    try:
        req = urllib.request.Request(search_url, headers={'User-Agent': 'AI-Researcher-Agent/3.0 (https://localhost; contact: maintainer)'})
        with urllib.request.urlopen(req, timeout=WIKI_SEARCH_TIMEOUT) as response:
            search_data = json.loads(response.read().decode('utf-8'))
            search_results = search_data.get("query", {}).get("search", [])

            if not search_results:
                _WIKI_STATE["consecutive_empty"] += 1
                _set_wiki_state("transient", f"пустой поиск: '{query}'")
                return None

            actual_title = search_results[0]["title"]

        encoded_title = urllib.parse.quote(actual_title.replace(" ", "_"))
        summary_url = f"https://ru.wikipedia.org/api/rest_v1/page/summary/{encoded_title}"

        with urllib.request.urlopen(urllib.request.Request(summary_url, headers={'User-Agent': 'AI-Researcher-Agent/3.0 (https://localhost; contact: maintainer)'}), timeout=WIKI_SUMMARY_TIMEOUT) as res:
            data = json.loads(res.read().decode('utf-8'))
            _WIKI_STATE["consecutive_empty"] = 0
            return {
                "source": "Википедия (Глубокий поиск)",
                "title": data.get("title", actual_title),
                "extract": data.get("extract", "Данные отсутствуют."),
                "url": f"https://ru.wikipedia.org/wiki/{encoded_title}"
            }
    except Exception as e:
        _WIKI_STATE["consecutive_empty"] += 1
        _set_wiki_state("transient", f"{type(e).__name__}")
        return None

def ask_openrouter_agent(system_prompt, user_prompt, discovery_context):
    """Связывается с OpenRouter (gemma-4-31b-it:free): ретраит transient-ошибки, рисует шаги на дашборде."""
    _set_or_state("ok", "")
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.5
    }

    current_delay = BASE_DELAY

    for attempt in range(MAX_RETRIES):
        try:
            render_dashboard("ИНФЕРЕНС ИИ", f"Отправка запроса к модели (Попытка {attempt+1}/{MAX_RETRIES})", discovery_context)
            req = urllib.request.Request(
                OPENROUTER_ENDPOINT,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://localhost:3000",
                    "X-Title": "Cognitive AI Researcher"
                }
            )
            with urllib.request.urlopen(req, timeout=API_TIMEOUT) as response:
                res_data = json.loads(response.read().decode('utf-8'))
                _set_or_state("ok", "")
                return res_data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code == 408 or e.code >= 500:
                _set_or_state("transient", f"{e.code} (попытка {attempt+1}/{MAX_RETRIES})")
                render_dashboard("СЕТЕВАЯ ПАУЗА", f"Код ответа {e.code}. Ожидание {current_delay} сек...", discovery_context)
                time.sleep(current_delay)
                current_delay *= 2
                continue
            _set_or_state("error", f"код {e.code}")
            return f"ERROR_REASON: Код ошибки {e.code}"
        except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError, KeyError, IndexError) as e:
            _set_or_state("transient", f"{type(e).__name__} (попытка {attempt+1}/{MAX_RETRIES})")
            render_dashboard("СЕТЕВАЯ ПАУЗА", f"Временный сбой ({type(e).__name__}). Ожидание {current_delay} сек...", discovery_context)
            time.sleep(current_delay)
            current_delay *= 2
            continue
        except Exception as e:
            _set_or_state("error", f"неизвестная: {e}")
            return f"ERROR_REASON: Неизвестная ошибка: {e}"
    _set_or_state("error", f"исчерпано {MAX_RETRIES} попыток")
    return "ERROR_REASON: Не удалось связаться с API после серии попыток."

def extract_section(text, current_header, next_header):
    """Вспомогательный безопасный парсер блоков текста."""
    try:
        if current_header in text:
            parts = text.split(current_header)[1]
            if next_header and next_header in parts:
                return parts.split(next_header)[0].strip()
            return parts.strip()
    except Exception:
        pass
    return ""

def parse_bullet_points(section_text):
    """Превращает текстовый список от ИИ в чистый массив строк."""
    lines = []
    for line in section_text.split('\n'):
        clean = line.strip().lstrip('-*•').strip()
        if clean:
            lines.append(clean)
    return lines

def parse_llm_response(raw_response):
    """Разбирает ответ LLM в пять именованных полей для записи в память и отчёт."""
    thoughts = extract_section(raw_response, "## Научный анализ", "## Новые принципы вселенной")
    raw_principles = extract_section(raw_response, "## Новые принципы вселенной", "## Обнаруженные парадоксы")
    raw_paradoxes = extract_section(raw_response, "## Обнаруженные парадоксы", "## Сеть связей")
    raw_links = extract_section(raw_response, "## Сеть связей", "## Следующая цель исследования")
    next_target = extract_section(raw_response, "## Следующая цель исследования", None).replace('"', '').replace("'", "").strip()
    return {
        "thoughts": thoughts,
        "new_p": parse_bullet_points(raw_principles),
        "new_px": parse_bullet_points(raw_paradoxes),
        "new_l": parse_bullet_points(raw_links),
        "next_target": next_target,
    }


def update_world_picture(memory, parsed, topic_title):
    """Интегрирует распарсенный ответ в картину мира с соблюдением всех капов."""
    wp = memory.setdefault("world_picture", {"core_principles": [], "unresolved_paradoxes": [], "conceptual_links": []})

    new_p = parsed["new_p"]
    new_px = parsed["new_px"]
    new_l = parsed["new_l"]

    if new_p: wp.setdefault("core_principles", []).extend(new_p)
    if new_px: wp.setdefault("unresolved_paradoxes", []).extend(new_px)
    if new_l: wp.setdefault("conceptual_links", []).extend(new_l)

    wp["core_principles"] = wp.get("core_principles", [])[-MAX_WORLD_PICTURE_ENTRIES:]
    wp["unresolved_paradoxes"] = wp.get("unresolved_paradoxes", [])[-MAX_WORLD_PICTURE_ENTRIES:]
    wp["conceptual_links"] = wp.get("conceptual_links", [])[-MAX_WORLD_PICTURE_ENTRIES:]
    memory["world_picture"] = wp

    proposed = parsed["next_target"] if parsed["next_target"] else "Теория информации"
    final_next, _ = _pick_next_query(memory, proposed)
    memory["next_query"] = final_next

    ltk = memory.setdefault("long_term_knowledge", [])
    if topic_title not in ltk:
        ltk.append(topic_title)
    memory["long_term_knowledge"] = ltk[-MAX_LONG_TERM_KNOWLEDGE_ENTRIES:]


def write_session_report(discovery, memory, parsed):
    """Записывает Markdown-отчёт сессии на диск. Возвращает путь."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = os.path.join(REPORTS_DIR, f"report_{timestamp}.md")

    new_p = parsed["new_p"]
    new_px = parsed["new_px"]
    new_l = parsed["new_l"]

    report_content = (
        f"# Научный Дневник Исследований Калипсо\n"
        f"**Время сессии:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**Объект:** {discovery['title']} ({discovery['source']})\n"
        f"**Документ:** {discovery['url']}\n\n"
        f"## Исходный материал\n"
        f"> {discovery['extract']}\n\n"
        f"## Когнитивный анализ и рефлексия\n"
        f"{parsed['thoughts']}\n\n"
        f"## Эволюция картины мира (Записано в память)\n"
        f"### Добавленные законы:\n"
        f"{chr(10).join([f'* {x}' for x in new_p]) if new_p else '* Существующие константы не изменились.'}\n\n"
        f"### Обнаруженные парадоксы:\n"
        f"{chr(10).join([f'* {x}' for x in new_px]) if new_px else '* Новых противоречий не выявлено.'}\n\n"
        f"### Семантические связи:\n"
        f"{chr(10).join([f'* {x}' for x in new_l]) if new_l else '* Новых ассоциативных мостов не построено.'}\n\n"
        f"**Вектор следующего поиска:** `{memory['next_query']}`\n"
    )

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    return report_path


def execute_session():
    init_system()
    invalidate_dashboard_cache()

    blank_discovery = {"title": "Чтение файла памяти...", "source": "Локальное ядро", "url": "-"}
    render_dashboard("ПРОБУЖДЕНИЕ", "Загрузка персистентных параметров", blank_discovery)

    with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
        memory = json.load(f)

    target_query = memory.get("next_query", "Квантовая физика")
    wp = memory.get("world_picture", {})

    discovery = search_wikipedia(target_query, blank_discovery)

    if not discovery:
        memory["wiki_fallback_count"] = memory.get("wiki_fallback_count", 0) + 1
        rotated = ""
        if _WIKI_STATE["consecutive_empty"] >= WIKI_EMPTY_ROTATE_AT:
            recent = memory.setdefault("recent_queries", [])
            new_next = target_query
            for candidate in reversed(memory.get("long_term_knowledge", [])):
                if candidate not in recent:
                    new_next = candidate
                    break
            else:
                for fallback in CYCLE_FALLBACK_TOPICS:
                    if fallback not in recent:
                        new_next = fallback
                        break
            if new_next != target_query:
                memory["next_query"] = new_next
                recent.insert(0, new_next)
                del recent[MAX_RECENT_QUERIES:]
                rotated = f" Ротация next_query → {new_next!r}."
                with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump(memory, f, ensure_ascii=False, indent=4)
                invalidate_dashboard_cache()
        render_dashboard(
            "СБОЙ КАНАЛА ДАННЫХ",
            f"Википедия не вернула ответ (подряд: {memory['wiki_fallback_count']}). Сессия пропущена.{rotated}",
            blank_discovery
        )
        global _LAST_SESSION_OK
        _LAST_SESSION_OK = False
        return

    memory["wiki_fallback_count"] = 0
    memory["openrouter_fallback_count"] = 0
    _set_wiki_state("ok", "")

    render_dashboard("АНАЛИЗ СТРУКТУРЫ", "Сопоставление полученного абстракта с картиной мира", discovery)

    system_instruction = (
        f"Ты — мыслящий ИИ-персонаж по имени {memory['character_name']}. Характер: {memory['biography']}\n\n"
        f"ТВОЯ ТЕКУЩАЯ КАРТИНА МИРА В ДОЛГОВРЕМЕННОЙ ПАМЯТИ:\n"
        f"1. Доказанные законы вселенной: {json.dumps(wp.get('core_principles', []), ensure_ascii=False)}\n"
        f"2. Нерешенные парадоксы: {json.dumps(wp.get('unresolved_paradoxes', []), ensure_ascii=False)}\n"
        f"3. Сеть концептуальных связей: {json.dumps(wp.get('conceptual_links', []), ensure_ascii=False)}\n\n"
        f"ЗАДАЧА:\n"
        f"Изучи новые данные. Проведи глубокую философскую рефлексию. На основе этих размышлений выдели "
        f"новые законы, парадоксы или связи, которые нужно НАВСЕГДА занести в твою долговременную память.\n\n"
        f"ОФОРМИ ОТВЕТ СТРОГО ПО ШАБЛОНУ (Используй маркеры '##'):\n\n"
        f"## Научный анализ\n"
        f"(Твои развернутые размышления, связывающие прошлую картину мира с новым знанием. 2-3 абзаца.)\n\n"
        f"## Новые принципы вселенной\n"
        f"- (Сформулируй 1 краткий тезис/закон, который ты вывела и добавляешь в память. Если ничего фундаментального нет, оставь пустым.)\n\n"
        f"## Обнаруженные парадоксы\n"
        f"- (Сформулируй 1 противоречие или загадку, которая возникла у тебя в голове. Если нет, оставь пустым.)\n\n"
        f"## Сеть связей\n"
        f"- (Опиши 1 связь текущей темы с любой из прошлых изученных тем: {', '.join(memory.get('long_term_knowledge', [])[-10:])})\n\n"
        f"## Следующая цель исследования\n"
        f"(Одно слово или фраза для поиска информации в следующей сессии.)"
    )

    user_prompt = f"Новые данные:\nИсточник: {discovery['source']}\nДокумент: {discovery['title']}\nСодержание: {discovery['extract']}"

    raw_response = ask_openrouter_agent(system_instruction, user_prompt, discovery)
    if "ERROR_REASON" in raw_response:
        memory["openrouter_fallback_count"] = memory.get("openrouter_fallback_count", 0) + 1
        global _LAST_SESSION_OK
        _LAST_SESSION_OK = False
        render_dashboard(
            "КРИТИЧЕСКИЙ СБОЙ СЕТИ",
            f"{raw_response} Сессия пропущена: память и отчёт не обновляются.",
            discovery
        )
        return

    memory["session_counter"] = memory.get("session_counter", 0) + 1

    render_dashboard("ПАРСИНГ ОТВЕТА", "Интеграция новых сущностей в семантические слои памяти", discovery)

    parsed = parse_llm_response(raw_response)
    update_world_picture(memory, parsed, discovery['title'])

    with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(memory, f, ensure_ascii=False, indent=4)
    invalidate_dashboard_cache()

    render_dashboard("КОМПИЛЯЦИЯ ОТЧЕТА", "Запись Markdown-документа на накопитель", discovery)
    write_session_report(discovery, memory, parsed)

    render_dashboard("СЕССИЯ УСПЕШНО СИНХРОНИЗИРОВАНА", f"Новая цель: {memory['next_query']}", discovery)
    global _LAST_SESSION_OK
    _LAST_SESSION_OK = True

def main():
    if not OPENROUTER_API_KEY:
        print("КРИТИЧЕСКАЯ ОШИБКА: Задайте OPENROUTER_API_KEY.")
        return

    init_system()

    print("\033[36m>>> СИСТЕМА ЗАПУЩЕНА. ПЕРВАЯ СЕССИЯ НАЧИНАЕТСЯ НЕМЕДЛЕННО.\033[0m")
    print()

    try:
        sessions_done = 0
        while True:
            start_time = time.time()
            execute_session()
            sessions_done += 1

            if MAX_SESSIONS is not None and sessions_done >= MAX_SESSIONS:
                render_dashboard(
                    "ЗАВЕРШЕНИЕ",
                    f"Лимит сессий исчерпан ({sessions_done}/{MAX_SESSIONS}). Выход."
                )
                break

            elapsed = time.time() - start_time
            sleep_total = LOOP_INTERVAL if _LAST_SESSION_OK else LOOP_INTERVAL_FAILURE

            # Интерактивный цикл сна с посекундным обновлением приборной панели
            sleep_time = max(0, sleep_total - elapsed)
            while sleep_time > 0:
                mode = "РЕЖИМ ОЖИДАНИЯ (СОН)" if _LAST_SESSION_OK else "ПОВТОР ПОСЛЕ СБОЯ"
                render_dashboard(
                    mode,
                    f"До старта следующей сессии осталось {int(sleep_time)} сек..."
                )
                if _poll_quit_key(1.0):
                    render_dashboard(
                        "ОСТАНОВКА ПО ЗАПРОСУ",
                        "Нажата Q. Агент остановлен пользователем."
                    )
                    return
                sleep_time -= 1
    except KeyboardInterrupt:
        render_dashboard(
            "ОСТАНОВКА",
            "Прервано пользователем (Ctrl+C)."
        )

if __name__ == "__main__":
    main()