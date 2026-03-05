from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = BASE_DIR / "exports"
PROJECT_DATA_DIR = BASE_DIR / "project" / "data"

for _d in (LOG_DIR, EXPORT_DIR, PROJECT_DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)

DEFAULT_PROMPT_VERSION = "v1.0.0"
DEFAULT_STRATEGY_VERSION = "v1.0.0"
MIN_BATCH_SIZE = 5
CAMERA_TYPES = ["远景", "全景", "中景", "近景", "特写", "推镜", "拉镜", "摇镜", "跟拍", "俯拍"]
TRANSITIONS = ["切", "淡入", "淡出", "闪回", "叠化"]
SFX_POOL = ["脚步声", "风声", "心跳声", "门轴声", "手机震动", "雨滴声", "刹车声", "远处人群喧哗"]
BGM_MAP = {
    "low": {"type": "环境氛围", "tempo": "慢", "intensity": 3},
    "mid": {"type": "情绪钢琴", "tempo": "中", "intensity": 5},
    "high": {"type": "紧张弦乐", "tempo": "快", "intensity": 8},
}
