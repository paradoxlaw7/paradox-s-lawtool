#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
docker compose exec -T app python - <<'PY'
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
root = Path('/app/data')
target_dir = root / 'backups'
target_dir.mkdir(exist_ok=True)
target = target_dir / ('workspace-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.sqlite3')
source = sqlite3.connect(root / 'workspace.sqlite3')
dest = sqlite3.connect(target)
try:
    source.backup(dest)
finally:
    dest.close()
    source.close()
print('Backup created in persistent volume: ' + target.name)
print('Copy the backup to a separate protected storage location for disaster recovery.')
PY
