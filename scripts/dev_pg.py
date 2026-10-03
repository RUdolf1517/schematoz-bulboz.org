"""Локальный PostgreSQL 16 без Docker (pip install pgserver). Печатает DATABASE_URL."""
import sys
from pathlib import Path

import pgserver

data = Path(sys.argv[1] if len(sys.argv) > 1 else ".pgdata").resolve()
srv = pgserver.get_server(str(data), cleanup_mode=None)
uri = srv.get_uri()  # postgresql://postgres:@/postgres?host=/tmp/...
print(uri.replace("postgresql://", "postgresql+asyncpg://", 1))
