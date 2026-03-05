from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class IntensityCurveStyle(str, Enum):
    linear = "线性"
    progressive = "递进"
    wave = "波浪式"


class Constraints(BaseModel):
    genre: str = Field(default="都市悬疑")
    emotion: str = Field(default="紧张")
    conflict_level: int = Field(ge=0, le=10, default=7)
    rhythm_speed: int = Field(ge=0, le=10, default=6)
    episodes: int = Field(ge=1, le=24, default=5)
    episode_duration: int = Field(ge=30, le=1800, default=120)
    intensity_curve_style: IntensityCurveStyle = Field(default=IntensityCurveStyle.progressive)


class ProjectParams(BaseModel):
    topic: str
    constraints: Constraints
    prompt_version: str = "v1.0.0"
    strategy_version: str = "v1.0.0"


class CreateProjectRequest(BaseModel):
    topic: str
    constraints: Constraints
    prompt_version: str = "v1.0.0"
    strategy_version: str = "v1.0.0"


class BGM(BaseModel):
    type: str
    tempo: str
    intensity: int = Field(ge=0, le=10)


class Shot(BaseModel):
    shot_id: str
    camera_type: str
    visual: str
    action: str
    dialogue: str
    os: str
    vo: str
    sfx: str
    transition: str
    source_scene_ref: str
    source_excerpt: str
    adaptation_note: str


class Scene(BaseModel):
    scene_id: str
    duration_estimate: int = Field(gt=0)
    location: str
    time: str
    environment: Literal["内", "外"]
    characters: List[str]
    emotion_level: int = Field(ge=0, le=10)
    bgm: BGM
    shots: List[Shot]


class EpisodeScript(BaseModel):
    episode: int
    total_duration_estimate: int
    scenes: List[Scene]


class RhythmNode(BaseModel):
    episode: int
    act: int
    target_emotion: int
    conflict: int
    payoff: str


class ParsedControlPlan(BaseModel):
    three_act_structure: List[Dict[str, Any]]
    conflict_curve: List[int]
    emotion_curve: List[int]
    payoff_distribution: List[str]
    rhythm_table: List[RhythmNode]


class EvaluationScores(BaseModel):
    structure_completeness: float
    conflict_intensity: float
    rhythm_consistency: float
    emotion_curve_quality: float
    bgm_matching_quality: float
    shot_diversity: float
    character_arc_integrity: float
    creativity: float
    total_score: float


class AgentReview(BaseModel):
    agent_name: str
    focus: str
    score: float
    strengths: List[str]
    risks: List[str]
    suggestions: List[str]


class OptimizationTrace(BaseModel):
    round: int
    base_score: float
    optimized_score: float
    chosen: str
    reason: str


class EvaluationResult(BaseModel):
    scores: EvaluationScores
    explanation: Dict[str, str]
    agent_reviews: List[AgentReview] = Field(default_factory=list)


class SampleOutput(BaseModel):
    sample_id: str
    project_id: str
    input_topic: str
    control_plan: ParsedControlPlan
    episodes: List[EpisodeScript]
    evaluation: EvaluationResult
    optimization_trace: List[OptimizationTrace] = Field(default_factory=list)
    token_usage_simulated: Dict[str, int]
    prompt_version: str
    strategy_version: str


class RankingItem(BaseModel):
    rank: int
    sample_id: str
    total_score: float


class GenerateBatchRequest(BaseModel):
    topic: Optional[str] = None
    constraints: Constraints
    project_id: Optional[str] = None
    batch_size: int = Field(default=5, ge=1, le=20)
    use_llm: bool = True
    prompt_version: str = "v1.0.0"
    strategy_version: str = "v1.0.0"

    @field_validator("batch_size")
    @classmethod
    def validate_batch(cls, v: int) -> int:
        if v < 5:
            raise ValueError("batch_size must be >= 5")
        return v

    @field_validator("use_llm")
    @classmethod
    def validate_use_llm(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Only LLM API generation is supported; use_llm must be true")
        return v


class GenerateBatchResponse(BaseModel):
    project_id: str
    created_at: datetime
    params: ProjectParams
    sample_count: int
    samples: List[SampleOutput]
    ranking: List[RankingItem]
    generation_logs: List[Dict[str, Any]]
    auto_exports: Optional[Dict[str, str]] = None


class ProjectRecord(BaseModel):
    project_id: str
    created_at: datetime
    updated_at: datetime
    params: ProjectParams
    samples: List[SampleOutput] = Field(default_factory=list)
    ranking: List[RankingItem] = Field(default_factory=list)
    generation_logs: List[Dict[str, Any]] = Field(default_factory=list)
    novel: Optional[Dict[str, Any]] = None


class ExportResponse(BaseModel):
    project_id: str
    format: str
    export_path: str
    exported_at: datetime
    content: Dict[str, Any] | str


class NovelIngestRequest(BaseModel):
    project_id: Optional[str] = None
    title: Optional[str] = "未命名小说"
    content: str = Field(min_length=1)


class NovelIngestResponse(BaseModel):
    project_id: str
    title: str
    content_chars: int
    segments_count: int
    preview: str
