# 自动化准分镜漫剧生产平台 Baseline（小说直连版）

## 运行环境
- Python 3.10+

## 安装
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置大模型 API（默认启用）
```bash
export LLM_API_KEY="你的API_KEY"
export LLM_BASE_URL="https://api.openai.com/v1"
export LLM_MODEL="gpt-4.1-mini"
export LLM_TIMEOUT_SECONDS="90"
export LLM_TEMPERATURE="0.7"
export LLM_MAX_RETRIES="4"
export LLM_RETRY_BASE_SECONDS="2.0"
export LLM_RETRY_MAX_SECONDS="30"
export LLM_MAX_CONCURRENCY="1"
export LLM_SOURCE_SCENES_PER_EPISODE="6"
export LLM_SOURCE_EXCERPT_CHARS="72"
```

## 启动 API
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 交互页面（推荐）
- 打开 `http://127.0.0.1:8000/ui`
- 直接粘贴小说原文，点击“一键生成并实时查看”
- 页面会自动：入库 -> 流式生成 -> 自动导出

## 新流程（推荐）
1. 上传小说原文（文本或文件）
2. 使用 UI 一键生成（自动处理 `project_id`）
3. 系统自动生成导出文件（`internal_production.json` + `arena_submission.txt`）

## 核心机制
- 小说拆分：自动按章节/场景拆分，生成 `chapters + scenes + story_map`。
- API-only：仅通过 LLM API 生成，不使用本地规则引擎兜底。
- 上下文窗口：按集切分 source_scenes（episode windows），逐集调用LLM；失败重试时自动压缩窗口，降低长文溢出和空响应概率。
- 生成输入：生成阶段显式消费小说拆分结果（episode_beats），不是只用 topic。
- 强制原文对齐：每个镜头都包含 `source_scene_ref/source_excerpt/adaptation_note`。
- 生成闭环：LLM生成初稿 -> LLM反思评估 -> LLM迭代改写 -> 选择更优稿。
- 排名闭环：5篇样本全部完成后，使用LLM评审对5篇进行最终排名。
- 导出双轨：
  - `internal_production.json`：完整结构化、可追溯（对内）
  - `arena_submission.txt`：纯阅读稿（对外评审）

## API 示例

### 1) 直接粘贴小说文本
```bash
curl -X POST "http://127.0.0.1:8000/novel/ingest_text" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "失控直播间",
    "content": "这里粘贴小说原文..."
  }'
```

### 2) 上传本地文件（推荐用CLI自动读取）
```bash
python cli.py ingest-file --file /absolute/path/novel.txt --title "失控直播间"
```

### 3) 基于 project_id 批量生成（无需 topic）
```bash
curl -X POST "http://127.0.0.1:8000/generate_batch" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_xxxxx",
    "constraints": {
      "genre": "都市悬疑",
      "emotion": "压迫",
      "conflict_level": 8,
      "rhythm_speed": 7,
      "episodes": 5,
      "episode_duration": 120,
      "intensity_curve_style": "递进"
    },
    "batch_size": 5,
    "use_llm": true,
    "prompt_version": "v1.0.0",
    "strategy_version": "v1.0.0"
  }'
```

### 3.1) 流式生成进度（推荐UI使用）
```bash
curl -N -X POST "http://127.0.0.1:8000/generate_batch_stream" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "proj_xxxxx",
    "constraints": {
      "genre": "现实主义",
      "emotion": "温情",
      "conflict_level": 6,
      "rhythm_speed": 5,
      "episodes": 5,
      "episode_duration": 120,
      "intensity_curve_style": "递进"
    },
    "batch_size": 5,
    "use_llm": true
  }'
```

### 4) 导出
```bash
curl "http://127.0.0.1:8000/export/{project_id}?format=bundle"
curl "http://127.0.0.1:8000/export/{project_id}?format=internal_json"
curl "http://127.0.0.1:8000/export/{project_id}?format=arena_txt"
```

## CLI
```bash
# 上传文本
python cli.py ingest-text --title "失控直播间" --content "这里粘贴原文"

# 上传文件（CLI自动读取文件并调用 ingest_text）
python cli.py ingest-file --file /absolute/path/novel.txt --title "失控直播间"

# 基于 project_id 生成
python cli.py generate --project-id proj_xxxxx --batch-size 5

# 导出
python cli.py export --project-id proj_xxxxx --format bundle
```

## 说明
- `generate_batch` 必须传 `project_id`，且项目下已上传小说原文。
- 仅支持 `use_llm=true`，未配置 LLM API 会返回错误。
- 若感觉慢：这是正常现象。总调用量约等于 `batch_size * episodes * (初稿+可能优化重试)`。
- 已内置重试退避和限并发参数：`LLM_MAX_RETRIES`、`LLM_RETRY_BASE_SECONDS`、`LLM_RETRY_MAX_SECONDS`、`LLM_MAX_CONCURRENCY`。
- 长文本上下文控制参数：`LLM_SOURCE_SCENES_PER_EPISODE`、`LLM_SOURCE_EXCERPT_CHARS`。
- UI 已改为流式显示 `/generate_batch_stream`，每完成一篇样本即实时输出该篇可读剧本。
- 每个样本结果包含 `evaluation.agent_reviews`、`optimization_trace`，并可按镜头追溯原文来源。
- 镜头级追溯字段：`shots[].source_scene_ref`、`shots[].source_excerpt`、`shots[].adaptation_note`。
- 所有 API 返回结构化 JSON。
# Storyboard-Splitting-Tool
# Storyboard-Splitting-Tool
# Storyboard-Splitting-Tool
