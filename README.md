# Agent Skills — CLI

Интерактивный CLI-агент с динамической системой скиллов, работающий через локальный или удалённый LLM.

## Требования

- Python `3.11+`
- `.env` для конфигурации LLM и MCP-серверов (см. `example.env`)

Установка:

```bash
pip install -r requirements.txt
cp example.env .env   # настроить под свой LLM
```

## Запуск

```bash
python main.py
```

Полезные флаги:

```bash
python main.py --provider ollama --model llama3.1
python main.py --provider openai --url http://localhost:1234/v1
python main.py --session-id cli
python main.py --new-session-per-run
```

## Команды в CLI

- `/skills` — список скиллов
- `/load NAME` — загрузить скилл
- `/reset` — сбросить текущую сессию
- `/tools` — какие tools были вызваны в последнем ходе
- `/help`, `/quit`

## Сессии

`session_id` определяет историю и активные скиллы:

- хранение в `InMemorySessionStore`
- TTL задаётся `SESSION_TTL_SECONDS`
- лимит истории — `SESSION_MAX_MESSAGES`

## Формат скилла

Структура:

```
skill-name/
├── SKILL.md          # required
├── tools.py          # optional
├── scripts/          # optional (не загружается в prompt)
├── templates/        # optional (загружается лимитировано)
└── resources/        # optional (загружается лимитировано)
```

`collect_context(...)` — обязательный built-in tool для workflow.

## MCP manifest в `SKILL.md`

Пример frontmatter:

```yaml
---
name: my_skill
description: skill description
mcp:
  server: victoriametrics-mcp
  expose_tools:
    - vm_query_range
    - vm_query_instant
---
```

При `load_skill`:
- читается manifest;
- в агент добавляются только `expose_tools`;
- вызов идёт через `core/mcp_bridge.py`.

## MCP-сервер через Docker Compose

Для локального запуска VictoriaMetrics MCP-сервера:

```bash
docker compose up -d
```

## Конфигурация `.env`

Ключевые параметры:

- `LLM_PROVIDER`, `OPENAI_BASE_URL`, `OLLAMA_BASE_URL`, ...
- `SESSION_TTL_SECONDS`, `SESSION_MAX_MESSAGES`
- `MCP_SERVERS` — список MCP-серверов для подключения

mattermost bot
# Установить новые зависимости
pip install mattermostdriver websockets

# Запустить бота (настройки из .env)
python main.py --mode bot

# Или с переопределением канала
python main.py --mode bot --mm-channel my-channel

Обновлен main.py — добавлен флаг --mode:
--mode cli (по умолчанию) — интерактивный терминал как раньше
--mode bot — запуск как Mattermost бот