"""告警层：分级通知（所有通知走飞书）"""

import requests, os
from config import *
from state import get_status_duration_min

# 告警级别
NORMAL = "normal"
WATCH = "watch"
ALERT = "alert"
URGENT = "urgent"


def evaluate_alerts(baby_state, transitions):
    """根据状态和转换评估告警"""
    alerts = []
    duration = get_status_duration_min(baby_state)
    status = baby_state["status"]

    # 状态转换告警
    for t in transitions:
        if t["to"] == "alone_awake":
            alerts.append({
                "level": ALERT,
                "message": f"⚠️ 锐锐醒了但没人看！{t.get('description', '')}",
            })
        elif t["to"] == "sleeping" and t["from"] != "unknown":
            alerts.append({
                "level": NORMAL,
                "message": f"😴 锐锐入睡了（从{t['from']}转为sleeping）",
            })
        elif t["from"] == "sleeping" and t["to"] not in ["unknown", "sleeping"]:
            alerts.append({
                "level": WATCH,
                "message": f"👀 锐锐醒了：{t.get('description', '')}",
            })

    # 持续状态告警
    if status == "alone_awake" and duration >= ALERT_ALONE_AWAKE_MIN:
        alerts.append({
            "level": URGENT,
            "message": f"🚨 锐锐独自清醒已{duration:.0f}分钟！请检查！",
        })
    elif status == "sleeping" and duration >= ALERT_LONG_SLEEP_MIN:
        alerts.append({
            "level": WATCH,
            "message": f"💤 锐锐已连续睡了{duration:.0f}分钟",
        })

    # 连续 unknown 告警
    if baby_state.get("consecutive_unknown", 0) >= 2:
        count = baby_state["consecutive_unknown"]
        alerts.append({
            "level": ALERT if count >= 3 else WATCH,
            "message": f"❓ 连续{count}次无法判断锐锐状态，摄像头可能异常",
        })

    return alerts


def send_alert(alert):
    """发送告警"""
    level = alert["level"]
    message = alert["message"]

    if level == NORMAL:
        print(f"  📝 {message}")
        return

    if level in [WATCH, ALERT, URGENT]:
        # 飞书通知（通过 OpenClaw webhook）
        try:
            notify_feishu(message)
            print(f"  📢 [{level}] {message}")
        except Exception as e:
            print(f"  ❌ 飞书通知失败: {e}")


def notify_feishu(message):
    """通过 HA rest_command 或直接 webhook 通知"""
    # 使用 OpenClaw hooks
    try:
        headers = {"Content-Type": "application/json"}
        if OPENCLAW_HOOK_TOKEN:
            headers["Authorization"] = f"Bearer {OPENCLAW_HOOK_TOKEN}"
        r = requests.post(
            OPENCLAW_HOOK_URL,
            json={"text": message},
            headers=headers,
            timeout=10,
        )
        r.raise_for_status()
    except:
        # 降级：写到文件让 cron agent 读取
        alert_file = CAPTURE_DIR / "pending_alerts.txt"
        with open(alert_file, "a") as f:
            f.write(f"{message}\n")



# 小爱播报已移除 — 所有通知统一走飞书
