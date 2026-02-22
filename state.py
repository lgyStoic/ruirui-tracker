"""状态机：管理锐锐的状态和转换"""

import json, time
from datetime import datetime
from config import STATE_FILE

STATES = ["sleeping", "playing", "held", "eating", "alone_awake", "unknown", "out"]

DEFAULT_STATE = {
    "status": "unknown",
    "status_since": 0,
    "room": "unknown",
    "companion": "unknown",
    "light": "unknown",
    "door_activity": None,
    "consecutive_unknown": 0,
    "history": [],  # 最近10条状态变更
}


def load_baby_state():
    try:
        data = json.loads(STATE_FILE.read_text())
        return data.get("baby", DEFAULT_STATE.copy())
    except:
        return DEFAULT_STATE.copy()


def save_baby_state(baby_state):
    try:
        data = json.loads(STATE_FILE.read_text())
    except:
        data = {}
    data["baby"] = baby_state
    STATE_FILE.write_text(json.dumps(data, default=str))


def parse_gemini_result(text):
    """解析 Gemini 输出为结构化状态
    
    输入格式: 房间 | 活动描述 | 陪伴 | 环境
    输出: dict with status, room, companion, light, description
    """
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 4:
        return {"status": "unknown", "raw": text}

    room_raw, desc, companion_raw, light_raw = parts[0], parts[1], parts[2], parts[3]

    # 推断状态
    desc_lower = desc.lower()
    status = "unknown"
    if any(w in desc_lower for w in ["睡", "sleep", "休息", "闭眼"]):
        status = "sleeping"
    elif any(w in desc_lower for w in ["玩", "爬", "坐", "play", "活动", "翻"]):
        if "无人" in companion_raw or "无" in companion_raw:
            status = "alone_awake"
        else:
            status = "playing"
    elif any(w in desc_lower for w in ["抱", "held", "怀里"]):
        status = "held"
    elif any(w in desc_lower for w in ["吃", "奶", "eat", "喂", "餐椅"]):
        status = "eating"
    elif "不确定" in desc_lower or "未见" in desc_lower or "看不清" in desc_lower:
        status = "unknown"

    # 有大人 → 不是 alone_awake
    has_companion = not any(w in companion_raw for w in ["无人", "无", "不确定"])
    if status == "alone_awake" and has_companion:
        status = "playing"

    return {
        "status": status,
        "room": room_raw,
        "companion": companion_raw,
        "light": light_raw,
        "description": desc,
    }


def update_state(baby_state, parsed):
    """更新状态机，返回 (new_state, transitions)"""
    transitions = []
    old_status = baby_state["status"]
    new_status = parsed["status"]
    now = time.time()

    # 更新连续 unknown 计数
    if new_status == "unknown":
        baby_state["consecutive_unknown"] += 1
    else:
        baby_state["consecutive_unknown"] = 0

    # 检测状态变更
    if new_status != old_status and new_status != "unknown":
        transition = {
            "from": old_status,
            "to": new_status,
            "time": datetime.now().strftime("%H:%M"),
            "ts": now,
            "description": parsed.get("description", ""),
        }
        transitions.append(transition)

        # 更新状态
        baby_state["status"] = new_status
        baby_state["status_since"] = now

        # 保留最近10条历史
        baby_state.setdefault("history", [])
        baby_state["history"].append(transition)
        baby_state["history"] = baby_state["history"][-10:]

    elif new_status != "unknown":
        # 状态没变但更新时间
        baby_state["status"] = new_status

    # 更新上下文
    if parsed.get("room") and parsed["room"] != "unknown":
        baby_state["room"] = parsed["room"]
    if parsed.get("companion"):
        baby_state["companion"] = parsed["companion"]
    if parsed.get("light"):
        baby_state["light"] = parsed["light"]

    baby_state["last_update"] = now

    return baby_state, transitions


def get_status_duration_min(baby_state):
    """当前状态持续了多少分钟"""
    since = baby_state.get("status_since", 0)
    if since == 0:
        return 0
    return (time.time() - since) / 60
