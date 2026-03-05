from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional
from uuid import uuid4

from app.core.config import DEFAULT_PROMPT_VERSION, DEFAULT_STRATEGY_VERSION
from app.models.schemas import (
    GenerateBatchRequest,
    GenerateBatchResponse,
    OptimizationTrace,
    ProjectParams,
    RankingItem,
    SampleOutput,
)
from app.project.manager import ProjectManager
from app.services.llm_client import LLMClientError
from app.services.llm_limiter import LLMConcurrencyLimiter
from app.services.llm_reflection_service import LLMReflectionService
from app.services.llm_story_service import LLMStoryboardService
from app.services.log_service import LogService
from app.services.novel_service import NovelService
from app.services.parser_service import TopicParserService
from app.services.export_service import ExportService


class GenerationOrchestrator:
    def __init__(self, project_manager: ProjectManager, log_service: LogService, export_service: ExportService) -> None:
        self.project_manager = project_manager
        self.log_service = log_service
        self.export_service = export_service
        self.parser = TopicParserService()
        self.novel_service = NovelService()
        self.llm_storyboard: LLMStoryboardService | None = None
        self.llm_reflector: LLMReflectionService | None = None
        self.llm_limiter = LLMConcurrencyLimiter()

    async def generate_batch(self, req: GenerateBatchRequest) -> GenerateBatchResponse:
        return await self.generate_batch_with_progress(req=req, progress_cb=None)

    async def generate_batch_with_progress(
        self,
        req: GenerateBatchRequest,
        progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
    ) -> GenerateBatchResponse:
        project = self.project_manager.get_project(req.project_id) if req.project_id else None
        if not req.use_llm:
            raise ValueError("Only LLM API generation is supported. Set use_llm=true.")
        if project is None:
            raise ValueError("project_id is required and must exist. Please ingest novel text first.")
        if not project.novel:
            raise ValueError("No novel text found in this project. Please call /novel/ingest_text first.")

        topic = self.novel_service.topic_from_novel(project.novel)
        params = ProjectParams(
            topic=topic,
            constraints=req.constraints,
            prompt_version=req.prompt_version or DEFAULT_PROMPT_VERSION,
            strategy_version=req.strategy_version or DEFAULT_STRATEGY_VERSION,
        )
        project.params = params

        novel_context = self.novel_service.build_generation_context(project.novel, req.constraints.episodes)
        control_plan = self.parser.parse(topic, req.constraints)

        self.log_service.write(
            project.project_id,
            "batch_started",
            {
                **req.model_dump(mode="json"),
                "novel_context_meta": {
                    "source_scene_count": novel_context.get("source_scene_count", 0),
                    "chapter_count": len(novel_context.get("chapter_titles", [])),
                },
            },
        )
        await self._emit_progress(
            progress_cb,
            {
                "stage": "batch_started",
                "project_id": project.project_id,
                "batch_size": req.batch_size,
                "episodes": req.constraints.episodes,
            },
        )

        samples: List[SampleOutput] = []
        for idx in range(req.batch_size):
            sample = await self.llm_limiter.run(
                self._generate_one_sample_with_retry(
                    project_id=project.project_id,
                    req=req,
                    control_plan=control_plan,
                    sample_index=idx,
                    topic=topic,
                    novel_context=novel_context,
                    progress_cb=progress_cb,
                )
            )
            samples.append(sample)

        ranking, ranking_reasons, rank_usage = await self._rank_samples_with_llm(topic, novel_context, samples)
        self.log_service.write(
            project.project_id,
            "llm_ranking_completed",
            {"ranking": [r.model_dump(mode="json") for r in ranking], "reasons": ranking_reasons, "usage": rank_usage},
        )
        await self._emit_progress(
            progress_cb,
            {
                "stage": "ranking_completed",
                "project_id": project.project_id,
                "ranking": [r.model_dump(mode="json") for r in ranking],
            },
        )

        project.samples = samples
        project.ranking = ranking
        project.generation_logs = self.log_service.read(project.project_id)
        self.project_manager.upsert(project)
        self.log_service.write(
            project.project_id,
            "batch_completed",
            {
                "sample_count": len(samples),
                "ranking": [r.model_dump(mode="json") for r in ranking],
            },
        )
        await self._emit_progress(
            progress_cb,
            {
                "stage": "batch_completed",
                "project_id": project.project_id,
                "sample_count": len(samples),
            },
        )

        logs = self.log_service.read(project.project_id)
        project.generation_logs = logs
        self.project_manager.upsert(project)
        auto_exports = self.export_service.export_bundle(project)
        self.log_service.write(project.project_id, "exports_generated", auto_exports)
        logs = self.log_service.read(project.project_id)
        project.generation_logs = logs
        self.project_manager.upsert(project)

        return GenerateBatchResponse(
            project_id=project.project_id,
            created_at=datetime.utcnow(),
            params=project.params,
            sample_count=len(samples),
            samples=samples,
            ranking=ranking,
            generation_logs=logs,
            auto_exports=auto_exports,
        )

    async def _generate_one_sample(
        self,
        project_id: str,
        req: GenerateBatchRequest,
        control_plan,
        sample_index: int,
        topic: str,
        novel_context: Dict,
        progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
    ) -> SampleOutput:
        await asyncio.sleep(0)
        sid = f"sample_{sample_index + 1}_{uuid4().hex[:8]}"
        await self._emit_progress(
            progress_cb,
            {"stage": "sample_started", "project_id": project_id, "sample_index": sample_index + 1, "sample_id": sid},
        )

        if self.llm_storyboard is None:
            self.llm_storyboard = LLMStoryboardService()
        if self.llm_reflector is None:
            self.llm_reflector = LLMReflectionService()

        # Round 0: LLM draft
        draft_eps, usage_gen_0 = await self.llm_storyboard.generate_episodes(
            topic=topic,
            constraints=req.constraints,
            control_plan=control_plan,
            sample_index=sample_index,
            novel_context=novel_context,
        )
        draft_eps = self.novel_service.enforce_source_alignment(draft_eps, novel_context)

        eval_0, revision_plan, usage_reflect_0 = await self.llm_reflector.reflect_sample(
            topic=topic,
            constraints=req.constraints.model_dump(mode="json"),
            novel_context=novel_context,
            episodes=draft_eps,
            sample_id=sid,
        )

        # Round 1: LLM reflection-driven rewrite
        rewrite_eps, usage_gen_1 = await self.llm_storyboard.generate_episodes(
            topic=topic,
            constraints=req.constraints,
            control_plan=control_plan,
            sample_index=sample_index + 100,
            novel_context=novel_context,
            optimization_feedback=revision_plan,
        )
        rewrite_eps = self.novel_service.enforce_source_alignment(rewrite_eps, novel_context)

        eval_1, _, usage_reflect_1 = await self.llm_reflector.reflect_sample(
            topic=topic,
            constraints=req.constraints.model_dump(mode="json"),
            novel_context=novel_context,
            episodes=rewrite_eps,
            sample_id=f"{sid}_iter1",
        )

        if eval_1.scores.total_score >= eval_0.scores.total_score:
            final_eps = rewrite_eps
            final_eval = eval_1
            chosen = "iter1"
            reason = "LLM反思迭代后评分更高"
        else:
            final_eps = draft_eps
            final_eval = eval_0
            chosen = "draft"
            reason = "初稿评分更高，保留初稿"

        trace = [
            OptimizationTrace(
                round=1,
                base_score=eval_0.scores.total_score,
                optimized_score=eval_1.scores.total_score,
                chosen=chosen,
                reason=reason,
            )
        ]

        token_usage = self._merge_tokens(
            self._merge_tokens(usage_gen_0, usage_reflect_0),
            self._merge_tokens(usage_gen_1, usage_reflect_1),
        )
        alignment = self.novel_service.source_alignment_report(final_eps, novel_context)

        sample = SampleOutput(
            sample_id=sid,
            project_id=project_id,
            input_topic=topic,
            control_plan=control_plan,
            episodes=final_eps,
            evaluation=final_eval,
            optimization_trace=trace,
            token_usage_simulated=token_usage,
            prompt_version=req.prompt_version,
            strategy_version=req.strategy_version,
        )

        self.log_service.write(
            project_id,
            "sample_generated",
            {
                "sample_id": sid,
                "generation_mode": "llm_generate_reflect_iterate",
                "total_score": final_eval.scores.total_score,
                "source_alignment": alignment,
                "token_usage": token_usage,
                "revision_plan": revision_plan,
            },
        )

        await self._emit_progress(
            progress_cb,
            {
                "stage": "sample_output",
                "project_id": project_id,
                "sample_index": sample_index + 1,
                "sample_id": sid,
                "readable_script": self.export_service.render_sample_readable(sample),
            },
        )
        return sample

    async def _generate_one_sample_with_retry(
        self,
        project_id: str,
        req: GenerateBatchRequest,
        control_plan,
        sample_index: int,
        topic: str,
        novel_context: Dict,
        progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
    ) -> SampleOutput:
        max_attempts = 2
        last_error = ""
        for attempt in range(1, max_attempts + 1):
            try:
                if attempt > 1:
                    await self._emit_progress(
                        progress_cb,
                        {
                            "stage": "sample_retrying",
                            "project_id": project_id,
                            "sample_index": sample_index + 1,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "error": last_error,
                        },
                    )
                return await self._generate_one_sample(
                    project_id=project_id,
                    req=req,
                    control_plan=control_plan,
                    sample_index=sample_index,
                    topic=topic,
                    novel_context=novel_context,
                    progress_cb=progress_cb,
                )
            except LLMClientError as e:
                last_error = str(e)
                self.log_service.write(
                    project_id,
                    "sample_retry",
                    {
                        "sample_index": sample_index + 1,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "error": last_error,
                    },
                )
                if attempt >= max_attempts:
                    await self._emit_progress(
                        progress_cb,
                        {
                            "stage": "sample_failed",
                            "project_id": project_id,
                            "sample_index": sample_index + 1,
                            "attempt": attempt,
                            "error": last_error,
                        },
                    )
                    raise LLMClientError(f"sample {sample_index + 1} failed after retries: {last_error}") from e
                await asyncio.sleep(1.2 * attempt)

    async def _rank_samples_with_llm(
        self,
        topic: str,
        novel_context: Dict,
        samples: List[SampleOutput],
    ) -> tuple[List[RankingItem], Dict[str, str], Dict[str, int]]:
        if self.llm_reflector is None:
            self.llm_reflector = LLMReflectionService()

        summaries = [
            {
                "sample_id": s.sample_id,
                "scores": s.evaluation.scores.model_dump(mode="json"),
                "agent_reviews": [a.model_dump(mode="json") for a in s.evaluation.agent_reviews],
                "optimization_trace": [t.model_dump(mode="json") for t in s.optimization_trace],
                "source_alignment_rate": self._source_alignment_rate(s.episodes),
            }
            for s in samples
        ]

        ranking_raw, usage = await self.llm_reflector.rank_samples(topic=topic, novel_context=novel_context, sample_summaries=summaries)
        valid_ids = {s.sample_id for s in samples}
        used = set()
        normalized = []
        reasons: Dict[str, str] = {}
        for item in ranking_raw:
            sid = item.get("sample_id")
            if sid not in valid_ids or sid in used:
                continue
            used.add(sid)
            normalized.append((sid, float(item.get("total_score", 0))))
            reasons[sid] = str(item.get("reason", ""))

        # fill missing with score desc
        missing = [s for s in samples if s.sample_id not in used]
        missing = sorted(missing, key=lambda x: x.evaluation.scores.total_score, reverse=True)
        for s in missing:
            normalized.append((s.sample_id, s.evaluation.scores.total_score))
            reasons[s.sample_id] = reasons.get(s.sample_id, "使用评分回退排序")

        ranking: List[RankingItem] = []
        for i, (sid, score) in enumerate(normalized, start=1):
            ranking.append(RankingItem(rank=i, sample_id=sid, total_score=round(float(score), 2)))
        return ranking, reasons, usage

    @staticmethod
    def _merge_tokens(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
        return {
            "prompt_tokens": int(a.get("prompt_tokens", 0)) + int(b.get("prompt_tokens", 0)),
            "completion_tokens": int(a.get("completion_tokens", 0)) + int(b.get("completion_tokens", 0)),
            "total_tokens": int(a.get("total_tokens", 0)) + int(b.get("total_tokens", 0)),
        }

    @staticmethod
    def _source_alignment_rate(episodes) -> float:
        shots = [sh for ep in episodes for sc in ep.scenes for sh in sc.shots]
        if not shots:
            return 0.0
        mapped = sum(1 for sh in shots if sh.source_scene_ref and sh.source_excerpt and sh.adaptation_note)
        return round(mapped / len(shots), 4)

    @staticmethod
    async def _emit_progress(
        progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]],
        payload: Dict[str, Any],
    ) -> None:
        if progress_cb is None:
            return
        maybe = progress_cb(payload)
        if asyncio.iscoroutine(maybe):
            await maybe
