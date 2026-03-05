from __future__ import annotations

from statistics import mean
from typing import List

from app.models.schemas import AgentReview, EpisodeScript, EvaluationResult

from .scorer import SelfEvaluator


class MultiAgentEvaluator:
    def __init__(self) -> None:
        self.base = SelfEvaluator()

    def evaluate(self, episodes: List[EpisodeScript], target_duration: int) -> EvaluationResult:
        result = self.base.evaluate(episodes, target_duration)
        agents = [
            self._structure_agent(episodes, result.scores.structure_completeness, result.scores.rhythm_consistency),
            self._conflict_agent(episodes, result.scores.conflict_intensity, result.scores.emotion_curve_quality),
            self._audiovisual_agent(episodes, result.scores.bgm_matching_quality, result.scores.shot_diversity),
            self._character_agent(episodes, result.scores.character_arc_integrity),
            self._innovation_agent(episodes, result.scores.creativity),
            self._fidelity_agent(episodes),
        ]
        agent_avg = mean([a.score for a in agents]) if agents else 0.0
        result.scores.total_score = round(min(10.0, result.scores.total_score * 0.75 + agent_avg * 0.25), 2)
        result.agent_reviews = agents
        result.explanation["multi_agent"] = f"多智能体综合均分 {round(agent_avg, 2)}，融合后总分 {result.scores.total_score}。"
        return result

    def collect_suggestions(self, evaluation: EvaluationResult) -> List[str]:
        items: List[str] = []
        for agent in evaluation.agent_reviews:
            for s in agent.suggestions:
                if s not in items:
                    items.append(s)
        return items[:8]

    def _structure_agent(self, episodes: List[EpisodeScript], structure: float, rhythm: float) -> AgentReview:
        total_scenes = sum(len(ep.scenes) for ep in episodes)
        risks = [] if total_scenes >= len(episodes) * 4 else ["分场数量偏少，镜头调度空间受限"]
        suggestions = []
        if structure < 8:
            suggestions.append("补齐每场首镜头信息密度，避免空字段")
        if rhythm < 7:
            suggestions.append("将每集末场作为高冲突段，压缩中段冗余时长")
        return AgentReview(
            agent_name="structure_agent",
            focus="三幕结构/节奏控制",
            score=round((structure + rhythm) / 2, 2),
            strengths=["结构字段覆盖高", "时长可核对"],
            risks=risks,
            suggestions=suggestions or ["保持当前结构密度并强化幕间转折点"],
        )

    def _conflict_agent(self, episodes: List[EpisodeScript], conflict: float, emotion: float) -> AgentReview:
        ep_peaks = [max([s.emotion_level for s in ep.scenes], default=0) for ep in episodes]
        risks = ["冲突峰值分布不均"] if len(set(ep_peaks)) <= 2 else []
        suggestions = []
        if conflict < 7:
            suggestions.append("提高关键场景对抗动作与对峙台词强度")
        if emotion < 7:
            suggestions.append("增加情绪波峰波谷，避免连续同强度段")
        return AgentReview(
            agent_name="conflict_agent",
            focus="冲突曲线/情绪曲线",
            score=round((conflict + emotion) / 2, 2),
            strengths=["冲突主轴明确"],
            risks=risks,
            suggestions=suggestions or ["维持冲突节拍，并在终场加入强钩子"],
        )

    def _audiovisual_agent(self, episodes: List[EpisodeScript], bgm: float, shot: float) -> AgentReview:
        sfx_set = {sh.sfx for ep in episodes for sc in ep.scenes for sh in sc.shots}
        risks = ["SFX类型重复偏高"] if len(sfx_set) < 5 else []
        suggestions = []
        if bgm < 7:
            suggestions.append("按情绪强度分层BGM力度，避免反差错配")
        if shot < 7:
            suggestions.append("增加推镜/摇镜/跟拍比例，降低静态镜头重复")
        return AgentReview(
            agent_name="audiovisual_agent",
            focus="视听设计/BGM-SFX/镜头语言",
            score=round((bgm + shot) / 2, 2),
            strengths=["镜头语言具备基础多样性"],
            risks=risks,
            suggestions=suggestions or ["保持视听匹配度并提升音效分层"],
        )

    def _character_agent(self, episodes: List[EpisodeScript], arc: float) -> AgentReview:
        by_ep = [{c for sc in ep.scenes for c in sc.characters} for ep in episodes]
        carry = sum(1 for i in range(1, len(by_ep)) if by_ep[i - 1].intersection(by_ep[i]))
        risks = ["角色跨集连续性不足"] if carry < max(1, len(by_ep) - 2) else []
        suggestions = ["确保核心角色在每集至少一场高权重出场"] if arc < 7 else ["强化关键角色目标变化台词"]
        return AgentReview(
            agent_name="character_agent",
            focus="角色弧线/关系推进",
            score=round(arc, 2),
            strengths=["主角可识别度较高"],
            risks=risks,
            suggestions=suggestions,
        )

    def _innovation_agent(self, episodes: List[EpisodeScript], creativity: float) -> AgentReview:
        transitions = {sh.transition for ep in episodes for sc in ep.scenes for sh in sc.shots}
        risks = ["转场样式单一"] if len(transitions) < 3 else []
        suggestions = ["引入反预期镜头组合与叙事反转点"] if creativity < 7 else ["继续保持表达新鲜度并提高象征性意象"]
        return AgentReview(
            agent_name="innovation_agent",
            focus="创意新颖度/表达差异化",
            score=round(creativity, 2),
            strengths=["具备类型化表达基础"],
            risks=risks,
            suggestions=suggestions,
        )

    def _fidelity_agent(self, episodes: List[EpisodeScript]) -> AgentReview:
        shots = [sh for ep in episodes for sc in ep.scenes for sh in sc.shots]
        if not shots:
            return AgentReview(
                agent_name="fidelity_agent",
                focus="原文映射忠实度",
                score=0.0,
                strengths=[],
                risks=["无镜头可评估"],
                suggestions=["确保每个镜头绑定 source_scene_ref/source_excerpt"],
            )

        mapped = sum(1 for sh in shots if sh.source_scene_ref and sh.source_excerpt)
        referenced = sum(1 for sh in shots if ("原著事件" in sh.visual or "原文线索" in sh.dialogue))
        map_ratio = mapped / len(shots)
        ref_ratio = referenced / len(shots)
        score = min(10.0, 3 + map_ratio * 4 + ref_ratio * 3)
        risks = []
        if map_ratio < 0.98:
            risks.append("存在镜头未绑定原文片段")
        if ref_ratio < 0.9:
            risks.append("镜头文本对原文线索引用不足")
        suggestions = []
        if risks:
            suggestions.append("为每个镜头补齐 source_scene_ref/source_excerpt/adaptation_note")
            suggestions.append("在 visual 或 dialogue 中显式引用对应原文事件")
        else:
            suggestions.append("保持原文-镜头一一映射并继续优化镜头表现力")

        return AgentReview(
            agent_name="fidelity_agent",
            focus="原文映射忠实度",
            score=round(score, 2),
            strengths=["镜头具备可追溯来源"],
            risks=risks,
            suggestions=suggestions,
        )
