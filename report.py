#!/usr/bin/env python3
"""锐锐活动报告 - 用 Gemini 生成汇报"""

import os, sys, requests, json, shutil
from datetime import datetime, timedelta
from pathlib import Path

from config import GEMINI_KEY_PATH, LOG_DIR
ARCHIVE_DIR = LOG_DIR


def load_key():
    try:
        return open(GEMINI_KEY_PATH).read().strip()
    except FileNotFoundError:
        print(f"ERROR: {GEMINI_KEY_PATH} not found"); sys.exit(1)


def read_log():
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = LOG_DIR / f"ruirui_{today}.md"
    if not log_file.exists():
        return ""
    return log_file.read_text(encoding="utf-8")


def filter_last_hour(log_text):
    """筛选最近一小时的记录"""
    now = datetime.now()
    one_hour_ago = now - timedelta(hours=1)
    lines = []
    for line in log_text.splitlines():
        if not line.startswith("- "):
            continue
        try:
            time_str = line.split("|")[0].replace("- ", "").strip()
            t = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year, month=now.month, day=now.day)
            if t >= one_hour_ago:
                lines.append(line)
        except:
            continue
    return "\n".join(lines)


def ask_gemini(prompt, api_key):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={api_key}"
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, json=payload, timeout=60)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        print(f"Gemini 请求失败: {e}")
        return None


def hourly_report(api_key):
    log = read_log()
    recent = filter_last_hour(log)
    if not recent:
        print("过去一小时没有记录")
        return

    now = datetime.now()
    hour_ago = now - timedelta(hours=1)
    prompt = f"""以下是锐锐（8个月婴儿）过去一小时的活动记录：

{recent}

请生成简洁的活动汇报，格式：
👶 {hour_ago.strftime('%H:%M')}-{now.strftime('%H:%M')} 锐锐动态：
- 用时间线展示活动变化
- 状态没变就简单说"一直在睡"之类
- 不要啰嗦"""

    result = ask_gemini(prompt, api_key)
    if result:
        print(result)


def daily_report(api_key):
    log = read_log()
    if not log.strip():
        print("今天没有记录")
        return

    today = datetime.now().strftime("%Y-%m-%d")
    prompt = f"""以下是锐锐（8个月婴儿）今天的全部活动记录：

{log}

请生成全天活动报告，包含：
1. 全天时间线（关键状态变化）
2. 统计：睡眠时长、活动时长、各房间停留时间
3. 作息规律观察
4. 简洁明了，不要废话

标题用：📋 锐锐 {today} 全天活动报告"""

    result = ask_gemini(prompt, api_key)
    if result:
        print(result)

    # 归档
    archive_file = ARCHIVE_DIR / f"ruirui_{today}.md"
    archive_file.write_text(log, encoding="utf-8")
    print(f"\n📁 已归档到 {archive_file}")

    # 清空日志，保留标题
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y年%-m月%-d日")
    weekday = ["周一","周二","周三","周四","周五","周六","周日"][(datetime.now() + timedelta(days=1)).weekday()]
    # 日志已按天分文件，无需清空
    print("🧹 日志已清空")


def main():
    if len(sys.argv) < 2:
        print("用法: report.py [hourly|daily]"); sys.exit(1)

    api_key = load_key()
    cmd = sys.argv[1]

    if cmd == "hourly":
        hourly_report(api_key)
    elif cmd == "daily":
        daily_report(api_key)
    else:
        print(f"未知命令: {cmd}"); sys.exit(1)


if __name__ == "__main__":
    main()
