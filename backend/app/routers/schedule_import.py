# -*- coding: utf-8 -*-
"""Excel 排产导入 API。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from ..core import db
from ..core.deps import require_admin, require_project_access
from ..services.schedule_import import parse_upload_full
from ..services.dispatch_import import resolve_plan_month

router = APIRouter(prefix="/api/projects", tags=["import"])


@router.post("/{pid}/import-schedule")
async def import_schedule(pid: int, file: UploadFile = File(...),
                          manager: str | None = Form(None),
                          monthly_plan: int = Form(0),
                          plan_month: str | None = Form(None),
                          user: dict = Depends(require_admin)):
    """上传排产 Excel → 解析聚合 → 写入 process_node_plans。（仅 admin，归属兜底）

    多负责人（v6.0）：
      - manager：本次导入归属的负责人。多人项目必填且必须在 delivery_person 拆分结果内；
        单人项目自动取该负责人；无负责人字段的项目保持 None（历史行为）。
      - monthly_plan：该负责人申报的本月计划数（方案P，独立申报，不校验求和）。
      - 覆盖语义：只替换该负责人名下的排产工序行（并吸收历史 NULL 行），不影响其他负责人。

    归属月（v7.2）：
      - plan_month：本次排产的归属月 'YYYY-MM'。前端默认取页面当前共享月份、可手动改；
        未传或格式非法时由 resolve_plan_month 解析（显式 > 文件名 > 当前自然月）。
      - 作用：① 每个排产工序行带归属月，使「本月是否上传过排产」不再靠「有没有工序行」推测
        （手动完成占位行 process_order=99 与独立工序 90/91 都不是排产上传的证据）；
        ② 导入成功后写一条 schedule_imports 台账；
        ③ 被替换掉的旧行先归档到 process_node_plans_history 再删除（替换而非销毁）。
    """
    if not file.filename or not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    # ---- 排产归属月解析（格式非法 → 400，不猜） ----
    try:
        resolved_month = resolve_plan_month(plan_month, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ---- 负责人解析与校验 ----
    managers = db.split_managers(project.get("delivery_person"))
    mgr: str | None = manager.strip() if manager and manager.strip() else None
    if len(managers) > 1:
        if not mgr:
            raise HTTPException(
                status_code=400,
                detail=f"该项目有 {len(managers)} 位负责人（{'/'.join(managers)}），请先选择本次导入归属的负责人",
            )
        if mgr not in managers:
            raise HTTPException(
                status_code=400,
                detail=f"负责人「{mgr}」不在该项目的负责人名单内（{'/'.join(managers)}）",
            )
    elif len(managers) == 1:
        mgr = mgr or managers[0]      # 单人项目自动归属，无需前端强制选择

    content = await file.read()
    plans, warnings, durations = parse_upload_full(content, file.filename)

    success = db.insert_node_plans(pid, plans, mgr, durations, plan_month=resolved_month)

    # 排产上传台账：只有真正写入计划行时才记账——0 行的导入不构成「本月已上传排产」的证据
    if success > 0:
        db.upsert_schedule_import(pid, resolved_month, mgr or "", success, file.filename)

    # 该负责人申报的本月计划数（仅负责人明确时记录）
    plan_val = int(monthly_plan or 0)
    if mgr and plan_val > 0:
        db.upsert_manager_monthly_plan(pid, mgr, plan_val)

    scope = f"（负责人：{mgr}）" if mgr else "（未区分负责人）"
    return {
        "message": f"✅ 导入成功：{success} 个节点计划{scope}（排产归属 {resolved_month}，工序：{file.filename}）",
        "success": success,
        "manager": mgr,
        "plan_month": resolved_month,
        "monthly_plan": plan_val if mgr else 0,
        "warnings": warnings[:20],
    }
