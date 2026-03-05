from __future__ import annotations

import re
from typing import Dict, List

from app.models.schemas import EpisodeScript


class NovelService:
    CHAPTER_RE = re.compile(r"^(第[0-9一二三四五六七八九十百千零两]+章|chapter\s*\d+|chap\.?\s*\d+)", re.IGNORECASE)

    def split_chapters(self, content: str) -> List[Dict]:
        lines = content.splitlines()
        chapters: List[Dict] = []
        current_title = "序章"
        buf: List[str] = []

        def flush() -> None:
            text = "\n".join([x for x in buf if x.strip()]).strip()
            if text:
                chapters.append({"title": current_title, "text": text})

        for ln in lines:
            s = ln.strip()
            if not s:
                buf.append(ln)
                continue
            if self.CHAPTER_RE.match(s):
                flush()
                buf.clear()
                current_title = s
                continue
            buf.append(ln)

        flush()
        if not chapters:
            chapters = [{"title": "正文", "text": content.strip()}]

        for i, ch in enumerate(chapters, start=1):
            ch["chapter_id"] = i
            ch["scenes"] = self.split_scenes(ch["text"], chapter_id=i)
        return chapters

    def split_scenes(self, text: str, chapter_id: int, max_chars: int = 420) -> List[Dict]:
        paras = [p.strip() for p in text.splitlines() if p.strip()]
        scenes: List[Dict] = []
        buf = ""
        sid = 1
        for p in paras:
            boundary = any(k in p for k in ["场景", "地点", "转场", "与此同时", "次日", "夜", "晨"])
            if len(buf) + len(p) + 1 <= max_chars and not boundary:
                buf = f"{buf}\n{p}".strip()
            else:
                if buf:
                    scenes.append(self._pack_scene(chapter_id, sid, buf))
                    sid += 1
                buf = p
        if buf:
            scenes.append(self._pack_scene(chapter_id, sid, buf))
        return scenes or [self._pack_scene(chapter_id, 1, text[:max_chars])]

    def _pack_scene(self, chapter_id: int, scene_no: int, raw: str) -> Dict:
        return {
            "scene_no": scene_no,
            "ref": f"C{chapter_id}-S{scene_no}",
            "summary": self._summarize(raw),
            "raw": raw,
            "excerpt": self._excerpt(raw),
        }

    def build_novel_payload(self, title: str, content: str) -> Dict:
        chapters = self.split_chapters(content)
        segments = [sc["raw"] for ch in chapters for sc in ch["scenes"]]
        story_map = self._build_story_map(chapters)
        return {
            "title": (title or "未命名小说").strip() or "未命名小说",
            "content": content,
            "chapters": chapters,
            "segments": segments,
            "story_map": story_map,
            "content_chars": len(content),
        }

    def topic_from_novel(self, novel: Dict) -> str:
        title = novel.get("title", "未命名小说")
        map_data = novel.get("story_map", {})
        conflict = map_data.get("core_conflict", "未知冲突")
        return f"{title}｜核心冲突：{conflict}"

    def build_generation_context(self, novel: Dict, target_episodes: int) -> Dict:
        chapters = novel.get("chapters") or []
        source_scenes: List[Dict] = []
        for ch in chapters:
            for sc in ch.get("scenes", []):
                source_scenes.append(
                    {
                        "ref": sc.get("ref", "C0-S0"),
                        "chapter_id": ch.get("chapter_id", 0),
                        "chapter_title": ch.get("title", ""),
                        "summary": sc.get("summary", ""),
                        "excerpt": sc.get("excerpt", ""),
                    }
                )

        if not source_scenes:
            raw = novel.get("content", "")[:280]
            source_scenes = [
                {
                    "ref": "C0-S1",
                    "chapter_id": 0,
                    "chapter_title": "正文",
                    "summary": self._summarize(raw),
                    "excerpt": self._excerpt(raw),
                }
            ]

        ep_beats = self._partition_source_scenes(source_scenes, max(1, target_episodes))

        return {
            "title": novel.get("title", "未命名小说"),
            "story_map": novel.get("story_map", {}),
            "chapter_titles": [c.get("title", "") for c in chapters],
            "source_scenes": source_scenes,
            "episode_beats": [b[:6] for b in ep_beats],
            "source_scene_count": len(source_scenes),
        }

    def _partition_source_scenes(self, source_scenes: List[Dict], episodes: int) -> List[List[Dict]]:
        if not source_scenes:
            return [[] for _ in range(episodes)]

        total = len(source_scenes)
        if total <= episodes:
            beats = []
            for i in range(episodes):
                beats.append([source_scenes[i % total]])
            return beats

        # Sequential windows preserve original narrative order.
        chunk = (total + episodes - 1) // episodes
        beats: List[List[Dict]] = []
        start = 0
        for _ in range(episodes):
            end = min(total, start + chunk)
            if start >= total:
                beats.append([source_scenes[-1]])
            else:
                beats.append(source_scenes[start:end])
            start = end
        return beats

    def enforce_source_alignment(self, episodes: List[EpisodeScript], novel_context: Dict) -> List[EpisodeScript]:
        source_scenes = (novel_context or {}).get("source_scenes") or []
        episode_beats = (novel_context or {}).get("episode_beats") or []

        if not source_scenes:
            source_scenes = [
                {
                    "ref": "TOPIC-S1",
                    "summary": "topic-derived source",
                    "excerpt": "topic-derived source",
                }
            ]

        for ep_idx, ep in enumerate(episodes):
            beats = episode_beats[ep_idx] if ep_idx < len(episode_beats) and episode_beats[ep_idx] else source_scenes
            for sc_idx, sc in enumerate(ep.scenes):
                src = beats[sc_idx % len(beats)]
                src_ref = src.get("ref", "TOPIC-S1")
                src_summary = src.get("summary", "")
                src_excerpt = src.get("excerpt", "")
                for shot in sc.shots:
                    shot.source_scene_ref = shot.source_scene_ref or src_ref
                    shot.source_excerpt = shot.source_excerpt or src_excerpt
                    shot.adaptation_note = shot.adaptation_note or f"改编自{src_ref}，保留核心事件并镜头化表达"
                    if src_summary and "原著事件" not in shot.visual:
                        shot.visual = f"{shot.visual} 原著事件：{src_summary}"
                    if src_excerpt and "原文线索" not in shot.dialogue:
                        shot.dialogue = f"{shot.dialogue} 原文线索：{src_excerpt[:24]}"
        return episodes

    def source_alignment_report(self, episodes: List[EpisodeScript], novel_context: Dict) -> Dict:
        valid_refs = {s.get("ref") for s in (novel_context.get("source_scenes") or [])}
        total = 0
        mapped = 0
        valid_ref_mapped = 0
        with_excerpt = 0
        for ep in episodes:
            for sc in ep.scenes:
                for sh in sc.shots:
                    total += 1
                    if sh.source_scene_ref and sh.source_excerpt and sh.adaptation_note:
                        mapped += 1
                    if sh.source_scene_ref in valid_refs:
                        valid_ref_mapped += 1
                    if sh.source_excerpt:
                        with_excerpt += 1
        if total == 0:
            return {
                "total_shots": 0,
                "mapped_ratio": 0.0,
                "valid_ref_ratio": 0.0,
                "excerpt_ratio": 0.0,
            }
        return {
            "total_shots": total,
            "mapped_ratio": round(mapped / total, 4),
            "valid_ref_ratio": round(valid_ref_mapped / total, 4),
            "excerpt_ratio": round(with_excerpt / total, 4),
        }

    def _build_story_map(self, chapters: List[Dict]) -> Dict:
        first = chapters[0]["text"] if chapters else ""
        last = chapters[-1]["text"] if chapters else ""
        core_conflict = self._extract_conflict(first + "\n" + last)
        return {
            "core_conflict": core_conflict,
            "opening_hook": self._summarize(first)[:80],
            "closing_hook": self._summarize(last)[:80],
            "chapter_count": len(chapters),
        }

    def _extract_conflict(self, text: str) -> str:
        for token in ["追杀", "背叛", "真相", "阴谋", "误会", "复仇", "失踪", "夺权", "生死"]:
            if token in text:
                return f"围绕{token}展开的高压对抗"
        return "目标与阻碍持续升级的对抗"

    def _excerpt(self, text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        return clean[:72]

    def _summarize(self, text: str) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) <= 90:
            return clean
        return clean[:90] + "..."
