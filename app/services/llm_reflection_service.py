from __future__ import annotations

import json
from typing import Dict, List, Tuple

from app.models.schemas import AgentReview, EvaluationResult, EvaluationScores, EpisodeScript
from app.services.llm_client import LLMClientError, OpenAICompatibleLLMClient


class LLMReflectionService:
    def __init__(self) -> None:
        self.client = OpenAICompatibleLLMClient()

    async def reflect_sample(
        self,
        topic: str,
        constraints: Dict,
        novel_context: Dict,
        episodes: List[EpisodeScript],
        sample_id: str,
    ) -> Tuple[EvaluationResult, List[str], Dict[str, int]]:
        digest = self._episodes_digest(episodes)
        src_digest = self._source_digest(novel_context)

        system_prompt = (
            "你是影视工业化总编审智能体。"
            "输出必须是JSON对象，不要输出markdown。"
            "你要进行：质量打分 + 问题诊断 + 下一轮改写建议。"
        )
        user_prompt = (
            f"sample_id:{sample_id}\n"
            f"topic:{topic}\n"
            f"constraints:{json.dumps(constraints, ensure_ascii=False)}\n"
            f"novel_source_digest:{json.dumps(src_digest, ensure_ascii=False)}\n"
            f"script_digest:{json.dumps(digest, ensure_ascii=False)}\n"
            "请输出JSON结构:\n"
            "{\n"
            "  \"scores\": {\n"
            "    \"structure_completeness\":0-10,\n"
            "    \"conflict_intensity\":0-10,\n"
            "    \"rhythm_consistency\":0-10,\n"
            "    \"emotion_curve_quality\":0-10,\n"
            "    \"bgm_matching_quality\":0-10,\n"
            "    \"shot_diversity\":0-10,\n"
            "    \"character_arc_integrity\":0-10,\n"
            "    \"creativity\":0-10,\n"
            "    \"total_score\":0-10\n"
            "  },\n"
            "  \"explanation\": {各维度解释字符串},\n"
            "  \"agent_reviews\": [\n"
            "    {\"agent_name\":\"structure_agent\",\"focus\":\"...\",\"score\":0-10,\"strengths\":[...],\"risks\":[...],\"suggestions\":[...]},\n"
            "    {\"agent_name\":\"conflict_agent\",...},\n"
            "    {\"agent_name\":\"audiovisual_agent\",...},\n"
            "    {\"agent_name\":\"character_agent\",...},\n"
            "    {\"agent_name\":\"innovation_agent\",...},\n"
            "    {\"agent_name\":\"fidelity_agent\",...}\n"
            "  ],\n"
            "  \"revision_plan\": [\"用于下一轮改写的明确指令\", ...]\n"
            "}\n"
            "要求: revision_plan 3-8条，必须具体可执行。"
        )
        result = await self.client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        usage = result.pop("_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

        evaluation = self._coerce_evaluation(result)
        revision_plan = result.get("revision_plan") or []
        if not isinstance(revision_plan, list):
            revision_plan = []
        revision_plan = [str(x) for x in revision_plan if str(x).strip()][:8]
        if not revision_plan:
            revision_plan = ["强化冲突推进并提升原文事件映射准确性"]
        return evaluation, revision_plan, usage

    async def rank_samples(
        self,
        topic: str,
        novel_context: Dict,
        sample_summaries: List[Dict],
    ) -> Tuple[List[Dict], Dict[str, int]]:
        system_prompt = (
            "你是影视项目评审委员会主席。"
            "输出必须是JSON对象，不要输出markdown。"
        )
        user_prompt = (
            f"topic:{topic}\n"
            f"novel_source_digest:{json.dumps(self._source_digest(novel_context), ensure_ascii=False)}\n"
            f"samples:{json.dumps(sample_summaries, ensure_ascii=False)}\n"
            "请输出:\n"
            "{\"ranking\":[{\"sample_id\":\"...\",\"rank\":1,\"total_score\":0-10,\"reason\":\"...\"}, ...]}\n"
            "要求: 包含全部sample_id且不重复。"
        )
        result = await self.client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        usage = result.pop("_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
        ranking = result.get("ranking")
        if not isinstance(ranking, list):
            raise LLMClientError("LLM ranking response missing ranking list")
        out = []
        for item in ranking:
            if not isinstance(item, dict):
                continue
            out.append(
                {
                    "sample_id": str(item.get("sample_id", "")),
                    "rank": self._to_int(item.get("rank"), 0),
                    "total_score": float(item.get("total_score", 0)),
                    "reason": str(item.get("reason", "")),
                }
            )
        return out, usage

    def _coerce_evaluation(self, raw: Dict) -> EvaluationResult:
        scores = raw.get("scores") or {}
        score_obj = EvaluationScores(
            structure_completeness=self._clip(scores.get("structure_completeness", 6.5)),
            conflict_intensity=self._clip(scores.get("conflict_intensity", 6.5)),
            rhythm_consistency=self._clip(scores.get("rhythm_consistency", 6.5)),
            emotion_curve_quality=self._clip(scores.get("emotion_curve_quality", 6.5)),
            bgm_matching_quality=self._clip(scores.get("bgm_matching_quality", 6.5)),
            shot_diversity=self._clip(scores.get("shot_diversity", 6.5)),
            character_arc_integrity=self._clip(scores.get("character_arc_integrity", 6.5)),
            creativity=self._clip(scores.get("creativity", 6.5)),
            total_score=self._clip(scores.get("total_score", 6.5)),
        )

        explanation = raw.get("explanation") or {}
        if not isinstance(explanation, dict):
            explanation = {}
        explanation = {str(k): str(v) for k, v in explanation.items()}
        if "total_score" not in explanation:
            explanation["total_score"] = f"综合评分 {score_obj.total_score}/10"

        raw_agents = raw.get("agent_reviews") or []
        agent_reviews: List[AgentReview] = []
        if isinstance(raw_agents, list):
            for a in raw_agents:
                if not isinstance(a, dict):
                    continue
                agent_reviews.append(
                    AgentReview(
                        agent_name=str(a.get("agent_name", "review_agent")),
                        focus=str(a.get("focus", "质量评审")),
                        score=self._clip(a.get("score", 6.5)),
                        strengths=[str(x) for x in (a.get("strengths") or [])][:6],
                        risks=[str(x) for x in (a.get("risks") or [])][:6],
                        suggestions=[str(x) for x in (a.get("suggestions") or [])][:8],
                    )
                )
        if not agent_reviews:
            agent_reviews = [
                AgentReview(
                    agent_name="review_agent",
                    focus="总体质量",
                    score=score_obj.total_score,
                    strengths=["结构完整"],
                    risks=["可进一步优化节奏"],
                    suggestions=["增加关键场景冲突张力"],
                )
            ]

        return EvaluationResult(scores=score_obj, explanation=explanation, agent_reviews=agent_reviews)

    @staticmethod
    def _episodes_digest(episodes: List[EpisodeScript]) -> List[Dict]:
        data = []
        for ep in episodes:
            scene_briefs = []
            for sc in ep.scenes[:6]:
                refs = [sh.source_scene_ref for sh in sc.shots[:2]]
                scene_briefs.append(
                    {
                        "scene_id": sc.scene_id,
                        "duration": sc.duration_estimate,
                        "emotion": sc.emotion_level,
                        "location": sc.location,
                        "characters": sc.characters,
                        "source_refs": refs,
                    }
                )
            data.append(
                {
                    "episode": ep.episode,
                    "total_duration_estimate": ep.total_duration_estimate,
                    "scene_count": len(ep.scenes),
                    "scene_briefs": scene_briefs,
                }
            )
        return data

    @staticmethod
    def _source_digest(novel_context: Dict) -> Dict:
        return {
            "title": novel_context.get("title", ""),
            "story_map": novel_context.get("story_map", {}),
            "chapter_titles": novel_context.get("chapter_titles", [])[:12],
            "source_scene_count": novel_context.get("source_scene_count", 0),
            "episode_beats": [
                [
                    {
                        "ref": x.get("ref", ""),
                        "summary": x.get("summary", ""),
                    }
                    for x in beat[:4]
                ]
                for beat in (novel_context.get("episode_beats") or [])
            ],
        }

    @staticmethod
    def _clip(v) -> float:
        try:
            f = float(v)
        except Exception:
            f = 6.5
        if f < 0:
            return 0.0
        if f > 10:
            return 10.0
        return round(f, 2)

    @staticmethod
    def _to_int(v, default: int) -> int:
        try:
            return int(v)
        except Exception:
            return default
