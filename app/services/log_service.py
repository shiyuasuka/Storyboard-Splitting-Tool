from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import LOG_DIR


class LogService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or LOG_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _log_path(self, project_id: str) -> Path:
        return self.base_dir / f"{project_id}.log"

    def write(self, project_id: str, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        line = {
            "timestamp": datetime.utcnow().isoformat(),
            "event": event,
            "payload": payload,
        }
        with self._log_path(project_id).open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        return line

    def read(self, project_id: str) -> List[Dict[str, Any]]:
        path = self._log_path(project_id)
        if not path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(raw))
            except Exception:
                continue
        return rows
