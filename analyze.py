"""分析层：帧差检测 → Gemini 分析 → 状态机 → 告警 → EVENT检测"""

import time, io, base64, json, requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageChops

from config import *
from state import load_baby_state, save_baby_state, parse_gemini_result, update_state
from alert import evaluate_alerts, send_alert
from door_check import check_door_event


# ── Gemini 成本估算 ──
IMG_TOKENS = 258
PROMPT_TOKENS = 800
OUTPUT_TOKENS = 50
INPUT_PRICE_PER_M = 1.25
OUTPUT_PRICE_PER_M = 10.0

PROMPT = """你看到的是家庭摄像头过去10分钟的截图（每2分钟一帧）。
文件名格式：摄像头_时间.jpg（如 bedroom_2230.jpg）

目标：追踪8个月大婴儿"锐锐"的活动。

摄像头说明：
- bedroom = 卧室（婴儿房，粉色墙，蚊帐婴儿床）
- living = 客厅（活动区，彩色玩具）

关键识别：
- 锐锐8个月大，不会走路站立！只会躺、坐、爬、趴
- 体型非常小，婴儿圆润身形
- 站着走路的都不是锐锐，是大人或其他小孩
- 通常在婴儿床/蚊帐里，或被大人抱着
- 婴儿床上被子有隆起/小鼓包 = 锐锐在被子里睡觉
- 蚊帐里的小身影 = 锐锐
- 大人怀里抱着的小婴儿 = 锐锐
- 结合多帧变化推断：位置没变=持续同一活动，位置变了=有转场
- 彩色画面 = 开灯；黑白画面 = 关灯/夜视模式

输出格式（严格一行）：
房间 | 活动描述 | 陪伴情况 | 环境光线

陪伴情况：无人、大人、妈妈、爸爸、家属、不确定
环境光线：明亮、暗、夜视 等

示例：
卧室 | 一直在婴儿床里睡觉 | 无人 | 关灯、夜视
客厅→卧室 | 前5分钟客厅玩耍，后被抱回卧室睡觉 | 妈妈 | 明亮

只输出一行，不要多余文字。"""


# ── 工具函数 ──

def load_tracker_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {}


def save_tracker_state(state):
    STATE_FILE.write_text(json.dumps(state, default=str))


def get_log_file():
    return LOG_DIR / f"ruirui_{datetime.now().strftime('%Y-%m-%d')}.md"


def get_recent_logs(n=6):
    log_file = get_log_file()
    if not log_file.exists():
        return ""
    lines = [l for l in log_file.read_text().splitlines() if l.startswith("- ")]
    return "\n".join(lines[-n:]) if lines else ""


def get_last_entry():
    files = sorted(LOG_DIR.glob("ruirui_*.md"), reverse=True)
    for f in files[:2]:
        lines = [l for l in f.read_text().splitlines() if l.startswith("- ")]
        if lines:
            return lines[-1]
    return ""


def get_recent_captures(minutes=12):
    if not CAPTURE_DIR.exists():
        return {"bedroom": [], "living": [], "door": []}
    cutoff = time.time() - minutes * 60
    files = sorted([
        f for f in CAPTURE_DIR.glob("*.jpg")
        if f.stat().st_mtime >= cutoff
    ], key=lambda f: f.name)
    result = {"bedroom": [], "living": [], "door": []}
    for f in files:
        for cam in result:
            if f.name.startswith(cam):
                result[cam].append(f)
                break
    return result


def compute_batch_diff(captures):
    max_diff = 0.0
    for cam in ["bedroom", "living", "door"]:
        files = captures[cam]
        if len(files) < 2:
            continue
        try:
            first = Image.open(files[0]).convert("L").resize(CMP_SIZE)
            last = Image.open(files[-1]).convert("L").resize(CMP_SIZE)
            diff_img = ImageChops.difference(first, last)
            pixels = list(diff_img.convert("L").tobytes())
            diff = sum(pixels) / len(pixels)
            max_diff = max(max_diff, diff)
        except:
            max_diff = 999.0
    return max_diff


def sample_evenly(files, n):
    if len(files) <= n:
        return files
    step = len(files) / n
    return [files[int(i * step)] for i in range(n)]


def resize_image(path):
    img = Image.open(path)
    if img.width > RESIZE_WIDTH:
        ratio = RESIZE_WIDTH / img.width
        new_h = int(img.height * ratio)
        img = img.resize((RESIZE_WIDTH, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


# ── 成本统计 ──

def load_stats():
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text())
        except:
            pass
    return {"total_calls": 0, "total_skips": 0, "total_cost_usd": 0.0, "daily": {}}


def update_stats(stats, called_gemini, num_images=0):
    today = datetime.now().strftime("%Y-%m-%d")
    if today not in stats["daily"]:
        stats["daily"][today] = {"calls": 0, "skips": 0, "images": 0, "cost_usd": 0.0}
    day = stats["daily"][today]

    if called_gemini:
        input_tokens = num_images * IMG_TOKENS + PROMPT_TOKENS
        cost = (input_tokens * INPUT_PRICE_PER_M + OUTPUT_TOKENS * OUTPUT_PRICE_PER_M) / 1_000_000
        stats["total_calls"] += 1
        stats["total_cost_usd"] = round(stats["total_cost_usd"] + cost, 6)
        day["calls"] += 1
        day["images"] = day.get("images", 0) + num_images
        day["cost_usd"] = round(day.get("cost_usd", 0) + cost, 6)
    else:
        stats["total_skips"] += 1
        day["skips"] += 1

    STATS_FILE.write_text(json.dumps(stats, indent=2))
    return stats, day


# ── Gemini 调用 ──

def call_gemini(selected, gemini_key):
    parts = []
    total_size = 0
    for f in selected:
        img_bytes = resize_image(f)
        total_size += len(img_bytes)
        parts.append({"text": f"[{f.name}]"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(img_bytes).decode()
            }
        })

    history = get_recent_logs()
    context = f"\n\n最近记录：\n{history}" if history else ""

    baby_state = load_baby_state()
    status_ctx = f"\n当前状态: {baby_state['status']}（在{baby_state.get('room', '未知')}）"

    parts.append({"text": PROMPT + context + status_ctx})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_key}"
    payload = {"contents": [{"parts": parts}]}

    last_err = None
    for i in range(GEMINI_MAX_RETRY):
        try:
            r = requests.post(url, json=payload, timeout=120)
            r.raise_for_status()
            result = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            return result, total_size
        except Exception as e:
            last_err = e
            if i < GEMINI_MAX_RETRY - 1:
                time.sleep(GEMINI_RETRY_BACKOFF[min(i, len(GEMINI_RETRY_BACKOFF) - 1)])
    raise last_err


def handle_event(event, state, now):
    """处理出门/回来事件，返回是否需要通知"""
    if not event:
        return False, ""

    last_event = state.get("last_event")
    last_event_time = state.get("last_event_time", 0)
    minutes_since = (time.time() - last_event_time) / 60

    if event == last_event and minutes_since < EVENT_DEDUP_MIN:
        print(f"⏭️ 事件「{event}」30分钟内已通知，跳过")
        return False, ""

    emoji = "🚼🚶" if "出门" in event else "🚼🏠"
    msg = f"{emoji} 锐锐{event}！猫眼检测到婴儿车"

    state["last_event"] = event
    state["last_event_time"] = time.time()

    return True, msg


# ── 主流程 ──

def run_analyze():
    gemini_key = open(GEMINI_KEY_PATH).read().strip()
    now = datetime.now()
    tracker_state = load_tracker_state()
    stats = load_stats()

    captures = get_recent_captures()
    total = sum(len(v) for v in captures.values())
    if total == 0:
        print("没有截图可分析")
        return

    # L1: 帧差检测
    batch_diff = compute_batch_diff(captures)
    last_gemini = tracker_state.get("last_gemini_time", 0)
    minutes_since = (time.time() - last_gemini) / 60
    significant_change = batch_diff > DIFF_THRESHOLD
    force_check = minutes_since >= FORCE_ANALYZE_MIN

    print(f"📊 帧差={batch_diff:.1f} (阈值{DIFF_THRESHOLD}) | 距上次={minutes_since:.0f}min")

    if not significant_change and not force_check:
        # L1: 无变化 — 跳过 Gemini，但检查持续状态告警
        baby_state = load_baby_state()
        alerts = evaluate_alerts(baby_state, [])
        for a in alerts:
            send_alert(a)

        last_desc = baby_state["status"]
        print(f"⚪ 无变化，延续 {last_desc}")

        log_file = get_log_file()
        log_file.parent.mkdir(exist_ok=True)
        with open(log_file, "a") as f:
            f.write(f"- {now.strftime('%H:%M')} | (无变化) 延续: {last_desc}\n")

        update_stats(stats, called_gemini=False)
        return

    # L2: Gemini 分析
    reason = "画面变化" if significant_change else "定期强制"
    print(f"🔴 触发分析（{reason}）")

    bedroom_sampled = sample_evenly(captures["bedroom"], MAX_PER_CAM)
    living_sampled = sample_evenly(captures["living"], MAX_PER_CAM)
    selected = bedroom_sampled + living_sampled
    print(f"📷 采样{len(selected)}张（卧室{len(bedroom_sampled)} + 客厅{len(living_sampled)}）")

    try:
        result_text, total_size = call_gemini(selected, gemini_key)
        print(f"📦 {total_size // 1024}KB → 🤖 {result_text}")

        # 更新状态机
        summary = result_text.strip().split("\n")[0].strip()
        parsed = parse_gemini_result(summary)
        baby_state = load_baby_state()
        old_status = baby_state["status"]
        baby_state, transitions = update_state(baby_state, parsed)
        new_status = baby_state["status"]
        save_baby_state(baby_state)

        # 评估告警（状态转换类）
        alerts = evaluate_alerts(baby_state, transitions)
        for a in alerts:
            send_alert(a)

        # 猫眼事件检查：室内状态变化时触发
        event = None
        ruirui_visible = new_status in ("sleeping", "playing", "held", "eating", "alone_awake")
        was_visible = old_status in ("sleeping", "playing", "held", "eating", "alone_awake")

        if was_visible and not ruirui_visible:
            # 锐锐消失了 → 可能出门
            print("👀 锐锐从室内消失，检查猫眼...")
            has_stroller, _ = check_door_event("out", gemini_key)
            if has_stroller:
                event = "出门"
        elif not was_visible and ruirui_visible:
            # 锐锐出现了 → 可能回来
            print("👀 锐锐重新出现，检查猫眼...")
            has_stroller, _ = check_door_event("in", gemini_key)
            if has_stroller:
                event = "回来"

        # 处理出门/回来事件通知
        if event:
            should_notify, notify_msg = handle_event(event, tracker_state, now)
            if should_notify:
                print(f"🚼 NOTIFY: {notify_msg}")
                from alert import notify_feishu
                try:
                    notify_feishu(notify_msg)
                except Exception as e:
                    print(f"❌ 飞书通知失败: {e}")

        # 写日志
        log_file = get_log_file()
        log_file.parent.mkdir(exist_ok=True)
        status_tag = f"[{new_status}]"
        entry = f"- {now.strftime('%H:%M')} {status_tag} | {summary}\n"
        if event:
            entry += f"  - ⚡ EVENT: {event}\n"
        with open(log_file, "a") as f:
            f.write(entry)

        # 更新 tracker state
        tracker_state["last_gemini_time"] = time.time()
        tracker_state["last_result"] = result_text
        save_tracker_state(tracker_state)

        stats, day = update_stats(stats, called_gemini=True, num_images=len(selected))
        print(f"✅ 状态={baby_state['status']} | 📈 今日{day['calls']}次 ${day['cost_usd']:.4f}")

    except Exception as e:
        print(f"❌ 分析失败: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(e.response.text[:500])
        baby_state = load_baby_state()
        baby_state["consecutive_unknown"] = baby_state.get("consecutive_unknown", 0) + 1
        save_baby_state(baby_state)
        update_stats(stats, called_gemini=False)


if __name__ == "__main__":
    run_analyze()
