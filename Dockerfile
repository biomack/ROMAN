FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

RUN apt-get update && apt-get install -y --no-install-recommends \
    iputils-ping \
    traceroute \
    && rm -rf /var/lib/apt/lists/*

COPY core ./core
COPY skills ./skills
COPY main.py ./
COPY README.md ./

RUN chown -R app:app /app

USER app

CMD ["python", "main.py", "--mode", "bot"]
