#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -f .env ]]; then
  echo 'Create .env from .env.deploy.example and fill the access password and model key.' >&2
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo 'Install Docker and Docker Compose using the official instructions first.' >&2
  exit 1
fi
docker compose config --quiet
docker compose up -d --build --wait --wait-timeout 120
echo 'Containers started. Check https://idzlawr.cn after DNS is configured.'
echo 'A successful container start does not verify public DNS, TLS or live AI access.'
