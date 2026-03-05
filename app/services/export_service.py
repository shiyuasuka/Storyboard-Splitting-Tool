from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import EXPORT_DIR
from app.models.schemas import ExportResponse, ProjectRecord, SampleOutput


class ExportService:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or EXPORT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def export_bundle(self, project: ProjectRecord) -> Dict[str, str]:
        out_dir = self.base_dir / project.project_id
        out_dir.mkdir(parents=True, exist_ok=True)

        internal_path = out_dir / "internal_production.json"
        arena_path = out_dir / "arena_submission.txt"

        internal_payload = self._build_internal_payload(project)
        internal_path.write_text(json.dumps(internal_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        arena_text = self.render_arena_submission(project)
        arena_path.write_text(arena_text, encoding="utf-8")

        return {
            "internal_production_json": str(internal_path),
            "arena_submission_txt": str(arena_path),
        }

    def export_project(self, project: ProjectRecord, fmt: str = "bundle") -> ExportResponse:
        fmt = (fmt or "bundle").lower()
        now = datetime.utcnow()

        if fmt in {"bundle", "all"}:
            paths = self.export_bundle(project)
            bundle_path = self.base_dir / project.project_id
            return ExportResponse(
                project_id=project.project_id,
                format="bundle",
                export_path=str(bundle_path),
                exported_at=now,
                content=paths,
            )

        if fmt in {"internal", "internal_json", "json"}:
            out_dir = self.base_dir / project.project_id
            out_dir.mkdir(parents=True, exist_ok=True)
            internal_path = out_dir / "internal_production.json"
            payload = self._build_internal_payload(project)
            internal_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return ExportResponse(
                project_id=project.project_id,
                format="internal_json",
                export_path=str(internal_path),
                exported_at=now,
                content=payload,
            )

        if fmt in {"arena", "arena_txt", "txt", "markdown", "md"}:
            out_dir = self.base_dir / project.project_id
            out_dir.mkdir(parents=True, exist_ok=True)
            arena_path = out_dir / "arena_submission.txt"
            text = self.render_arena_submission(project)
            arena_path.write_text(text, encoding="utf-8")
            return ExportResponse(
                project_id=project.project_id,
                format="arena_txt",
                export_path=str(arena_path),
                exported_at=now,
                content=text,
            )

        raise ValueError("unsupported export format")

    def render_arena_submission(self, project: ProjectRecord) -> str:
        ranked_ids = [r.sample_id for r in sorted(project.ranking, key=lambda x: x.rank)] if project.ranking else []
        sample_map = {s.sample_id: s for s in project.samples}
        ordered_samples: List[SampleOutput] = []

        for sid in ranked_ids:
            s = sample_map.get(sid)
            if s:
                ordered_samples.append(s)
        if not ordered_samples:
            ordered_samples = list(project.samples)

        lines: List[str] = []
        title = (project.novel or {}).get("title") or project.params.topic
        lines.append(f"《{title}》外部评审阅读稿")
        lines.append("")

        for idx, sample in enumerate(ordered_samples, start=1):
            lines.append(f"========== 样本{idx} ==========")
            lines.append("")
            lines.extend(self._render_sample_readable(sample))
            lines.append("")

        return "\n".join(lines).strip() + "\n"

    def render_sample_readable(self, sample: SampleOutput) -> str:
        return "\n".join(self._render_sample_readable(sample))

    def _render_sample_readable(self, sample: SampleOutput) -> List[str]:
        lines: List[str] = []
        for ep in sample.episodes:
            lines.append(f"第{ep.episode}集")
            lines.append("")
            for scene_index, sc in enumerate(ep.scenes, start=1):
                chars = "、".join(sc.characters) if sc.characters else "无"
                lines.append(f"场景{scene_index}  {sc.time}  {'内景' if sc.environment == '内' else '外景'}  {sc.location}")
                lines.append(f"人物：{chars}")
                lines.append(f"配乐：{sc.bgm.type}（{self._tempo_cn(sc.bgm.tempo)}）")
                lines.append("")
                for shot_index, sh in enumerate(sc.shots, start=1):
                    lines.append(f"镜头{shot_index}｜{self._camera_cn(sh.camera_type)}")
                    lines.append(f"画面：{self._clean_text(sh.visual)}")
                    lines.append(f"动作：{self._clean_text(sh.action)}")
                    if sh.dialogue:
                        lines.append(f"台词：{self._clean_text(sh.dialogue)}")
                    if sh.os:
                        lines.append(f"内心：{self._clean_text(sh.os)}")
                    if sh.vo:
                        lines.append(f"旁白：{self._clean_text(sh.vo)}")
                    if sh.sfx:
                        lines.append(f"音效：{self._clean_text(sh.sfx)}")
                    lines.append(f"转场：{self._transition_cn(sh.transition)}")
                    lines.append("")
            lines.append("")
        return lines

    def _build_internal_payload(self, project: ProjectRecord) -> Dict[str, Any]:
        return {
            "project_id": project.project_id,
            "params": project.params.model_dump(mode="json"),
            "novel": project.novel,
            "samples": [s.model_dump(mode="json") for s in project.samples],
            "ranking": [r.model_dump(mode="json") for r in project.ranking],
            "generation_logs": project.generation_logs,
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""
        # 隐藏算法/结构痕迹
        for token in ["原著事件：", "原文线索：", "改编自", "source_scene_ref", "source_excerpt", "adaptation_note"]:
            t = t.replace(token, "")
        return " ".join(t.split())

    @staticmethod
    def _tempo_cn(tempo: str) -> str:
        m = {"快": "快板", "中": "中板", "慢": "慢板", "fast": "快板", "medium": "中板", "slow": "慢板"}
        return m.get((tempo or "").strip().lower(), tempo or "中板")

    @staticmethod
    def _camera_cn(camera: str) -> str:
        mapping = {
            "close-up": "特写",
            "medium": "中景",
            "long shot": "远景",
            "tracking": "跟拍",
            "pan": "摇镜",
            "push": "推镜",
        }
        key = (camera or "").strip().lower()
        return mapping.get(key, camera or "中景")

    @staticmethod
    def _transition_cn(trans: str) -> str:
        mapping = {"cut": "切", "fade in": "淡入", "fade out": "淡出", "flashback": "闪回", "dissolve": "叠化"}
        key = (trans or "").strip().lower()
        return mapping.get(key, trans or "切")
