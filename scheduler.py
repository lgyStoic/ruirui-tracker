#!/usr/bin/env python3
"""统一调度入口：每分钟由 crontab 调用

每分钟：capture.py 截图
每10分钟：analyze.py 分析（帧差→Gemini→状态机→告警→EVENT）
"""

from datetime import datetime
from config import RUN_HOUR_START, RUN_HOUR_END


def main():
    now = datetime.now()
    hour = now.hour
    minute = now.minute

    # 时间范围检查
    if hour < RUN_HOUR_START or hour >= RUN_HOUR_END:
        return

    # 每分钟：采集
    from capture import run_capture
    results = run_capture()

    # 每10分钟：分析
    if minute % 10 == 0:
        from analyze import run_analyze
        run_analyze()


if __name__ == "__main__":
    main()
