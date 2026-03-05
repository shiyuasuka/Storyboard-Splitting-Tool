from __future__ import annotations

import json
import asyncio
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from pydantic import ValidationError

from app.models.schemas import Constraints, EpisodeScript, ParsedControlPlan
from app.services.llm_client import LLMClientError, OpenAICompatibleLLMClient


class LLMStoryboardService:
    def __init__(self) -> None:
        self.client = OpenAICompatibleLLMClient()
        self.max_source_scenes = max(1, int(os.getenv("LLM_SOURCE_SCENES_PER_EPISODE", "6")))
        self.max_source_excerpt_chars = max(24, int(os.getenv("LLM_SOURCE_EXCERPT_CHARS", "72")))

    async def generate_episodes(
        self,
        topic: str,
        constraints: Constraints,
        control_plan: ParsedControlPlan,
        sample_index: int,
        novel_context: Dict | None = None,
        optimization_feedback: List[str] | None = None,
        progress_cb: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        progress_meta: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[EpisodeScript], Dict[str, int]]:
        context = novel_context or {}
        episode_windows = self._episode_windows(context, constraints.episodes)
        episodes: List[EpisodeScript] = []
        usage_sum = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        max_episode_attempts = 3

        for ep_no in range(1, constraints.episodes + 1):
            window = episode_windows[ep_no - 1] if ep_no - 1 < len(episode_windows) else []
            last_error = ""
            ep_model = None
            for attempt in range(1, max_episode_attempts + 1):
                attempt_window = self._source_window_for_attempt(window, attempt)
                await self._emit_progress(
                    progress_cb,
                    {
                        **(progress_meta or {}),
                        "stage": "episode_attempt",
                        "episode_no": ep_no,
                        "attempt": attempt,
                        "max_attempts": max_episode_attempts,
                        "source_scene_count": len(attempt_window),
                    },
                )
                system_prompt = self._build_system_prompt(strict=(attempt > 1))
                user_prompt = self._build_user_prompt(
                    topic=topic,
                    constraints=constraints,
                    control_plan=control_plan,
                    sample_index=sample_index,
                    episode_no=ep_no,
                    source_scenes=attempt_window,
                    optimization_feedback=optimization_feedback,
                    strict=(attempt > 1),
                )
                try:
                    result = await self.client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
                    usage = result.pop("_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                    usage_sum = self._merge_usage(usage_sum, usage)
                    raw_ep = self._extract_episode_payload(result)
                    raw_ep = self._coerce_episode_payload(raw_ep, constraints, ep_no)
                    raw_ep = self._inject_source_fields(raw_ep, attempt_window)
                    candidate = self._validate_episode(raw_ep)
                    candidate = self._normalize_episode(candidate, constraints, ep_no)
                    if not candidate.scenes:
                        raise LLMClientError("LLM returned empty scenes")
                    ep_model = candidate
                    await self._emit_progress(
                        progress_cb,
                        {
                            **(progress_meta or {}),
                            "stage": "episode_completed",
                            "episode_no": ep_no,
                            "attempt": attempt,
                            "scene_count": len(candidate.scenes),
                        },
                    )
                    break
                except LLMClientError as e:
                    last_error = str(e)
                    if attempt == max_episode_attempts:
                        # Rescue path: compact prompt with strict minimal output
                        rescue_ep, rescue_usage = await self._rescue_episode(
                            topic=topic,
                            constraints=constraints,
                            episode_no=ep_no,
                            source_scenes=window,
                        )
                        usage_sum = self._merge_usage(usage_sum, rescue_usage)
                        rescue_ep = self._inject_source_fields(rescue_ep, window)
                        candidate = self._validate_episode(rescue_ep)
                        candidate = self._normalize_episode(candidate, constraints, ep_no)
                        ep_model = candidate
                        await self._emit_progress(
                            progress_cb,
                            {
                                **(progress_meta or {}),
                                "stage": "episode_rescued",
                                "episode_no": ep_no,
                                "attempt": attempt,
                            },
                        )
                        break
                    await self._emit_progress(
                        progress_cb,
                        {
                            **(progress_meta or {}),
                            "stage": "episode_retrying",
                            "episode_no": ep_no,
                            "attempt": attempt,
                            "error": last_error,
                        },
                    )
                    continue

            if ep_model is None:
                raise LLMClientError(f"episode {ep_no} failed: {last_error}")
            episodes.append(ep_model)

        return episodes, usage_sum

    async def _rescue_episode(
        self,
        topic: str,
        constraints: Constraints,
        episode_no: int,
        source_scenes: List[Dict],
    ) -> Tuple[Dict, Dict[str, int]]:
        minimal_sources = self._source_window_for_attempt(source_scenes, attempt=3)
        if not minimal_sources:
            minimal_sources = [{"ref": "C0-S1", "summary": "核心事件", "excerpt": "核心事件"}]

        attempts = 2
        usage_sum = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        last_error = ""
        for i in range(1, attempts + 1):
            strict_json_shape = (
                "{\"episode\":{\"episode\":1,\"total_duration_estimate\":120,\"scenes\":["
                "{\"scene_id\":\"1-1\",\"duration_estimate\":120,\"location\":\"\",\"time\":\"日\",\"environment\":\"内\","
                "\"characters\":[\"\"],\"emotion_level\":6,\"bgm\":{\"type\":\"\",\"tempo\":\"中\",\"intensity\":5},"
                "\"shots\":[{\"shot_id\":\"1-1-1\",\"camera_type\":\"中景\",\"visual\":\"\",\"action\":\"\","
                "\"dialogue\":\"\",\"os\":\"\",\"vo\":\"\",\"sfx\":\"\",\"transition\":\"切\","
                "\"source_scene_ref\":\"\",\"source_excerpt\":\"\",\"adaptation_note\":\"\"}]}]}}"
            )
            system_prompt = (
                "你是影视编剧引擎。"
                "仅输出JSON对象。"
                "现在只生成一集，场景不能空。"
                "文本字段统一使用简体中文。"
            )
            user_prompt = (
                f"命题:{topic}\\n"
                f"集数:{episode_no}\\n"
                f"目标时长:{constraints.episode_duration}\\n"
                f"原文片段:{json.dumps(minimal_sources[:max(1, 3 - i)], ensure_ascii=False)}\\n"
                f"必须严格按此JSON形状输出:{strict_json_shape}\\n"
                "约束："
                "1) scenes>=1;"
                "2) 每场shots>=1;"
                "3) source_scene_ref 必须取自给定 ref;"
                "4) source_excerpt 必须引用给定 excerpt 原文。"
            )
            try:
                result = await self.client.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
                usage = result.pop("_usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
                usage_sum = self._merge_usage(usage_sum, usage)
                raw = self._extract_episode_payload(result)
                raw = self._coerce_episode_payload(raw, constraints, episode_no)
                if not raw.get("scenes"):
                    raise LLMClientError("LLM returned empty scenes")
                return raw, usage_sum
            except LLMClientError as e:
                last_error = str(e)
                continue

        raise LLMClientError(f"episode {episode_no} rescue failed: {last_error or 'unknown error'}")

    @staticmethod
    def _build_system_prompt(strict: bool = False) -> str:
        base = (
            "你是影视工业化准分镜编剧引擎。"
            "必须仅返回JSON对象，不要输出markdown。"
            "当前只生成一集，且必须改编自提供的source_scenes。"
            "文本内容必须全部使用简体中文表达。"
            "shots字段必须包含：shot_id,camera_type,visual,action,dialogue,os,vo,sfx,transition,"
            "source_scene_ref,source_excerpt,adaptation_note。"
        )
        if strict:
            base += "严禁返回空数组；scenes最少4个且shots每场最少2个。"
        return base

    def _build_user_prompt(
        self,
        topic: str,
        constraints: Constraints,
        control_plan: ParsedControlPlan,
        sample_index: int,
        episode_no: int,
        source_scenes: List[Dict],
        optimization_feedback: List[str] | None = None,
        strict: bool = False,
    ) -> str:
        src = json.dumps(source_scenes, ensure_ascii=False)
        feedback_text = json.dumps(optimization_feedback or [], ensure_ascii=False)
        control_plan_compact = {
            "three_act_structure": control_plan.three_act_structure,
            "current_episode_plan": [
                x.model_dump(mode="json")
                for x in control_plan.rhythm_table
                if x.episode == episode_no
            ],
        }
        tail = (
            f"命题:{topic}\n"
            f"样本序号:{sample_index + 1} 集数:{episode_no}/{constraints.episodes}\n"
            f"体裁:{constraints.genre} 情感基调:{constraints.emotion}\n"
            f"冲突等级:{constraints.conflict_level} 节奏速度:{constraints.rhythm_speed}\n"
            f"单集时长:{constraints.episode_duration}秒 曲线风格:{constraints.intensity_curve_style.value}\n"
            f"控制信息:{json.dumps(control_plan_compact, ensure_ascii=False)}\n"
            f"本集可用原文场景source_scenes:{src}\n"
            f"优化建议:{feedback_text}\n"
            "任务要求:\n"
            "1) 只生成当前这一集，返回格式必须是 {\"episode\": {...}}\n"
            "2) 本集所有场景必须来自source_scenes，不允许虚构新事件\n"
            "3) 每个镜头必须填写 source_scene_ref/source_excerpt/adaptation_note\n"
            "4) source_scene_ref 必须取自 source_scenes.ref\n"
            "5) source_excerpt 必须来自对应 source_scenes.excerpt 的原文片段\n"
            "6) 每集总时长严格等于 episode_duration\n"
            "7) 不允许输出额外解释文本\n"
            "7.1) visual/action/dialogue/os/vo/sfx/transition 统一用中文表述\n"
        )
        if strict:
            tail += (
                "8) scenes 数量必须 >= 4；每个 scene.shots 数量必须 >= 2\n"
                "9) 禁止返回空 scenes；禁止省略 scenes 字段\n"
            )
        return tail

    @staticmethod
    def _extract_episode_payload(result: Dict) -> Dict:
        ep = result.get("episode")
        if isinstance(ep, dict):
            return ep
        ep2 = result.get("episode_data") or result.get("episode_script")
        if isinstance(ep2, dict):
            return ep2
        eps = result.get("episodes")
        if isinstance(eps, list) and eps and isinstance(eps[0], dict):
            return eps[0]
        raise LLMClientError("LLM JSON missing episode payload")

    def _coerce_episode_payload(self, raw_episode: Dict, constraints: Constraints, ep_no: int) -> Dict:
        if not isinstance(raw_episode, dict):
            raise LLMClientError("episode payload must be an object")

        # episode-level aliases
        episode = raw_episode.get("episode")
        if episode is None:
            episode = raw_episode.get("episode_number") or raw_episode.get("ep") or ep_no

        total_duration = (
            raw_episode.get("total_duration_estimate")
            or raw_episode.get("total_duration")
            or raw_episode.get("duration_total")
            or raw_episode.get("episode_duration")
            or constraints.episode_duration
        )

        scenes = (
            raw_episode.get("scenes")
            or raw_episode.get("scene_list")
            or raw_episode.get("storyboard")
            or raw_episode.get("episode_script")
            or []
        )
        if isinstance(scenes, dict):
            scenes = scenes.get("scenes") or scenes.get("scene_list") or []

        coerced_scenes = [self._coerce_scene_payload(sc, i + 1) for i, sc in enumerate(scenes if isinstance(scenes, list) else [])]
        return {
            "episode": episode,
            "total_duration_estimate": total_duration,
            "scenes": coerced_scenes,
        }

    def _coerce_scene_payload(self, raw_scene: Dict, idx: int) -> Dict:
        if not isinstance(raw_scene, dict):
            raw_scene = {}

        scene_id = raw_scene.get("scene_id") or raw_scene.get("id") or raw_scene.get("scene_no") or f"TBD-{idx}"
        duration = (
            raw_scene.get("duration_estimate")
            or raw_scene.get("duration")
            or raw_scene.get("scene_duration")
            or 20
        )
        location = raw_scene.get("location") or raw_scene.get("place") or raw_scene.get("setting") or "未注明地点"
        time_val = raw_scene.get("time") or raw_scene.get("time_of_day") or "日"
        env = raw_scene.get("environment") or raw_scene.get("env") or raw_scene.get("interior_exterior") or "内"
        characters = raw_scene.get("characters") or raw_scene.get("roles") or raw_scene.get("persons") or []
        if isinstance(characters, str):
            characters = [x.strip() for x in characters.split("、") if x.strip()] or [characters]
        emotion = raw_scene.get("emotion_level") or raw_scene.get("emotion") or raw_scene.get("intensity") or 6
        bgm = raw_scene.get("bgm") or {}
        if not isinstance(bgm, dict):
            bgm = {}

        shots = raw_scene.get("shots") or raw_scene.get("shot_list") or raw_scene.get("camera_shots") or []
        coerced_shots = [self._coerce_shot_payload(sh, i + 1) for i, sh in enumerate(shots if isinstance(shots, list) else [])]

        return {
            "scene_id": str(scene_id),
            "duration_estimate": self._to_int(duration, 20),
            "location": str(location),
            "time": str(time_val),
            "environment": "外" if str(env).strip() in {"外", "EXT", "ext", "Exterior"} else "内",
            "characters": characters if isinstance(characters, list) else [],
            "emotion_level": self._to_int(emotion, 6),
            "bgm": {
                "type": bgm.get("type") or bgm.get("style") or "情绪钢琴",
                "tempo": bgm.get("tempo") or bgm.get("rhythm") or "中",
                "intensity": self._to_int(bgm.get("intensity") or bgm.get("level"), 5),
            },
            "shots": coerced_shots,
        }

    def _coerce_shot_payload(self, raw_shot: Dict, idx: int) -> Dict:
        if not isinstance(raw_shot, dict):
            raw_shot = {}
        return {
            "shot_id": str(raw_shot.get("shot_id") or raw_shot.get("id") or raw_shot.get("shot_no") or f"TBD-SH-{idx}"),
            "camera_type": raw_shot.get("camera_type") or raw_shot.get("shot_type") or raw_shot.get("camera") or "中景",
            "visual": raw_shot.get("visual") or raw_shot.get("image") or raw_shot.get("description") or "",
            "action": raw_shot.get("action") or raw_shot.get("movement") or "",
            "dialogue": raw_shot.get("dialogue") or raw_shot.get("line") or "",
            "os": raw_shot.get("os") or raw_shot.get("inner_voice") or "",
            "vo": raw_shot.get("vo") or raw_shot.get("narration") or "",
            "sfx": raw_shot.get("sfx") or raw_shot.get("sound_effect") or "环境声",
            "transition": raw_shot.get("transition") or raw_shot.get("cut") or "切",
            "source_scene_ref": raw_shot.get("source_scene_ref") or raw_shot.get("source_ref") or "",
            "source_excerpt": raw_shot.get("source_excerpt") or raw_shot.get("source_text") or "",
            "adaptation_note": raw_shot.get("adaptation_note") or raw_shot.get("note") or "",
        }

    @staticmethod
    def _validate_episode(raw_episode: Dict) -> EpisodeScript:
        try:
            return EpisodeScript.model_validate(raw_episode)
        except ValidationError as e:
            raise LLMClientError(f"Episode validation failed: {e}") from e

    def _normalize_episode(self, ep: EpisodeScript, constraints: Constraints, ep_no: int) -> EpisodeScript:
        ep.episode = ep_no
        if not ep.scenes:
            raise LLMClientError("LLM returned empty scenes")

        for sc_idx, scene in enumerate(ep.scenes, start=1):
            scene.scene_id = f"{ep_no}-{sc_idx}"
            scene.environment = "内" if scene.environment not in {"内", "外"} else scene.environment
            scene.emotion_level = max(0, min(10, scene.emotion_level))
            scene.bgm.intensity = max(0, min(10, scene.bgm.intensity))
            if scene.duration_estimate <= 0:
                scene.duration_estimate = max(5, constraints.episode_duration // max(1, len(ep.scenes)))
            for sh_idx, shot in enumerate(scene.shots, start=1):
                shot.shot_id = f"{ep_no}-{sc_idx}-{sh_idx}"

        total = sum(s.duration_estimate for s in ep.scenes)
        diff = constraints.episode_duration - total
        if diff != 0:
            ep.scenes[-1].duration_estimate += diff
            if ep.scenes[-1].duration_estimate <= 0:
                ep.scenes[-1].duration_estimate = max(5, constraints.episode_duration // len(ep.scenes))

        ep.total_duration_estimate = constraints.episode_duration
        return ep

    def _inject_source_fields(self, raw_episode: Dict, source_scenes: List[Dict]) -> Dict:
        if not source_scenes:
            source_scenes = [{"ref": "TOPIC-S1", "excerpt": "topic-derived source", "summary": "topic-derived source"}]

        scenes = raw_episode.get("scenes") if isinstance(raw_episode, dict) else None
        if not isinstance(scenes, list):
            return raw_episode

        by_ref = {s.get("ref"): s for s in source_scenes if s.get("ref")}
        for sc_idx, scene in enumerate(scenes):
            if not isinstance(scene, dict):
                continue
            default_src = source_scenes[sc_idx % len(source_scenes)]
            shots = scene.get("shots")
            if not isinstance(shots, list):
                continue
            for shot in shots:
                if not isinstance(shot, dict):
                    continue
                raw_ref = shot.get("source_scene_ref")
                src = by_ref.get(raw_ref) if raw_ref in by_ref else default_src
                ref = src.get("ref", "TOPIC-S1")
                excerpt = src.get("excerpt", "topic-derived source")
                summary = src.get("summary", "")
                shot["source_scene_ref"] = ref
                shot["source_excerpt"] = shot.get("source_excerpt") or excerpt
                shot["adaptation_note"] = shot.get("adaptation_note") or f"改编自{ref}，保留原文事件核心"
                if summary and "原著事件" not in str(shot.get("visual", "")):
                    shot["visual"] = f"{shot.get('visual', '')} 原著事件：{summary}".strip()
                if excerpt and "原文线索" not in str(shot.get("dialogue", "")):
                    shot["dialogue"] = f"{shot.get('dialogue', '')} 原文线索：{excerpt[:24]}".strip()
        return raw_episode

    @staticmethod
    def _episode_windows(novel_context: Dict, episodes: int) -> List[List[Dict]]:
        beats = novel_context.get("episode_beats") or []
        windows: List[List[Dict]] = []
        for i in range(episodes):
            if i < len(beats) and beats[i]:
                windows.append(beats[i])
            else:
                windows.append(novel_context.get("source_scenes", [])[:1])
        return windows

    def _source_window_for_attempt(self, window: List[Dict], attempt: int) -> List[Dict]:
        if not window:
            return []
        count = self.max_source_scenes
        excerpt_chars = self.max_source_excerpt_chars
        if attempt >= 2:
            count = max(2, count - 2)
            excerpt_chars = max(40, excerpt_chars - 20)
        if attempt >= 3:
            count = 1
            excerpt_chars = 32

        compact: List[Dict] = []
        for scene in window[:count]:
            compact.append(
                {
                    "ref": scene.get("ref", ""),
                    "chapter_id": scene.get("chapter_id", 0),
                    "chapter_title": scene.get("chapter_title", ""),
                    "summary": str(scene.get("summary", ""))[:120],
                    "excerpt": str(scene.get("excerpt", ""))[:excerpt_chars],
                }
            )
        return compact

    @staticmethod
    def _merge_usage(a: Dict[str, int], b: Dict[str, int]) -> Dict[str, int]:
        return {
            "prompt_tokens": int(a.get("prompt_tokens", 0)) + int(b.get("prompt_tokens", 0)),
            "completion_tokens": int(a.get("completion_tokens", 0)) + int(b.get("completion_tokens", 0)),
            "total_tokens": int(a.get("total_tokens", 0)) + int(b.get("total_tokens", 0)),
        }

    @staticmethod
    def _to_int(value, default: int) -> int:
        try:
            return int(value)
        except Exception:
            return default

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
