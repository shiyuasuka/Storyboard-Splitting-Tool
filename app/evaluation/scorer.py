from __future__ import annotations

from statistics import mean, pstdev
from typing import Dict, List

from app.models.schemas import EpisodeScript, EvaluationResult, EvaluationScores


class SelfEvaluator:
    def evaluate(self, episodes: List[EpisodeScript], target_duration: int) -> EvaluationResult:
        structure_score = self._structure_completeness(episodes)
        conflict_score = self._conflict_intensity(episodes)
        rhythm_score = self._rhythm_consistency(episodes, target_duration)
        emotion_curve_score = self._emotion_curve_quality(episodes)
        bgm_score = self._bgm_matching_quality(episodes)
        diversity_score = self._shot_diversity(episodes)
        arc_score = self._character_arc_integrity(episodes)
        creativity_score = self._creativity(episodes)

        weighted = (
            structure_score * 0.15
            + conflict_score * 0.15
            + rhythm_score * 0.12
            + emotion_curve_score * 0.12
            + bgm_score * 0.1
            + diversity_score * 0.12
            + arc_score * 0.12
            + creativity_score * 0.12
        )
        scores = EvaluationScores(
            structure_completeness=round(structure_score, 2),
            conflict_intensity=round(conflict_score, 2),
            rhythm_consistency=round(rhythm_score, 2),
            emotion_curve_quality=round(emotion_curve_score, 2),
            bgm_matching_quality=round(bgm_score, 2),
            shot_diversity=round(diversity_score, 2),
            character_arc_integrity=round(arc_score, 2),
            creativity=round(creativity_score, 2),
            total_score=round(weighted, 2),
        )
        explanation = {
            "structure_completeness": "分场和镜头字段完整，且每集时长可校验。" if structure_score >= 8 else "部分字段稀疏，结构完整度下降。",
            "conflict_intensity": "冲突峰值与平均情绪值较高，推进力充足。" if conflict_score >= 7 else "冲突波峰不足，驱动力一般。",
            "rhythm_consistency": "节奏与目标时长偏差小，集内分配稳定。" if rhythm_score >= 7 else "分场时长波动偏大。",
            "emotion_curve_quality": "情绪曲线具有可感知起伏与递进。" if emotion_curve_score >= 7 else "情绪变化过平或突兀。",
            "bgm_matching_quality": "BGM强度与场景情绪匹配。" if bgm_score >= 7 else "BGM强度存在错配。",
            "shot_diversity": "镜头类型分布多样，视觉节奏较好。" if diversity_score >= 7 else "镜头类型重复偏高。",
            "character_arc_integrity": "主要角色跨集出现并形成推进弧线。" if arc_score >= 7 else "角色推进连续性不足。",
            "creativity": "文本表达与组合结构具备新鲜感。" if creativity_score >= 7 else "表达模板化较明显。",
            "total_score": f"综合评分 {round(weighted, 2)} / 10。",
        }
        return EvaluationResult(scores=scores, explanation=explanation)

    def _structure_completeness(self, episodes: List[EpisodeScript]) -> float:
        required = 19
        valid = 0
        total = 0
        for ep in episodes:
            for sc in ep.scenes:
                total += 1
                if sc.shots:
                    shot = sc.shots[0]
                    fields = [
                        ep.episode,
                        sc.scene_id,
                        sc.duration_estimate,
                        sc.time,
                        sc.environment,
                        sc.location,
                        sc.characters,
                        shot.shot_id,
                        shot.camera_type,
                        shot.visual,
                        shot.action,
                        shot.dialogue,
                        shot.os,
                        shot.vo,
                        shot.transition,
                        shot.sfx,
                        shot.source_scene_ref,
                        shot.source_excerpt,
                        shot.adaptation_note,
                    ]
                    valid += sum(1 for x in fields if x is not None)
        return 10 * (valid / max(1, total * required))

    def _conflict_intensity(self, episodes: List[EpisodeScript]) -> float:
        emotions = [sc.emotion_level for ep in episodes for sc in ep.scenes]
        if not emotions:
            return 0.0
        return min(10.0, mean(emotions) * 0.8 + max(emotions) * 0.2)

    def _rhythm_consistency(self, episodes: List[EpisodeScript], target_duration: int) -> float:
        deviations = []
        for ep in episodes:
            actual = sum(sc.duration_estimate for sc in ep.scenes)
            deviations.append(abs(actual - target_duration) / max(1, target_duration))
        avg_dev = mean(deviations) if deviations else 1
        return max(0.0, min(10.0, 10 - avg_dev * 25))

    def _emotion_curve_quality(self, episodes: List[EpisodeScript]) -> float:
        curve = [mean([sc.emotion_level for sc in ep.scenes]) for ep in episodes if ep.scenes]
        if len(curve) < 2:
            return 5.0
        volatility = pstdev(curve)
        trend = sum(1 for i in range(1, len(curve)) if curve[i] >= curve[i - 1]) / (len(curve) - 1)
        return max(0.0, min(10.0, 4 + volatility * 1.2 + trend * 3.0))

    def _bgm_matching_quality(self, episodes: List[EpisodeScript]) -> float:
        score_sum = 0.0
        count = 0
        for ep in episodes:
            for sc in ep.scenes:
                expected = 3 if sc.emotion_level <= 3 else 5 if sc.emotion_level <= 6 else 8
                score_sum += 10 - min(10, abs(sc.bgm.intensity - expected) * 2)
                count += 1
        return score_sum / max(1, count)

    def _shot_diversity(self, episodes: List[EpisodeScript]) -> float:
        cameras = [sh.camera_type for ep in episodes for sc in ep.scenes for sh in sc.shots]
        if not cameras:
            return 0.0
        unique_ratio = len(set(cameras)) / len(cameras)
        return min(10.0, 3 + unique_ratio * 14)

    def _character_arc_integrity(self, episodes: List[EpisodeScript]) -> float:
        by_ep = [{c for sc in ep.scenes for c in sc.characters} for ep in episodes]
        if not by_ep:
            return 0.0
        continuity = 0
        for i in range(1, len(by_ep)):
            overlap = by_ep[i - 1].intersection(by_ep[i])
            continuity += 1 if overlap else 0
        ratio = continuity / max(1, len(by_ep) - 1)
        lead_presence = max((sum(1 for chars in by_ep if lead in chars) for lead in set().union(*by_ep)), default=0)
        lead_ratio = lead_presence / max(1, len(by_ep))
        return min(10.0, 4 + ratio * 3 + lead_ratio * 3)

    def _creativity(self, episodes: List[EpisodeScript]) -> float:
        visuals = [sh.visual for ep in episodes for sc in ep.scenes for sh in sc.shots]
        dialogues = [sh.dialogue for ep in episodes for sc in ep.scenes for sh in sc.shots]
        if not visuals:
            return 0.0
        visual_uniques = len(set(visuals)) / len(visuals)
        dialogue_uniques = len(set(dialogues)) / len(dialogues)
        return min(10.0, 4 + visual_uniques * 3 + dialogue_uniques * 3)


def build_ranking(samples: List[Dict]) -> List[Dict]:
    sorted_samples = sorted(samples, key=lambda x: x["evaluation"]["scores"]["total_score"], reverse=True)
    ranking = []
    for i, item in enumerate(sorted_samples, start=1):
        ranking.append(
            {
                "rank": i,
                "sample_id": item["sample_id"],
                "total_score": item["evaluation"]["scores"]["total_score"],
            }
        )
    return ranking
