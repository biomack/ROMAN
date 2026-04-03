# ROMAN — Reasoning-Oriented Multi-skill Agent Navigator

ROMAN — это AI-агент на Python с динамической системой skills. Он работает через OpenAI-compatible LLM API, умеет подгружать специализированные навыки по запросу и запускаться в двух режимах:

- интерактивный CLI
- бот для Mattermost

Проект подходит для сценариев, где одной общей модели недостаточно и нужны прикладные инструменты: работа с документацией, NetBox, сетевой диагностикой, установкой `node_exporter` и другими domain-specific skills.

## Возможности

- запуск в интерактивном терминале
- работа в режиме Mattermost-бота
- динамическая загрузка skills по запросу модели
- tool-calling через OpenAI-compatible API
- хранение состояния диалога между сообщениями
- ограничение размера reference-файлов для skills
- подключение специализированных инструментов без изменения ядра агента
- встроенные Prometheus-метрики (LLM usage, токены, latency, uptime)

## Как это работает

При старте агент:

1. Загружает конфигурацию из `.env`
2. Сканирует каталог `skills/`
3. Читает только метаданные skills из `SKILL.md`
4. Передает модели каталог доступных skills
5. При необходимости модель вызывает `load_skill`
6. После загрузки skill агент получает:
   - полные инструкции из `SKILL.md`
   - дополнительные reference-файлы
   - Python-инструменты из `tools.py`

Таким образом, агент не держит все инструкции и инструменты в контексте сразу, а подключает их по мере необходимости.

## Встроенные skills

На текущий момент в проекте есть следующие skills:

- `acp-docs-qa` — ответы по документации ACP/XaaS из Git-репозитория с retrieval-пайплайном
- `netbox` — запросы к NetBox через MCP server
- `server_diagnostics` — проверка доступности серверов, ping, traceroute, SSH, открытые порты
- `install-node-exporter` — установка Prometheus Node Exporter на Linux-серверы через Ansible

## Требования

- Python 3.11+
- доступ к OpenAI-compatible API
- при использовании Mattermost bot mode:
  - доступ к Mattermost
  - токен бота или personal access token
- при использовании отдельных skills:
  - дополнительные внешние сервисы, например NetBox MCP, Git с документацией, SSH-доступ к серверам и т.д.

## Установка

### 1. Клонирование проекта

```bash
git clone <repo-url>
cd ROMAN
```

### 2. Установка зависимостей

Рекомендуется использовать виртуальное окружение.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Конфигурация

Проект читает настройки из файла `.env`.

Создайте `.env` на основе `example.env` и заполните нужные значения.

### Основные переменные

```env
LLM_PROVIDER=openai
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_MODEL=openai/gpt-oss-20b
OPENAI_API_KEY=lm-studio
OPENAI_TIMEOUT_SECONDS=1200

LLM_TEMPERATURE=0.4
SKILLS_DIR=skills

SESSION_TTL_SECONDS=3600
SESSION_MAX_MESSAGES=100
REFERENCE_FILE_MAX_BYTES=32768
REFERENCE_FILES_TOTAL_MAX_BYTES=262144

PROMETHEUS_METRICS_ENABLED=true
PROMETHEUS_METRICS_HOST=0.0.0.0
PROMETHEUS_METRICS_PORT=9108
```

### Mattermost

Нужны только для режима `--mode bot`.

```env
MATTERMOST_URL=im.example.com
MATTERMOST_TOKEN=your_token
MATTERMOST_TEAM=your_team
MATTERMOST_CHANNEL=your_channel
MATTERMOST_BOT_NAME=roman-bot
MATTERMOST_THREAD_HISTORY_DEPTH=20
```

### NetBox skill

```env
NETBOX_MCP_URL=http://localhost:8000/mcp
NETBOX_LLM_URL=http://localhost:1234/v1
NETBOX_LLM_MODEL=openai/gpt-oss-20b
NETBOX_MAX_TOOL_ROUNDS=20
NETBOX_MAX_IDENTICAL_TOOL_CALLS=3
```

### ACP Docs QA skill

```env
ACP_DOCS_REPO_URL=https://example.git
ACP_DOCS_GIT_USERNAME=readonly-user
ACP_DOCS_GIT_TOKEN=
ACP_DOCS_LOCAL_REPO_DIR=.cache/acp-docs-repo
ACP_DOCS_INDEX_CACHE_DIR=.cache/acp-docs-index
ACP_DOCS_DOCS_SUBDIR=docs
ACP_DOCS_TOP_K=5
ACP_DOCS_MIN_SCORE=0.20
ACP_DOCS_LLM_MAX_TOKENS=1000
```

### Примечание по безопасности

Не храните реальные токены и пароли в публичном репозитории. Для production лучше передавать секреты через переменные окружения, Secret Manager или CI/CD secrets.

## Режимы работы

### CLI режим

CLI-режим запускается по умолчанию:

```bash
python main.py
```

Это интерактивный чат в терминале. После старта агент:

- подключается к LLM
- показывает найденные skills
- создает или использует текущую сессию
- принимает сообщения пользователя в цикле

Поддерживаются служебные команды:

- `/skills` — показать список skills и их статус
- `/load NAME` — вручную загрузить skill
- `/reset` — очистить историю текущей сессии
- `/tools` — показать инструменты, вызванные в последнем ходе
- `/help` — показать справку
- `/quit` — выйти

Полезные примеры запуска:

```bash
python main.py --provider openai --url http://localhost:1234/v1 --model openai/gpt-oss-20b
python main.py --session-id my-session
python main.py --new-session-per-run
```

Когда использовать CLI:

- локальная отладка агента
- тестирование новых skills
- ручная работа с инструментами и проверка ответов модели

### Bot режим

Bot-режим запускает Mattermost-бота:

```bash
python main.py --mode bot
```

В этом режиме агент:

- подключается к той же LLM-модели
- использует ту же систему skills
- слушает указанный Mattermost-канал
- отвечает от имени бота
- может учитывать глубину истории треда через `MATTERMOST_THREAD_HISTORY_DEPTH`

Дополнительно можно переопределить настройки через аргументы:

```bash
python main.py --mode bot --mm-token <token> --mm-channel <channel>
```

Для режима `bot` обязательно должны быть заданы:

- `MATTERMOST_TOKEN`
- `MATTERMOST_URL`
- `MATTERMOST_TEAM`
- `MATTERMOST_CHANNEL`

Когда использовать bot mode:

- для работы команды через Mattermost
- для постоянного доступа к агенту из чата
- для автоматизации типовых инфраструктурных запросов

## Аргументы командной строки

Поддерживаются следующие ключи:

- `--provider` — провайдер LLM
- `--model` — имя модели
- `--url` — базовый URL OpenAI-compatible API
- `--api-key` — API key
- `--skills-dir` — путь к каталогу skills
- `--session-id` — идентификатор сессии
- `--new-session-per-run` — создавать новую CLI-сессию при каждом запуске
- `--mode` — `cli` или `bot`
- `--mm-token` — переопределить `MATTERMOST_TOKEN`
- `--mm-channel` — переопределить `MATTERMOST_CHANNEL`

## Примеры использования

### Пример 1. Обычный диалог

```text
You> Привет, чем ты умеешь помогать?
```

### Пример 2. Работа с документацией

```text
You> Как настроить ACP/XaaS по документации?
```

Агент должен подгрузить `acp-docs-qa` и ответить на основании найденных документов.

### Пример 3. Работа с NetBox

```text
You> Покажи интерфейсы устройства leaf-01 в NetBox
```

### Пример 4. Диагностика сервера

```text
You> Проверь доступность 10.10.10.5
```

### Пример 5. Установка Node Exporter

```text
You> Установи node_exporter на 10.0.0.10 и 10.0.0.11, логин admin
```

Если не хватает данных, агент должен запросить уточнение.

## Как добавить новый skill

Чтобы добавить новый skill, создайте новый каталог внутри `skills/`.

Минимальная структура:

```text
skills/
└── my-skill/
    ├── SKILL.md
    └── tools.py
```

### 1. Создайте `SKILL.md`

Файл должен содержать frontmatter с метаданными и далее инструкции для модели.

Пример:

```md
---
name: my-skill
description: Выполняет специализированную задачу для агента.
aliases:
  - my_skill
  - мой-скилл
---

# My Skill

## Workflow

1. Сначала вызови `collect_context`.
2. Если не хватает данных, задай уточняющий вопрос.
3. Затем вызови нужный инструмент.
4. Сформируй итоговый ответ для пользователя.
```

Что важно:

- `name` должен быть уникальным
- `description` попадет в каталог skills, который видит модель
- `aliases` необязательны, но удобны для альтернативных имен
- основной текст после frontmatter — это полные инструкции skill для модели

### 2. Создайте `tools.py`

В `tools.py` размещаются Python-функции, которые агент сможет вызывать как инструменты.

Инструменты регистрируются через декоратор `@tool`.

Пример:

```python
from typing import Annotated

from core.tool_registry import tool


@tool("Проверяет статус сервиса")
def check_service(
    name: Annotated[str, "Имя сервиса"],
) -> str:
    return f"Service {name} is OK"
```

Важно:

- имя функции становится именем инструмента
- описание из `@tool(...)` показывается модели
- JSON schema параметров строится автоматически по сигнатуре функции
- для пояснения параметров удобно использовать `Annotated`

### 3. При необходимости добавьте reference-файлы

SkillManager автоматически подгружает небольшие текстовые файлы из каталогов:

- `resources/`
- `references/`
- `templates/`
- `assets/`

Это удобно для:

- шаблонов команд
- playbook-файлов
- справочных инструкций
- текстовых ресурсов, которые нужны skill во время работы

### 4. Добавьте переменные окружения

Если skill зависит от внешних сервисов или секретов:

1. добавьте новые переменные в `example.env`
2. опишите их в `SKILL.md`
3. считывайте их в коде через `os.getenv(...)`

### 5. Перезапустите агент

После добавления нового каталога в `skills/` агент обнаружит его автоматически при следующем запуске.

## Docker

В проекте есть `Dockerfile`.

### Сборка образа

```bash
docker build -t roman-agent .
```

### Запуск контейнера

```bash
docker run --rm -it --env-file .env roman-agent
```

По умолчанию контейнер запускает:

```bash
python main.py --mode bot
```

Если нужен CLI-режим, можно переопределить команду:

```bash
docker run --rm -it --env-file .env roman-agent python main.py
```

## Структура проекта

```text
ROMAN/
├── core/
│   ├── agent.py
│   ├── config.py
│   ├── llm_client.py
│   ├── mattermost_bot.py
│   ├── session_store.py
│   ├── skill_manager.py
│   └── tool_registry.py
├── skills/
│   ├── acp-docs-qa/
│   ├── netbox/
│   ├── server_diagnostics/
│   └── install_node_exporter/
├── main.py
├── requirements.txt
├── Dockerfile
├── example.env
└── README.md
```

## Логи

Приложение пишет debug-лог в файл:

```text
agent_debug.log
```

Это полезно для разбора ошибок tool-calling, проблем с моделью и отладки skills.

## Prometheus метрики и Grafana

Агент поднимает endpoint метрик в формате Prometheus через встроенный HTTP-сервер:

- URL: `http://<host>:<PROMETHEUS_METRICS_PORT>/metrics`
- по умолчанию: `http://0.0.0.0:9108/metrics`

### Ключевые метрики

- `roman_agent_user_response_tokens_total` — сколько токенов ушло на финальные ответы пользователям
- `roman_agent_llm_tokens_total{token_type="total"}` — суммарные токены за все время работы процесса
- `roman_agent_uptime_seconds` — аптайм процесса
- `roman_agent_user_response_duration_seconds` — время ответа пользователю (end-to-end)
- `roman_agent_llm_request_duration_seconds` — latency запросов к LLM API
- `roman_agent_llm_requests_total` — количество запросов к LLM (ok/error)
- `roman_agent_tool_calls_total` — статистика вызовов инструментов
- `roman_agent_active_sessions` — активные сессии в памяти
- `roman_agent_errors_total` — ошибки по компонентам

### Дашборд Grafana

Готовый dashboard JSON уже добавлен в репозиторий:

- `grafana-roman-agent-dashboard.json`

Импорт:

1. В Grafana: **Dashboards -> New -> Import**
2. Загрузить файл `grafana-roman-agent-dashboard.json`
3. Выбрать Prometheus datasource
4. Использовать фильтры `provider`, `model`, `source`

## Возможные проблемы

### Агент не подключается к модели

Проверьте:

- `OPENAI_BASE_URL`
- доступность endpoint `/models`
- корректность `OPENAI_API_KEY`
- имя модели в `OPENAI_MODEL`

### Не запускается Mattermost bot

Проверьте:

- `MATTERMOST_TOKEN`
- `MATTERMOST_URL`
- `MATTERMOST_TEAM`
- `MATTERMOST_CHANNEL`

### Skill не работает

Проверьте:

- заполнены ли его переменные окружения
- доступен ли внешний сервис, от которого он зависит
- есть ли необходимые системные утилиты
- что в `skills/<skill-name>/` присутствуют `SKILL.md` и при необходимости `tools.py`

## Расширение проекта

Чтобы добавить новый skill:

1. Создайте каталог в `skills/`
2. Добавьте `SKILL.md` с frontmatter:
   - `name`
   - `description`
   - при необходимости `aliases`
3. Добавьте `tools.py` с функциями-инструментами
4. При необходимости положите reference-файлы в:
   - `resources/`
   - `references/`
   - `templates/`
   - `assets/`

После этого skill будет автоматически обнаружен при запуске агента.

## Лицензия

Добавьте здесь используемую лицензию проекта, если она определена.
