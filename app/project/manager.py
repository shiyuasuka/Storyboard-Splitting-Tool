from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from app.core.config import PROJECT_DATA_DIR
from app.models.schemas import ProjectParams, ProjectRecord


class ProjectManager:
    def __init__(self, storage_dir: Path | None = None) -> None:
        self.storage_dir = storage_dir or PROJECT_DATA_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, ProjectRecord] = {}
        self._load_existing()

    def _record_path(self, project_id: str) -> Path:
        return self.storage_dir / f"{project_id}.json"

    def _load_existing(self) -> None:
        for file in self.storage_dir.glob("*.json"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                record = ProjectRecord.model_validate(data)
                self._cache[record.project_id] = record
            except Exception:
                continue

    def create_project(self, params: ProjectParams, project_id: Optional[str] = None) -> ProjectRecord:
        pid = project_id or f"proj_{uuid4().hex[:10]}"
        now = datetime.utcnow()
        record = ProjectRecord(
            project_id=pid,
            created_at=now,
            updated_at=now,
            params=params,
            samples=[],
            ranking=[],
            generation_logs=[],
        )
        self._cache[pid] = record
        self.save(record)
        return record

    def get_project(self, project_id: str) -> Optional[ProjectRecord]:
        return self._cache.get(project_id)

    def list_projects(self) -> List[ProjectRecord]:
        return sorted(self._cache.values(), key=lambda x: x.updated_at, reverse=True)

    def save(self, record: ProjectRecord) -> None:
        record.updated_at = datetime.utcnow()
        path = self._record_path(record.project_id)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def upsert(self, record: ProjectRecord) -> None:
        self._cache[record.project_id] = record
        self.save(record)
