from __future__ import annotations

from typing import List

from app.models.schemas import Constraints, ParsedControlPlan, RhythmNode


class TopicParserService:
    def parse(self, topic: str, constraints: Constraints) -> ParsedControlPlan:
        episodes = constraints.episodes
        conflict_curve = self._build_curve(constraints.conflict_level, episodes, constraints.intensity_curve_style.value)
        emotion_curve = self._build_curve(max(constraints.conflict_level - 1, 0), episodes, constraints.intensity_curve_style.value)
        three_act = self._build_three_act(topic, constraints, conflict_curve)
        payoffs = self._build_payoffs(episodes)
        rhythm = self._build_rhythm_table(episodes, conflict_curve, emotion_curve, payoffs)
        return ParsedControlPlan(
            three_act_structure=three_act,
            conflict_curve=conflict_curve,
            emotion_curve=emotion_curve,
            payoff_distribution=payoffs,
            rhythm_table=rhythm,
        )

    def _build_curve(self, base_level: int, episodes: int, style: str) -> List[int]:
        curve: List[int] = []
        for i in range(episodes):
            ratio = i / max(episodes - 1, 1)
            if style == "线性":
                val = round(base_level * (0.7 + 0.3 * ratio))
            elif style == "波浪式":
                wave = 1 if i % 2 == 0 else -1
                val = base_level + wave * 2
            else:
                val = round(base_level * (0.55 + 0.45 * (ratio**1.2))) + (1 if i >= episodes // 2 else 0)
            curve.append(max(0, min(10, val)))
        return curve

    def _build_three_act(self, topic: str, constraints: Constraints, curve: List[int]):
        return [
            {
                "act": 1,
                "name": "建立",
                "goal": f"建立{topic}核心命题与人物动机",
                "target_conflict": curve[max(0, len(curve) // 4 - 1)],
            },
            {
                "act": 2,
                "name": "对抗",
                "goal": "冲突升级、误判与反转叠加",
                "target_conflict": curve[max(0, len(curve) // 2)],
            },
            {
                "act": 3,
                "name": "决断",
                "goal": "核心抉择与代价兑现",
                "target_conflict": curve[-1],
            },
        ]

    def _build_payoffs(self, episodes: int) -> List[str]:
        templates = ["身份揭示", "资源逆转", "关系破裂", "局势翻盘", "代价落地", "终局钩子"]
        return [templates[i % len(templates)] for i in range(episodes)]

    def _build_rhythm_table(
        self,
        episodes: int,
        conflict_curve: List[int],
        emotion_curve: List[int],
        payoffs: List[str],
    ) -> List[RhythmNode]:
        nodes: List[RhythmNode] = []
        for ep in range(1, episodes + 1):
            act = 1 if ep <= max(1, episodes // 3) else 2 if ep <= max(2, episodes * 2 // 3) else 3
            nodes.append(
                RhythmNode(
                    episode=ep,
                    act=act,
                    target_emotion=emotion_curve[ep - 1],
                    conflict=conflict_curve[ep - 1],
                    payoff=payoffs[ep - 1],
                )
            )
        return nodes
