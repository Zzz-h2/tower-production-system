# -*- coding: utf-8 -*-
"""业务时区与「业务今天」的单一来源（single source of truth）。

背景（跨时区缺陷）：
    系统用户均在东八区（北京时间）。若各处直接用 ``date.today()`` / ``datetime.now()``，
    取到的是**运行环境/OS 时区**的今天。容器基础镜像（python:3.11-slim）默认 UTC，
    于是在北京时间 00:00–08:00 期间，"容器今天" = "用户本地今天 − 1"，
    导致填报日期窗口 `[今天 − BACKFILL_DAYS, 今天]`、四分组、时间闸门等出现跨天错位。

约定：
    本项目所有依赖"今天/当前时刻"的**业务**判定（填报窗口、四分组、工序时间规则、
    出品排名、里程碑倒排、月份缺省值、导入完成日期……）都必须经本模块取"业务今天/业务现在"，
    不得直接使用 ``date.today()`` / ``datetime.now()``。

    例外（有意为之、保持现状）：
      * ``security.py`` 的 JWT ``iat/exp``、``deps.py`` 的空闲超时——基于 UTC 的绝对时间，
        与业务时区无关，必须继续用 ``datetime.now(timezone.utc)``。
      * 纯测试脚本（``backend/qa_edward/*``、根目录 ``test_bugs.py``）不在运行时路径内。

时区实现：
    优先 ``zoneinfo.ZoneInfo("Asia/Shanghai")``（需 IANA tzdata：容器已由 Dockerfile 安装
    OS tzdata，并可另装 PyPI ``tzdata`` 兜底）；若运行环境无 IANA 数据（如未装 tzdata 的
    Windows），退化为固定 UTC+8。中国标准时间恒为 UTC+8、自 1991 年起无夏令时，
    固定偏移与 IANA ``Asia/Shanghai`` 在当今及可预见日期上完全等价。
"""
from datetime import date, datetime, timedelta, timezone

BUSINESS_TZ_NAME = "Asia/Shanghai"

try:  # 优先 IANA 时区（容器装 OS tzdata 或 PyPI tzdata 时命中）
    from zoneinfo import ZoneInfo

    BUSINESS_TZ = ZoneInfo(BUSINESS_TZ_NAME)
    TZ_SOURCE = f"zoneinfo:{BUSINESS_TZ_NAME}"
except Exception:  # noqa: BLE001 — 缺 IANA 数据时退化为固定 UTC+8
    BUSINESS_TZ = timezone(timedelta(hours=8))
    TZ_SOURCE = "fixed:UTC+08:00"


def business_now() -> datetime:
    """业务时区的当前时间（带 tzinfo）。"""
    return datetime.now(BUSINESS_TZ)


def business_today() -> date:
    """业务时区的「今天」（全项目单一来源）。"""
    return business_now().date()
