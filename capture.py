"""采集层：多源抓帧 + 重试 + 帧差检测"""

import time, io, json, requests
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageChops

from config import *


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, default=str))


def frame_diff(img_bytes, last_path):
    try:
        curr = Image.open(io.BytesIO(img_bytes)).convert("L").resize(CMP_SIZE)
        prev = Image.open(last_path).convert("L").resize(CMP_SIZE)
        diff_img = ImageChops.difference(curr, prev)
        pixels = list(diff_img.convert("L").tobytes())
        return sum(pixels) / len(pixels)
    except:
        return 999.0


def retry_request(fn, max_retry=CAPTURE_MAX_RETRY, backoff=None):
    """通用重试包装"""
    backoff = backoff or CAPTURE_RETRY_BACKOFF
    last_err = None
    for i in range(max_retry):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if i < max_retry - 1:
                wait = backoff[min(i, len(backoff) - 1)]
                time.sleep(wait)
    raise last_err


def capture_go2rtc(src):
    """从 go2rtc 抓帧"""
    def _fetch():
        r = requests.get(f"{GO2RTC_URL}/api/frame.jpeg?src={src}", timeout=30)
        r.raise_for_status()
        if len(r.content) < 1000:
            raise ValueError(f"image too small: {len(r.content)} bytes")
        return r.content
    return retry_request(_fetch)


def get_ys7_token(state):
    """获取或复用萤石云 token"""
    token = state.get("ys7_token")
    expire = state.get("ys7_token_expire", 0)
    if token and time.time() * 1000 < expire - 60000:
        return token

    appkey = open(YS7_APPKEY_PATH).read().strip()
    secret = open(YS7_SECRET_PATH).read().strip()
    r = requests.post("https://open.ys7.com/api/lapp/token/get",
                       data={"appKey": appkey, "appSecret": secret}, timeout=10)
    r.raise_for_status()
    data = r.json()["data"]
    state["ys7_token"] = data["accessToken"]
    state["ys7_token_expire"] = data["expireTime"]
    return data["accessToken"]


def capture_ys7(serial, token):
    """从萤石云抓截图"""
    def _fetch():
        r = requests.post("https://open.ys7.com/api/lapp/device/capture",
                           data={"accessToken": token, "deviceSerial": serial, "channelNo": 1},
                           timeout=15)
        r.raise_for_status()
        result = r.json()
        if result["code"] != "200":
            raise ValueError(f"API: {result['msg']}")
        img_r = requests.get(result["data"]["picUrl"], timeout=15)
        img_r.raise_for_status()
        if len(img_r.content) < 1000:
            raise ValueError(f"image too small: {len(img_r.content)} bytes")
        return img_r.content
    return retry_request(_fetch)


def check_go2rtc_health():
    """检查 go2rtc 是否在线"""
    try:
        r = requests.get(f"{GO2RTC_URL}/api/streams", timeout=5)
        return r.status_code == 200
    except:
        return False


def run_capture():
    """执行一次采集，返回结果字典"""
    CAPTURE_DIR.mkdir(exist_ok=True)
    now_str = datetime.now().strftime("%H%M")
    state = load_state()
    results = {}

    # 健康检查
    go2rtc_ok = check_go2rtc_health()
    if not go2rtc_ok:
        state["go2rtc_failures"] = state.get("go2rtc_failures", 0) + 1
        print(f"⚠️ go2rtc 不在线 (连续{state['go2rtc_failures']}次)")
    else:
        state["go2rtc_failures"] = 0

    # go2rtc 摄像头
    for name, src in GO2RTC_CAMERAS.items():
        try:
            if not go2rtc_ok:
                raise ConnectionError("go2rtc offline")
            img_bytes = capture_go2rtc(src)
            output_path = CAPTURE_DIR / f"{name}_{now_str}.jpg"

            last_key = f"last_{name}"
            diff = 999.0
            if last_key in state and Path(state[last_key]).exists():
                diff = frame_diff(img_bytes, state[last_key])

            output_path.write_bytes(img_bytes)
            state[last_key] = str(output_path)

            changed = diff > DIFF_THRESHOLD
            results[name] = {"ok": True, "size": len(img_bytes), "diff": diff, "changed": changed}
            print(f"{'🔴' if changed else '⚪'} {name}: {len(img_bytes)//1024}KB diff={diff:.1f}")

        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
            print(f"❌ {name}: {e}")

    # 猫眼不再轮询截图 — 改为事件驱动（见 door_check.py）

    # 汇总
    any_change = any(r.get("changed", False) for r in results.values())
    any_failure = any(not r.get("ok", False) for r in results.values())
    state["last_capture"] = now_str
    state["last_capture_ts"] = time.time()
    state["last_any_change"] = any_change
    state["last_any_failure"] = any_failure
    save_state(state)

    # 心跳
    HEARTBEAT_FILE.write_text(str(time.time()))

    # 清理30分钟前的旧图
    cutoff = time.time() - 1800
    for f in CAPTURE_DIR.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink()

    return results


if __name__ == "__main__":
    run_capture()
