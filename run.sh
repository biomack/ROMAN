#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-roman-agent}"
CONTAINER_NAME="${CONTAINER_NAME:-roman-agent-bot}"
ENV_FILE="${ENV_FILE:-.env}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is not installed or not in PATH."
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "Error: env file '$ENV_FILE' not found."
  echo "Create it from example.env, for example:"
  echo "  cp example.env .env"
  exit 1
fi

echo "Building image '$IMAGE_NAME'..."
docker build -t "$IMAGE_NAME" .

echo "Stopping old container '$CONTAINER_NAME' (if exists)..."
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "Starting bot container '$CONTAINER_NAME'..."
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  --env-file "$ENV_FILE" \
  "$IMAGE_NAME" \
  python main.py --mode bot

echo "Container started."
echo "Logs:"
echo "  docker logs -f $CONTAINER_NAME"
