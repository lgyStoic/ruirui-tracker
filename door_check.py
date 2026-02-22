"""猫眼事件检查：仅在室内状态变化时调用

不轮询截图，而是查萤石云告警API获取移动侦测事件+截图，
然后用 Gemini 判断是否有婴儿车（出门/回来）。
"""

import time, io, base64, requests
from datetime import datetime
from pathlib import Path
from PIL import Image

from config import *


DOOR_PROMPT = """你看到的是门口猫眼（海康DP2C）的移动侦测告警截图，拍摄的是门外走廊。

请判断画面中是否有婴儿车/推车/伞车。

规则：
- 有婴儿车 → 回答 YES
- 没有婴儿车（只是路人、邻居、快递等）→ 回答 NO

只输出 YES 或 NO，不要多余文字。"""


def get_ys7_token():
    """获取萤石云 access token"""
    appkey = open(YS7_APPKEY_PATH).read().strip()
    secret = open(YS7_SECRET_PATH).read().strip()
    r = requests.post("https://open.ys7.com/api/lapp/token/get",
                       data={"appKey": appkey, "appSecret": secret}, timeout=10)
    r.raise_for_status()
    data = r.json()["data"]
    return data["accessToken"]


def get_recent_alarms(token, serial, minutes=15):
    """查询最近N分钟的告警事件"""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - minutes * 60 * 1000
    
    r = requests.post("https://open.ys7.com/api/lapp/alarm/device/list",
                       data={
                           "accessToken": token,
                           "deviceSerial": serial,
                           "startTime": start_ms,
                           "endTime": now_ms,
                           "pageSize": 10,
                       }, timeout=15)
    r.raise_for_status()
    result = r.json()
    if result["code"] != "200":
        raise ValueError(f"API error: {result['msg']}")
    return result.get("data", [])


def download_alarm_pic(pic_url):
    """下载告警截图"""
    r = requests.get(pic_url, timeout=15)
    r.raise_for_status()
    if len(r.content) < 1000:
        raise ValueError(f"image too small: {len(r.content)} bytes")
    return r.content


def resize_image_bytes(img_bytes):
    img = Image.open(io.BytesIO(img_bytes))
    if img.width > RESIZE_WIDTH:
        ratio = RESIZE_WIDTH / img.width
        new_h = int(img.height * ratio)
        img = img.resize((RESIZE_WIDTH, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def check_stroller_gemini(images, gemini_key):
    """用 Gemini 判断告警截图中是否有婴儿车"""
    parts = []
    for i, img_bytes in enumerate(images):
        resized = resize_image_bytes(img_bytes)
        parts.append({"text": f"[告警截图 {i+1}]"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": base64.b64encode(resized).decode()
            }
        })
    parts.append({"text": DOOR_PROMPT})

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={gemini_key}"
    payload = {"contents": [{"parts": parts}]}

    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    result = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
    return "YES" in result


def check_door_event(direction, gemini_key):
    """检查猫眼告警，判断是否有婴儿车出入
    
    Args:
        direction: "out" (锐锐消失→可能出门) 或 "in" (锐锐出现→可能回来)
        gemini_key: Gemini API key
    
    Returns:
        (has_stroller: bool, alarm_count: int)
    """
    serial = list(YS7_CAMERAS.values())[0]  # K66700907
    
    try:
        token = get_ys7_token()
        alarms = get_recent_alarms(token, serial, minutes=15)
        
        if not alarms:
            print(f"🚪 猫眼：最近15分钟无告警")
            return False, 0
        
        print(f"🚪 猫眼：最近15分钟有{len(alarms)}条告警，下载截图分析...")
        
        # 下载最近3张告警截图（去重、省成本）
        images = []
        for alarm in alarms[:3]:
            pic_url = alarm.get("alarmPicUrl")
            if not pic_url:
                continue
            try:
                img = download_alarm_pic(pic_url)
                images.append(img)
            except Exception as e:
                print(f"  ⚠️ 下载告警图片失败: {e}")
        
        if not images:
            print(f"🚪 猫眼：告警截图下载失败")
            return False, len(alarms)
        
        # Gemini 判断有没有婴儿车
        has_stroller = check_stroller_gemini(images, gemini_key)
        emoji = "🍼" if has_stroller else "👤"
        print(f"🚪 猫眼：{emoji} {'有婴儿车!' if has_stroller else '无婴儿车（路人）'}（分析了{len(images)}张告警图）")
        
        return has_stroller, len(alarms)
        
    except Exception as e:
        print(f"🚪 猫眼检查失败: {e}")
        return False, 0
