# -*- coding: utf-8 -*-
"""配置查询接口：前端启动时拉取排产工序清单与标准工期（单一来源）。"""
from fastapi import APIRouter

from ..core.config import SCHEDULE_PROCESS_NAMES, SCHEDULE_PROCESS_DAYS

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/schedule")
def get_schedule_config():
    """返回排产工序顺序与各工序标准自然日工期（供前端里程碑倒排设置默认值）。"""
    return {
        "process_names": SCHEDULE_PROCESS_NAMES,
        "default_durations": SCHEDULE_PROCESS_DAYS,
    }