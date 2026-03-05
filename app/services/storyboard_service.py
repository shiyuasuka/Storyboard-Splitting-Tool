from __future__ import annotations

import json
import random
from typing import Dict, List

from app.core.config import BGM_MAP, CAMERA_TYPES, SFX_POOL, TRANSITIONS
from app.models.schemas import BGM, EpisodeScript, ParsedControlPlan, Scene, Shot


class StoryboardGeneratorService:
    def __init__(self) -> None:
        self.location_pool = ["天桥", "地下车库", "旧仓库", "写字楼大厅", "便利店门口", "公寓走廊", "医院电梯口"]
        self.character_pool = ["林岚", "程野", "许默", "周岑", "黎夏", "顾尧"]

    def generate_episodes(
        self,
        topic: str,
        genre: str,
        total_episodes: int,
        episode_duration: int,
        plan: ParsedControlPlan,
        seed: int,
        novel_context: Dict | None = None,
    ) -> List[EpisodeScript]:
        random.seed(seed)
        output: List[EpisodeScript] = []
        ep_beats = (novel_context or {}).get("episode_beats", [])
        for ep in range(1, total_episodes + 1):
            scene_count = random.randint(4, 6)
            scene_durations = self._allocate_durations(episode_duration, scene_count)
            scenes: List[Scene] = []
            base_emotion = plan.emotion_curve[ep - 1]
            episode_beat = ep_beats[ep - 1] if ep - 1 < len(ep_beats) else []

            for s_idx in range(scene_count):
                scene_id = f"{ep}-{s_idx + 1}"
                location = random.choice(self.location_pool)
                environment = "外" if location in {"天桥", "便利店门口"} else "内"
                characters = random.sample(self.character_pool, k=random.randint(2, 3))
                emotion_level = max(0, min(10, base_emotion + random.randint(-2, 2)))
                bgm = self._pick_bgm(emotion_level)
                shots = self._generate_shots(
                    episode=ep,
                    scene_no=s_idx + 1,
                    topic=topic,
                    genre=genre,
                    characters=characters,
                    emotion_level=emotion_level,
                    beat=episode_beat[s_idx % len(episode_beat)] if episode_beat else {},
                )
                scene = Scene(
                    scene_id=scene_id,
                    duration_estimate=scene_durations[s_idx],
                    location=location,
                    time="日" if s_idx % 2 == 0 else "夜",
                    environment=environment,
                    characters=characters,
                    emotion_level=emotion_level,
                    bgm=bgm,
                    shots=shots,
                )
                scenes.append(scene)

            output.append(EpisodeScript(episode=ep, total_duration_estimate=episode_duration, scenes=scenes))
        return output

    def _allocate_durations(self, total: int, count: int) -> List[int]:
        base = [max(8, total // count) for _ in range(count)]
        remain = total - sum(base)
        idx = 0
        while remain > 0:
            base[idx % count] += 1
            remain -= 1
            idx += 1
        while remain < 0:
            if base[idx % count] > 5:
                base[idx % count] -= 1
                remain += 1
            idx += 1
        return base

    def _pick_bgm(self, emotion_level: int) -> BGM:
        key = "low" if emotion_level <= 3 else "mid" if emotion_level <= 6 else "high"
        value = BGM_MAP[key]
        return BGM(type=value["type"], tempo=value["tempo"], intensity=value["intensity"])

    def _generate_shots(
        self,
        episode: int,
        scene_no: int,
        topic: str,
        genre: str,
        characters: List[str],
        emotion_level: int,
        beat: Dict | None = None,
    ) -> List[Shot]:
        shot_count = random.randint(2, 4)
        shots: List[Shot] = []
        beat = beat or {}
        beat_summary = beat.get("summary", "")
        beat_ref = beat.get("ref", "TOPIC-S1")
        beat_excerpt = beat.get("excerpt", "")
        for i in range(shot_count):
            shot_id = f"{episode}-{scene_no}-{i + 1}"
            char_focus = characters[i % len(characters)]
            shot = Shot(
                shot_id=shot_id,
                camera_type=CAMERA_TYPES[(episode + scene_no + i) % len(CAMERA_TYPES)],
                visual=f"{genre}氛围下，{topic}线索在{char_focus}视角中被放大。{(' 原著事件：' + beat_summary) if beat_summary else ''}",
                action=f"{char_focus}停顿后快速转身，尝试确认异动来源。",
                dialogue=f"{char_focus}：" + self._dialogue(topic, emotion_level, i, beat_excerpt),
                os=f"{char_focus}OS：这一步如果错了，后果会失控。" if i == shot_count - 1 else "",
                vo=f"VO：冲突值提升至{emotion_level}，局势逼近临界点。" if i == 0 else "",
                sfx=random.choice(SFX_POOL),
                transition=TRANSITIONS[(i + scene_no) % len(TRANSITIONS)],
                source_scene_ref=beat_ref,
                source_excerpt=beat_excerpt,
                adaptation_note=f"改编自{beat_ref}，将原文片段转化为镜头行动",
            )
            shots.append(shot)
        return shots

    def _dialogue(self, topic: str, emotion_level: int, idx: int, beat_excerpt: str = "") -> str:
        bank = [
            f"{topic}不是巧合，证据链正在闭合。",
            "你现在退出还来得及，但真相会把你拖回来。",
            "别装镇定，我们都听见那一声了。",
            "再给我三十秒，我能把局面翻过来。",
        ]
        line = bank[idx % len(bank)]
        if beat_excerpt:
            line = f"{line} 按原文线索：{beat_excerpt[:26]}"
        suffix = "" if emotion_level < 7 else " 现在没有退路。"
        return line + suffix

    @staticmethod
    def simulate_tokens(episodes: List[EpisodeScript]) -> Dict[str, int]:
        text_size = 0
        for ep in episodes:
            text_size += len(json.dumps(ep.model_dump(mode="json"), ensure_ascii=False))
        prompt_tokens = max(300, text_size // 6)
        completion_tokens = max(900, text_size // 4)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
