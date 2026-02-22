"""集中配置 — 所有路径和参数在此管理"""
import os
from pathlib import Path

# ── 路径 ──
CAPTURE_DIR = Path(os.environ.get("RUIRUI_CAPTURE_DIR", "/tmp/ruirui_captures"))
LOG_DIR = Path(os.environ.get("RUIRUI_LOG_DIR",
    os.path.expanduser("~/.openclaw/workspace/memory")))
STATE_FILE = CAPTURE_DIR / "tracker_state.json"
HEARTBEAT_FILE = Path("/tmp/ruirui_heartbeat")
STATS_FILE = LOG_DIR / "ruirui_stats.json"

# ── 凭证（文件路径，运行时读取） ──
GEMINI_KEY_PATH = os.environ.get("GEMINI_KEY_PATH", os.path.expanduser("~/.gemini_key"))
HA_TOKEN_PATH = os.environ.get("HA_TOKEN_PATH", os.path.expanduser("~/.ha_token"))
YS7_APPKEY_PATH = os.environ.get("YS7_APPKEY_PATH", os.path.expanduser("~/.ys7_appkey"))
YS7_SECRET_PATH = os.environ.get("YS7_SECRET_PATH", os.path.expanduser("~/.ys7_secret"))

# ── go2rtc ──
GO2RTC_URL = os.environ.get("GO2RTC_URL", "http://192.168.2.24:2984")
GO2RTC_CAMERAS = {
    "bedroom": "c302_4021",
    "living": "c302_4243",
}

# ── 萤石云（猫眼） ──
YS7_CAMERAS = {
    "door": "K66700907",
}

# ── Home Assistant ──
HA_URL = os.environ.get("HA_URL", "http://192.168.2.24:8123")

# ── OpenClaw webhook（告警通知） ──
OPENCLAW_HOOK_URL = os.environ.get("OPENCLAW_HOOK_URL", "http://127.0.0.1:18789/hooks")
OPENCLAW_HOOK_TOKEN = os.environ.get("OPENCLAW_HOOK_TOKEN", "")

# ── 分析参数 ──
GEMINI_MODEL = "gemini-2.5-pro"
MAX_PER_CAM = 5
MAX_DOOR_FRAMES = 2
RESIZE_WIDTH = 800
DIFF_THRESHOLD = 8.0
CMP_SIZE = (160, 120)
FORCE_ANALYZE_MIN = 30

# ── 告警阈值 ──
ALERT_ALONE_AWAKE_MIN = 5      # 独自清醒超过N分钟告警
ALERT_LONG_SLEEP_MIN = 180     # 连续睡觉超过N分钟提醒
ALERT_UNKNOWN_MIN = 20         # 连续unknown超过N分钟告警
EVENT_DEDUP_MIN = 30           # 同一事件N分钟内不重复通知

# ── 运行时间 ──
RUN_HOUR_START = 7
RUN_HOUR_END = 22

# ── 重试 ──
CAPTURE_MAX_RETRY = 3
CAPTURE_RETRY_BACKOFF = [2, 5, 10]
GEMINI_MAX_RETRY = 2
GEMINI_RETRY_BACKOFF = [5, 15]
