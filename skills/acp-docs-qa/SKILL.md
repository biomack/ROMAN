---
name: acp-docs-qa
description: Retrieval-first QA over ACP/XaaS markdown documentation from Gitea. Use when user asks platform or docs questions in Russian about ACP, XaaS, user guides, CI/CD, mkdocs, or UML generation.
aliases:
  - acp_docs_qa
  - acp-docs
  - xaas-docs
---

# ACP/XaaS Docs QA

Отвечает на вопросы по документации ACP/XaaS, хранящейся в Git-репозитории Markdown.

## Workflow

1. Вызови `ask_acp_docs(query)`.
2. Инструмент синхронизирует git-репозиторий документации.
3. Markdown-файлы разбиваются на чанки по заголовкам `#`, `##`, `###`.
4. Чанки индексируются в FAISS через эмбеддинги.
5. Выполняется semantic search top-k релевантных чанков.
6. LLM получает только вопрос и найденный контекст и формирует ответ на русском.

## Обязательные правила ответа

- Не придумывать информацию.
- Если ответа нет в контексте: `Ответ не найден в документации`.
- Если в контексте есть команды или пошаговые действия, включать их в ответ.
- Не использовать внешние знания вне найденных документов.
- Формат ответа всегда:

```text
Краткий ответ:
<1-2 предложения>

Подробности:
<развернутое объяснение>

Пример:
<команды/пример или "Нет примера">

Источник:
<файл и раздел документации>
```

## Переменные окружения

- `ACP_DOCS_REPO_URL` — URL git-репозитория документации
- `ACP_DOCS_GIT_USERNAME` — username для read-only доступа
- `ACP_DOCS_GIT_TOKEN` — токен/пароль для read-only доступа
- `ACP_DOCS_LOCAL_REPO_DIR` — локальный каталог clone/fetch
- `ACP_DOCS_INDEX_CACHE_DIR` — каталог для FAISS/metadata cache
- `ACP_DOCS_DOCS_SUBDIR` — подкаталог docs внутри репозитория (по умолчанию `docs`)
- `ACP_DOCS_TOP_K` — количество чанков для retrieval
- `ACP_DOCS_MIN_SCORE` — порог релевантности
- `OPENAI_BASE_URL` — URL OpenAI-compatible сервера (используется общий .env)
- `OPENAI_MODEL` — модель LLM (используется общий .env)
- `OPENAI_API_KEY` — API ключ OpenAI-compatible провайдера (если требуется)
- `ACP_DOCS_LLM_MAX_TOKENS` — лимит токенов ответа

Примечание: отдельная embedding-модель не обязательна. Если `ACP_DOCS_EMBEDDING_MODEL` не задана, используется fallback retrieval без эмбеддингов.

## Файлы реализации

- `tools.py` — инструмент skill для агента
- `qa_service.py` — метод `ask(query: str) -> str`
- `retrieval.py` — загрузка docs, chunking, embeddings, FAISS, semantic search
- `llm_client.py` — генерация ответа строго по контексту
- `example.py` — пример локального запуска
