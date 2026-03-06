# llm_new_skils

Проект с тремя режимами работы:
1. `CLI` (интерактивный чат, совместим с текущим `main.py`)
2. `REST API` (FastAPI, только enqueue событий)
3. `Worker/Supervisor` (асинхронная обработка и проактивные события)

## Требования

- Python `3.11+`
- `.env` для конфигурации LLM/API/Kafka/Sessions/Mattermost/Supervisor
- Опционально Kafka (для прод-потока)

Установка:

```bash
pip install -r requirements.txt
```

## Режим 1: CLI

Запуск:

```bash
python main.py
```

Полезные флаги:

```bash
python main.py --session-id cli
python main.py --new-session-per-run
```

Команды в CLI:

- `/skills` — список скиллов
- `/load NAME` — загрузить скилл
- `/reset` — сбросить текущую сессию
- `/tools` — какие tools были вызваны в последнем ходе
- `/help`, `/quit`

## Режим 2: REST API

Запуск API:

```bash
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

Эндпоинты:

- `POST /v1/events` — принять `Event` и положить в очередь (`agent-events`)
- `GET /v1/health` — health
- `GET /v1/skills` — доступные скиллы
- `POST /v1/sessions/{session_id}/reset` — сброс сессии (через control event)

Важно: API не вызывает LLM синхронно.

## Режим 3: Worker + Supervisor

Worker читает `agent-events`, вызывает `Agent.chat(...)` по `session_id`,
публикует результат в `agent-outbox`.

```bash
python -m app.worker
```

Supervisor публикует проактивные события по расписанию:

```bash
python -m app.supervisor
```

## Kafka через Docker Compose

```bash
docker compose up --build
```

Поднимаются:

- `zookeeper`
- `kafka`
- `api`
- `worker`

## Сессии

`session_id` определяет историю и активные скиллы:

- хранение в `InMemorySessionStore`
- TTL задается `SESSION_TTL_SECONDS`
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
- вызов идет через `core/mcp_bridge.py` (сейчас stub).

## Mattermost (skeleton)

- `core/mattermost_adapter.py` конвертирует Mattermost payload в `Event`
- отправка ответов в Mattermost вынесена в TODO (через outbox sender)

## Конфигурация `.env`

Ключевые параметры:

- `LLM_PROVIDER`, `OPENAI_BASE_URL`, `OLLAMA_BASE_URL`, ...
- `KAFKA_ENABLED`, `KAFKA_BOOTSTRAP_SERVERS`
- `KAFKA_EVENTS_TOPIC=agent-events`
- `KAFKA_OUTBOX_TOPIC=agent-outbox`
- `API_HOST`, `API_PORT`
- `SESSION_TTL_SECONDS`, `SESSION_MAX_MESSAGES`
- `SUPERVISOR_INTERVAL_SECONDS`, `SUPERVISOR_SERVICES`
