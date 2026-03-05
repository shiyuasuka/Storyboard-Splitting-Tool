from __future__ import annotations

from typing import List

from app.core.config import CAMERA_TYPES, TRANSITIONS
from app.models.schemas import EpisodeScript, ParsedControlPlan


class ScriptOptimizerService:
    def optimize(
        self,
        episodes: List[EpisodeScript],
        control_plan: ParsedControlPlan,
        suggestions: List[str],
    ) -> List[EpisodeScript]:
        optimized = [EpisodeScript.model_validate(ep.model_dump(mode="json")) for ep in episodes]
        self._stabilize_character_arc(optimized)
        self._align_emotion_and_bgm(optimized, control_plan)
        self._diversify_camera_and_transition(optimized)
        if suggestions:
            self._apply_suggestions_bias(optimized, suggestions)
        return optimized

    def _stabilize_character_arc(self, episodes: List[EpisodeScript]) -> None:
        freq = {}
        for ep in episodes:
            for sc in ep.scenes:
                for c in sc.characters:
                    freq[c] = freq.get(c, 0) + 1
        if not freq:
            return
        lead = max(freq.items(), key=lambda x: x[1])[0]
        for ep in episodes:
            for sc in ep.scenes:
                if lead not in sc.characters:
                    sc.characters = (sc.characters + [lead])[:3]

    def _align_emotion_and_bgm(self, episodes: List[EpisodeScript], control_plan: ParsedControlPlan) -> None:
        target_curve = control_plan.emotion_curve
        for ep_idx, ep in enumerate(episodes):
            target = target_curve[min(ep_idx, len(target_curve) - 1)] if target_curve else 6
            for sc_idx, sc in enumerate(ep.scenes):
                bias = -1 if sc_idx < len(ep.scenes) // 2 else 1
                sc.emotion_level = max(0, min(10, target + bias))
                if sc.emotion_level <= 3:
                    sc.bgm.intensity, sc.bgm.tempo = 3, "慢"
                elif sc.emotion_level <= 6:
                    sc.bgm.intensity, sc.bgm.tempo = 5, "中"
                else:
                    sc.bgm.intensity, sc.bgm.tempo = 8, "快"

    def _diversify_camera_and_transition(self, episodes: List[EpisodeScript]) -> None:
        camera_idx = 0
        trans_idx = 0
        for ep in episodes:
            for sc in ep.scenes:
                for sh in sc.shots:
                    sh.camera_type = CAMERA_TYPES[camera_idx % len(CAMERA_TYPES)]
                    sh.transition = TRANSITIONS[trans_idx % len(TRANSITIONS)]
                    camera_idx += 1
                    trans_idx += 1

    def _apply_suggestions_bias(self, episodes: List[EpisodeScript], suggestions: List[str]) -> None:
        boost_conflict = any("冲突" in s or "对抗" in s for s in suggestions)
        if boost_conflict:
            for ep in episodes:
                for sc in ep.scenes:
                    sc.emotion_level = max(0, min(10, sc.emotion_level + 1))
                    for sh in sc.shots:
                        if sh.dialogue:
                            sh.dialogue = sh.dialogue + " 现在必须正面冲突。"
