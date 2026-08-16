"""
pages/2_项目详情.py — 单项目详情页

功能：
- 项目信息卡（基本信息 + 进度 + 风险）
- 工序进度甘特图（Plotly 横向甘特图）
- 工序明细表格（含状态颜色标识）
- 风险与异常管理（提报 + 闭环）
- 里程碑倒排工具
- 工序节点计划管控（排产矩阵导入 + 时间轴 + 实际填报）
- 工序节点预警（四态统计 + 逾期/部分完成重点提示）

Author: Senior Developer / Engineer
Date: 2026-08-03 / 2026-08-12 (v4.0 节点计划管控)
"""

import streamlit as st
import sys
import os
from datetime import date, timedelta
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from config import (
    COLORS, PROCESS_NAMES, PROCESS_DAYS, TOTAL_DAYS,
    RESPONSIBILITY_OPTIONS, CUSTOM_CSS, SCHEDULE_PROCESS_NAMES
)
from database import (
    get_project_by_id, get_project_processes, update_process,
    insert_anomaly, get_project_anomalies, update_anomaly_status,
    update_project_risk_level, delete_project, update_project,
    init_project_processes, regenerate_process_plan,
    insert_node_plans, get_node_plans,
    upsert_node_actual, get_node_actuals,
)
from utils import (
    parse_date, calculate_lag_days, count_workdays_between,
    generate_forward_plan, generate_backward_plan,
    refresh_processes_from_db, judge_warning_level,
    estimate_delivery_date,
)
from utils.business_logic import judge_node_status, judge_process_node_status
from utils.schedule_import import parse_schedule_excel as parse_node_schedule_excel


def _dbg(module: str, project_id, result, extra: str = ""):
    """控制台调试日志（等价浏览器 console.log）：打印请求入参与返回结果摘要。

    输出到 streamlit run 的终端，格式：模块名 | 入参 project_id | 返回条数 | 附加信息。
    """
    if hasattr(result, "__len__"):
        n = len(result)
    else:
        n = result if result is not None else 0
    print(f"[IMPORT-DEBUG] {module} | 入参 project_id={project_id} | 返回 {n} 条 {extra}".rstrip())
    return result




def main():
    """项目详情页主入口"""
    st.set_page_config(
        page_title="项目详情",
        page_icon="📋",
        layout="wide",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # 优先从 URL 参数恢复项目ID（刷新浏览器时 session_state 会丢失，URL 参数可持久化）
    query_pid = st.query_params.get("project_id", None)
    if query_pid:
        try:
            st.session_state.selected_project_id = int(query_pid)
        except ValueError:
            pass

    # 获取项目ID
    project_id = st.session_state.get("selected_project_id")

    if not project_id:
        st.warning("未选择项目，请从主界面跳转。")
        if st.button("← 返回项目列表"):
            st.switch_page("app.py")
        return

    # 获取项目数据
    project = get_project_by_id(project_id)
    if not project:
        st.error(f"项目不存在（ID: {project_id}）")
        if st.button("← 返回项目列表"):
            st.switch_page("app.py")
        return

    # 成功加载项目后同步 URL，确保刷新/直达时 URL 始终携带正确 project_id
    st.query_params["project_id"] = str(project_id)

    # ============================================================
    # 顶部导航
    # ============================================================
    col1, col2, col3 = st.columns([1, 3, 1])
    with col1:
        if st.button("← 返回列表", use_container_width=True):
            st.query_params.pop("project_id", None)  # 清除 URL 中的项目ID，避免列表页残留
            st.session_state.selected_project_id = None
            st.switch_page("app.py")
    with col2:
        st.title(f"📋 {project.get('project_name', 'N/A')}")
    with col3:
        if st.button("🗑️ 删除项目", type="secondary", use_container_width=True):
            st.session_state.confirm_delete = True

    # 删除确认
    if st.session_state.get("confirm_delete"):
        st.error(f"⚠️ 确认删除项目「{project.get('project_name')}」吗？此操作不可撤销！")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 确认删除", type="primary"):
                delete_project(project_id)
                st.cache_data.clear()  # 删除后清除只读查询缓存
                st.session_state.selected_project_id = None
                st.session_state.confirm_delete = False
                st.query_params.pop("project_id", None)  # 清除 URL 中的项目ID
                st.success("项目已删除")
                st.switch_page("app.py")
        with c2:
            if st.button("❌ 取消"):
                st.session_state.confirm_delete = False
                st.rerun()

    st.divider()

    # 单次加载工序数据（@st.cache_data 缓存复用，交互间不重复查库）
    processes = _dbg("公共-工序加载", project_id, get_project_processes(project_id))
    processes_with_status = refresh_processes_from_db(processes)

    # ============================================================
    # 项目信息卡（共享已加载数据，不再内部查库）
    # ============================================================
    _render_project_info_card(project, processes_with_status)

    # ============================================================
    # Tab 页签：六个标签【全部渲染】，前端 tabs 组件自动隐藏非激活标签内容
    # ============================================================
    # 关键修复：放弃"仅渲染激活 Tab"的懒加载方案。
    # 懒加载依赖 st.session_state["detail_tabs"] 与前端激活状态严格同步，
    # 前端一旦重置激活标签，会出现"标签在但内容区空白"（用户看到的 5 Tab 看不见数据）。
    # 全部渲染后：6 个模块内容始终存在于 DOM，前端切换标签只是显示切换，绝对可靠。
    TAB_LABELS = [
        "📊 工序甘特图",
        "📋 工序明细",
        "⚠️ 风险与异常",
        "📅 里程碑倒排",
        "📅 节点计划",
        "🚨 节点预警",
    ]
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(TAB_LABELS)

    with tab1:
        _render_gantt_chart(project, processes_with_status)
    with tab2:
        _render_process_table(project_id, project, processes_with_status)
    with tab3:
        _render_risk_anomaly(project_id, project, processes_with_status)
    with tab4:
        _render_milestone_planning(project, processes_with_status)
    with tab5:
        _render_node_schedule(project_id, project)
    with tab6:
        _render_node_warning(project_id, project)


# ============================================================
# 项目信息卡
# ============================================================

def _close_edit_panel(project_id):
    """统一关闭「编辑项目信息」面板：清理编辑状态与日期维护模式状态"""
    edit_key = f"show_edit_project_{project_id}"
    mode_key = f"edit_date_mode_{project_id}"
    for k in [edit_key, mode_key]:
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

def _render_project_info_card(project: dict, processes_with_status: Optional[list] = None):
    """渲染项目信息卡（工序数据由 main() 共享传入，避免重复查库）"""
    # 当前工序（复用传入数据，缺失时兜底加载）
    if processes_with_status is None:
        proc_list = get_project_processes(project.get("id"))
        processes_with_status = refresh_processes_from_db(proc_list)
    proc_with_status = processes_with_status

    # 风险等级：根据实时工序状态判定（与工序明细口径一致，不依赖静态 risk_level 字段）
    risk, _ = judge_warning_level(processes_with_status or [])

    risk_colors = {
        "normal": ("#38a169", "#f0fff4", "正常"),
        "warning": ("#d69e2e", "#fffff0", "预警"),
        "delayed": ("#e53e3e", "#fff5f5", "延期"),
    }
    risk_color, risk_bg, risk_label = risk_colors.get(risk, risk_colors["normal"])
    progress = project.get("progress_pct", 0)

    current_proc = "未开始"
    last_proc_name = proc_with_status[-1].get("process_name", "") if proc_with_status else ""
    for p in proc_with_status:
        if p.get("status") in ("in_progress", "delayed"):
            current_proc = p.get("process_name", "")
            break
    else:
        # 全完成 → 显示最后一道工序
        all_done = all(p.get("status") == "completed" for p in proc_with_status)
        if all_done and last_proc_name:
            current_proc = f"{last_proc_name}(已完成)"

    st.markdown(f"""
    <div style="
        background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
        border-radius: 16px;
        padding: 28px 32px;
        color: white;
        margin-bottom: 24px;
        display: flex;
        flex-wrap: wrap;
        gap: 24px;
        align-items: center;
        box-shadow: 0 4px 24px rgba(26, 54, 93, 0.25);
    ">
        <div style="flex: 1.6; min-width: 280px; background: rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 16px;">
            <div style="font-size: 12px; opacity: 0.75; font-weight: 600; letter-spacing: 1px; margin-bottom: 8px;">基本信息</div>
            <div style="display: flex; flex-wrap: wrap; gap: 16px;">
                <div style="flex: 1; min-width: 140px;">
                    <div style="font-size: 13px; opacity: 0.7; margin-bottom: 4px;">钢塔厂家</div>
                    <div style="font-size: 16px; font-weight: 600;">{project.get('factory_name', 'N/A')}</div>
                </div>
                <div style="flex: 1; min-width: 120px;">
                    <div style="font-size: 13px; opacity: 0.7; margin-bottom: 4px;">交付负责人</div>
                    <div style="font-size: 16px; font-weight: 600;">{project.get('delivery_person', 'N/A')}</div>
                </div>
                <div style="flex: 1.4; min-width: 200px;">
                    <div style="font-size: 13px; opacity: 0.7; margin-bottom: 4px;">计划开工 → 计划交付</div>
                    <div style="font-size: 16px; font-weight: 600;">{project.get('plan_start_date') or '—'} → {project.get('plan_end_date') or '—'}</div>
                </div>
            </div>
        </div>
        <div style="flex: 1.2; min-width: 260px; background: rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 16px;">
            <div style="font-size: 12px; opacity: 0.75; font-weight: 600; letter-spacing: 1px; margin-bottom: 8px;">整体进度</div>
            <div style="font-size: 13px; opacity: 0.9; margin-bottom: 6px;">{progress}% · 当前工序：{current_proc}</div>
            <div style="
                height: 12px;
                background: rgba(255,255,255,0.2);
                border-radius: 6px;
                overflow: hidden;
            ">
                <div style="
                    width: {progress}%;
                    height: 100%;
                    background: {risk_color};
                    border-radius: 6px;
                    transition: width 0.5s ease;
                "></div>
            </div>
        </div>
        <div style="flex: 0.8; min-width: 150px; background: rgba(255,255,255,0.08); border-radius: 10px; padding: 12px 16px; text-align: center;">
            <div style="font-size: 12px; opacity: 0.75; font-weight: 600; letter-spacing: 1px; margin-bottom: 8px;">风险等级</div>
            <div style="
                display: inline-block;
                padding: 6px 18px;
                border-radius: 20px;
                background: {risk_bg};
                color: {risk_color};
                font-weight: 700;
                font-size: 16px;
            ">{risk_label}</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ============ 项目信息编辑（v3.1） ============
    project_id = project.get("id")
    edit_key = f"show_edit_project_{project_id}"
    if st.button("✏️ 编辑项目", key=f"btn_edit_project_{project_id}"):
        st.session_state[edit_key] = True

    if st.session_state.get(edit_key):
        with st.container(border=True):
            st.subheader("✏️ 编辑项目信息")

            # 顶部关闭按钮（所有模式通用，位于标题下方左侧）
            close_col, _ = st.columns([1, 6])
            with close_col:
                if st.button("✕ 关闭", key=f"close_edit_top_{project_id}", type="secondary"):
                    _close_edit_panel(project_id)

            # ---- 二模式切换：自动重算 / 手工修改日期 ----
            mode_key = f"edit_date_mode_{project_id}"
            if mode_key not in st.session_state:
                st.session_state[mode_key] = "auto"
            # 如果上次残留在一键导入模式，则重置为自动重算
            if st.session_state[mode_key] == "import":
                st.session_state[mode_key] = "auto"
            m1, m2 = st.columns(2)
            with m1:
                if st.button("🔄 自动重算", key=f"mode_auto_{project_id}",
                             type="secondary" if st.session_state[mode_key] != "auto" else "primary",
                             use_container_width=True):
                    st.session_state[mode_key] = "auto"; st.rerun()
            with m2:
                if st.button("✏️ 手工修改日期", key=f"mode_manual_{project_id}",
                             type="secondary" if st.session_state[mode_key] != "manual" else "primary",
                             use_container_width=True):
                    st.session_state[mode_key] = "manual"; st.rerun()

            # ---------- 模式一：自动重算（原逻辑原样保留） ----------
            if st.session_state[mode_key] == "auto":
                st.caption("补填/修改计划开工日期后，将自动重算12道工序的计划起止时间。")

                c1, c2 = st.columns(2)
                with c1:
                    edit_start = st.date_input(
                        "计划开工日期",
                        value=parse_date(project.get("plan_start_date")),
                        key=f"edit_start_{project_id}",
                    )
                with c2:
                    edit_end = st.date_input(
                        "计划交付日期",
                        value=parse_date(project.get("plan_end_date")),
                        key=f"edit_end_{project_id}",
                    )
                c3, c4 = st.columns(2)
                with c3:
                    edit_factory = st.text_input(
                        "钢塔厂家", value=project.get("factory_name", ""),
                        key=f"edit_factory_{project_id}",
                    )
                    edit_person = st.text_input(
                        "交付负责人", value=project.get("delivery_person", ""),
                        key=f"edit_person_{project_id}",
                    )
                with c4:
                    edit_plan = st.number_input(
                        "本月计划出品(段)", min_value=0,
                        value=int(project.get("monthly_plan", 0) or 0),
                        step=1, key=f"edit_plan_{project_id}",
                    )
                    st.caption("计划交付日期仅作里程碑参考，不强制校验与工序总工期一致")

                if st.button("💾 保存", key=f"save_edit_{project_id}", type="primary",
                             use_container_width=True):
                    try:
                        # 1. 更新项目基础信息
                        update_project(project_id, {
                            "factory_name": edit_factory,
                            "delivery_person": edit_person,
                            "monthly_plan": int(edit_plan),
                            "plan_start_date": (
                                edit_start.strftime('%Y-%m-%d') if edit_start else None
                            ),
                            "plan_end_date": (
                                edit_end.strftime('%Y-%m-%d') if edit_end else None
                            ),
                        })

                        # 2. 工序计划联动重算：填了开工日期 → 重算/初始化12道工序
                        if edit_start:
                            updated = regenerate_process_plan(
                                project_id, edit_start.strftime('%Y-%m-%d')
                            )
                            if updated > 0:
                                st.success(f"✅ 已重算 {updated} 道工序计划")

                        # 3. 状态重算：先清缓存再读取工序，确保按新计划日期重算 status/lag
                        st.cache_data.clear()
                        all_procs = get_project_processes(project_id)
                        refreshed = refresh_processes_from_db(all_procs)
                        for up in refreshed:
                            update_process(up["id"], {
                                "status": up["status"],
                                "lag_days": up["lag_days"],
                            })
                        # 先清缓存，确保 update_project_risk_level 读到最新工序状态
                        st.cache_data.clear()
                        update_project_risk_level(project_id)
                        st.cache_data.clear()  # 再清一次，确保后续查询读到新风险等级
                        del st.session_state[edit_key]
                        if mode_key in st.session_state:
                            del st.session_state[mode_key]
                        st.success("✅ 项目信息已更新")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 保存失败: {e}")
                        import traceback
                        st.code(traceback.format_exc()[-400:])

            # ---------- 模式二：手工逐条修改工序计划日期 ----------
            elif st.session_state[mode_key] == "manual":
                st.caption("逐条修改各工序的计划开始/结束日期（仅影响计划排程，不影响实际进度）。")
                proc_list = get_project_processes(project_id)
                if not proc_list:
                    st.info("暂无工序数据，请先在「🔄 自动重算」模式填写计划开工日期生成工序。")
                else:
                    h1, h2, h3 = st.columns([2, 2, 2])
                    h1.markdown("**工序名称**")
                    h2.markdown("**计划开始**")
                    h3.markdown("**计划结束**")
                    st.divider()

                    manual_values = []
                    for proc in proc_list:
                        pid = proc["id"]
                        ps_default = parse_date(proc.get("plan_start_date"))
                        pe_default = parse_date(proc.get("plan_end_date"))
                        c1, c2, c3 = st.columns([2, 2, 2])
                        with c1:
                            st.text_input(
                                "工序", value=proc.get("process_name", ""),
                                key=f"manual_name_{project_id}_{pid}",
                                disabled=True, label_visibility="collapsed",
                            )
                        with c2:
                            manual_ps = st.date_input(
                                "计划开始", value=ps_default,
                                key=f"manual_ps_{project_id}_{pid}",
                            )
                        with c3:
                            manual_pe = st.date_input(
                                "计划结束", value=pe_default,
                                key=f"manual_pe_{project_id}_{pid}",
                            )
                        manual_values.append((proc, manual_ps, manual_pe))

                    if st.button("💾 保存工序日期", key=f"save_manual_dates_{project_id}", type="primary",
                                 use_container_width=True):
                        # 校验：计划开始 <= 计划结束（两端均有值时校验）
                        errors = []
                        for proc, ps, pe in manual_values:
                            if ps and pe and ps > pe:
                                errors.append(
                                    f"{proc.get('process_name')}: 开始({ps.strftime('%Y-%m-%d')}) "
                                    f"晚于 结束({pe.strftime('%Y-%m-%d')})"
                                )
                        if errors:
                            st.error("❌ 存在日期校验失败：\n" + "\n".join(errors))
                        else:
                            try:
                                # 1. 逐条更新工序计划日期
                                for proc, ps, pe in manual_values:
                                    update_process(proc["id"], {
                                        "plan_start_date": (
                                            ps.strftime('%Y-%m-%d') if ps else None
                                        ),
                                        "plan_end_date": (
                                            pe.strftime('%Y-%m-%d') if pe else None
                                        ),
                                    })
                                # 2. 先清缓存再读取工序，确保按新计划日期重算 status/lag
                                st.cache_data.clear()
                                all_procs = get_project_processes(project_id)
                                refreshed = refresh_processes_from_db(all_procs)
                                for up in refreshed:
                                    update_process(up["id"], {
                                        "status": up["status"],
                                        "lag_days": up["lag_days"],
                                    })
                                # 3. 清缓存 → 项目风险等级重算 → 再清缓存
                                st.cache_data.clear()
                                update_project_risk_level(project_id)
                                st.cache_data.clear()
                                del st.session_state[edit_key]
                                if mode_key in st.session_state:
                                    del st.session_state[mode_key]
                                st.success("✅ 工序日期已保存")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ 保存失败: {e}")
                                import traceback
                                st.code(traceback.format_exc()[-400:])



# ============================================================
# 甘特图
# ============================================================

def _render_gantt_chart(project: dict, processes: list[dict]):
    """使用 Plotly 渲染横向甘特图"""
    try:
        import plotly.express as px
        import plotly.graph_objects as go
        import pandas as pd
    except ImportError:
        st.warning("请安装 plotly: pip install plotly")
        return

    if not processes:
        st.info("暂无工序数据，请先生成计划。")
        # 如果项目有计划开工日期但无工序数据，提供初始化按钮
        plan_start = project.get("plan_start_date")
        if plan_start:
            if st.button("🔄 初始化12道标准工序"):
                init_project_processes(project["id"], plan_start)
                st.rerun()
        return

    # 构建甘特图数据
    gantt_data = []
    today = date.today()
    status_colors = {
        "not_started": "#cbd5e0",  # 灰色
        "in_progress": "#4299e1",  # 蓝色
        "completed": "#48bb78",    # 绿色
        "delayed": "#fc8181",      # 红色
    }
    # 状态中文名（hover 展示用）
    status_labels = {
        "not_started": "未开始",
        "in_progress": "进行中",
        "completed": "已完成",
        "delayed": "延期",
    }
    # 工序名称 → 滞后天数 映射（实际条 hover 展示用）
    name_lag_map = {
        proc.get("process_name", ""): proc.get("lag_days", 0)
        for proc in processes
    }

    for proc in processes:
        order = proc.get("process_order", 0)
        name = proc.get("process_name", "")
        status = proc.get("status", "not_started") or "not_started"
        if status not in status_colors:
            status = "not_started"

        # 计划时间段
        plan_start_str = proc.get("plan_start_date", "")
        plan_end_str = proc.get("plan_end_date", "")
        plan_start = parse_date(plan_start_str) if plan_start_str else None
        plan_end = parse_date(plan_end_str) if plan_end_str else None

        # 实际时间段
        actual_start_str = proc.get("actual_start_date", "")
        actual_end_str = proc.get("actual_end_date", "")
        actual_start = parse_date(actual_start_str) if actual_start_str else None
        actual_end = parse_date(actual_end_str) if actual_end_str else None

        if plan_start and plan_end:
            # 计划条：浅灰半透明，仅作参考线
            gantt_data.append({
                "工序": name,
                "色键": "计划",
                "开始": plan_start,
                "结束": plan_end + timedelta(days=1),  # Plotly 结束是不包含的
                "状态": "计划",
                "滞后": "-",
                "序号": order,
            })

            # 实际条：凡有实际进度（非未开始）即渲染，按工序状态着色
            # 注意：actual_start_date 在库中可能为 NULL，起点兜底用计划开始；
            # 未完工（进行中/延期）终点用今天，让条延伸到今天。
            if status in ("in_progress", "delayed", "completed"):
                actual_start_display = actual_start or plan_start
                actual_end_display = actual_end or today
                lag = name_lag_map.get(name, 0)
                if lag > 0:
                    lag_text = f"滞后{lag}天"
                elif lag < 0:
                    lag_text = f"提前{-lag}天"
                else:
                    lag_text = "0天"
                gantt_data.append({
                    "工序": name,
                    "色键": f"实际·{status}",
                    "开始": actual_start_display,
                    "结束": actual_end_display + timedelta(days=1),  # Plotly 结束是不包含的
                    "状态": status_labels.get(status, status),
                    "滞后": lag_text,
                    "序号": order,
                })

    if not gantt_data:
        st.info("暂无甘特图数据")
        return

    df = pd.DataFrame(gantt_data)
    df = df.sort_values("序号")

    # 颜色映射：计划条固定浅灰半透明；实际条按状态着色（5 键全枚举）
    color_discrete_map = {
        "计划": "rgba(160,174,192,0.35)",
        "实际·not_started": status_colors["not_started"],
        "实际·in_progress": status_colors["in_progress"],
        "实际·completed": status_colors["completed"],
        "实际·delayed": status_colors["delayed"],
    }

    fig = px.timeline(
        df,
        x_start="开始",
        x_end="结束",
        y="工序",
        color="色键",
        color_discrete_map=color_discrete_map,
        title=f"工序进度甘特图 — {project.get('project_name', '')}",
        labels={"工序": "", "开始": "", "结束": ""},
        hover_data={"状态": True, "滞后": True},
    )

    # 倒序排列工序（从顶到下：下料→内装 ）
    fig.update_yaxes(autorange="reversed")

    # 悬停信息：工序名 / 起止日期 / 状态 / 滞后天数（覆盖默认模板，隐藏"色键"噪音）
    fig.update_traces(
        hovertemplate=(
            "%{y}<br>"
            "开始 %{base|%Y-%m-%d}<br>"
            "结束 %{x|%Y-%m-%d}<br>"
            "状态 %{customdata[0]}<br>"
            "滞后 %{customdata[1]}<extra></extra>"
        )
    )

    # 图例名称：色键 → 可读中文（避免显示"实际·completed"这类原始键）
    legend_names = {
        "计划": "计划(参考)",
        "实际·not_started": "未开始",
        "实际·in_progress": "进行中",
        "实际·completed": "已完成",
        "实际·delayed": "延期",
    }
    for tr in fig.data:
        tr.name = legend_names.get(tr.name, tr.name)

    # 添加今天竖线 — 使用 pd.Timestamp 确保与 px.timeline 的日期轴类型兼容
    fig.add_vline(
        x=pd.Timestamp(today),
        line_dash="dash",
        line_color="#e53e3e",
        annotation_text="今天",
        annotation_position="top",
    )

    fig.update_layout(
        height=500,
        margin=dict(l=10, r=10, t=40, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(
            tickformat="%m/%d",
            dtick="D1" if (df["结束"].max() - df["开始"].min()).days < 60 else "W1",
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
    )

    # 甘特图工具栏配置（最简）：
    # - 保留默认工具栏但隐藏 Plotly logo
    # - 注意：不要在此自定义 modeBarButtons——非法的按钮名（如 "zoomIn"/"autoscale"）
    #   会让 Plotly 前端 JS 抛错、中断整图渲染（曾导致甘特图只剩标题和图例）
    # - 若不想看到英文 tooltip，可将 displayModeBar 改为 False 直接隐藏工具栏
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={
            "displayModeBar": True,    # 保留工具栏
            "displaylogo": False,      # 隐藏 Plotly logo
        },
    )

    # 图例
    st.caption("图例：⬜ 计划(参考) | ⬛ 未开始 | 🟦 进行中 | 🟩 已完成 | 🟥 延期 | 🔴 - - - 今天")


# ============================================================
# 工序明细表
# ============================================================

def _calc_deviation(proc: dict) -> tuple[str, str]:
    """
    计算工序时间偏差（统一「实际完成时间」单字段判定）。
    仅基于 actual_end_date vs plan_end_date，不再依赖实际开工日期。

    Returns:
        (偏差文本, 颜色代码)
    """
    from datetime import date as dt_date

    today = dt_date.today()

    # === 统一归一化为 date 或 None ===
    actual_end = parse_date(proc.get("actual_end_date"))
    plan_end   = parse_date(proc.get("plan_end_date"))

    # ---- 分支1: 有完成时间 → 已完成（偏差与状态解耦，不论是否>今日） ----
    if actual_end is not None:
        if not plan_end:
            return ("—", "#718096")
        if actual_end < plan_end:
            days = (plan_end - actual_end).days
            return (f"提前{days}天", "#38a169")
        elif actual_end == plan_end:
            return ("准时", "#718096")
        else:
            days = (actual_end - plan_end).days
            return (f"滞后{days}天", "#e53e3e")

    # ---- 分支2: 无完成时间，今日 > 计划结束 → 延期 ----
    if plan_end and today > plan_end:
        days = (today - plan_end).days
        return (f"滞后{days}天", "#e53e3e")

    # ---- 分支3: 进行中 / 未开始 ----
    return ("—", "#718096")


def _render_process_table(project_id: int, project: dict, processes: list[dict]):
    """渲染工序明细表格"""
    if not processes:
        st.info("暂无工序数据")
        return

    st.caption("填写实际完成时间即标记工序已完成；留空则按计划周期自动判定进行中/延期/未开始。")

    # 工序明细表格：不设固定高度/滚动，高度自适应工序数据总量，全部工序完整铺开呈现
    with st.container(border=True):
        # 表头
        cols = st.columns([2, 2, 2, 1, 2, 1, 1, 2])
        headers = ["工序名称", "计划开始", "计划结束", "工期",
                   "实际完成时间", "状态", "偏差", "操作"]
        for col, header in zip(cols, headers):
            col.markdown(f"**{header}**")
        st.divider()

        status_labels = {
            "not_started": ("⬜ 未开始", "#718096"),
            "in_progress": ("🟦 进行中", "#3182ce"),
            "completed": ("🟩 已完成", "#38a169"),
            "delayed": ("🟥 延期", "#e53e3e"),
            "data_error": ("⚠️ 数据异常", "#e53e3e"),
        }

        for proc in processes:
            order = proc.get("process_order", 0)
            name = proc.get("process_name", "")
            status = proc.get("status", "not_started")
            lag = proc.get("lag_days", 0)

            # 工期列：按实际计划起止日期实时计算（自然日历天，含起止日，一周七天都计入）；
            # 日期任一缺失时回退到标准工期，避免空值显示异常。standard_days 本身不改动。
            ps_dur = parse_date(proc.get("plan_start_date"))
            pe_dur = parse_date(proc.get("plan_end_date"))
            if ps_dur and pe_dur:
                if pe_dur < ps_dur:
                    duration_days = 0
                else:
                    duration_days = (pe_dur - ps_dur).days + 1  # 含起止日
            else:
                duration_days = proc.get("standard_days", 0) or 0

            # 展示层：「数据异常」由 lag_days == -999 信号驱动，存储层仍为合法枚举值
            if lag == -999:
                status_label = "⚠️ 数据异常"
                status_color = "#e53e3e"
            else:
                status_label, status_color = status_labels.get(status, status_labels["not_started"])
            lag_color = "#e53e3e" if lag > 0 else "#718096"

            # 行背景色
            if status == "delayed" or lag == -999:
                row_bg = "#fff5f5"
            elif lag == 1:
                row_bg = "#fffff0"
            else:
                row_bg = "transparent"

            cols = st.columns([2, 2, 2, 1, 2, 1, 1, 2])

            with cols[0]:
                st.write(name)
            with cols[1]:
                st.write(str(proc.get("plan_start_date", "-")))
            with cols[2]:
                st.write(str(proc.get("plan_end_date", "-")))
            with cols[3]:
                st.write(f"{duration_days}天")
            with cols[4]:
                st.write(str(proc.get("actual_end_date", "-")))
            with cols[5]:
                st.markdown(f"<span style='color:{status_color};font-weight:600;'>{status_label}</span>",
                           unsafe_allow_html=True)
            with cols[6]:
                # 偏差列：基于「实际完成时间 vs 计划结束」计算
                deviation_text, deviation_color = _calc_deviation(proc)
                st.markdown(
                    f"<span style='color:{deviation_color};font-weight:600;'>{deviation_text}</span>",
                    unsafe_allow_html=True,
                )
            with cols[7]:
                # 操作按钮
                op_col1, op_col2 = st.columns(2)
                process_key = f"proc_{proc['id']}"
                with op_col1:
                    if st.button("📝", key=f"update_{process_key}", help="更新进度"):
                        st.session_state[f"show_update_{process_key}"] = True
                with op_col2:
                    if st.button("⚠️", key=f"anomaly_{process_key}", help="异常提报"):
                        st.session_state[f"show_anomaly_{process_key}"] = True

            # 更新进度弹窗（仅实际完成日期）
            if st.session_state.get(f"show_update_{process_key}"):
                with st.container():
                    st.markdown("---")
                    st.subheader(f"更新进度：{name}")
                    st.caption("💡 填写实际完成日期 = 工序已完成 | 留空 = 未完成/进行中")
                    new_end = st.date_input(
                        "实际完成日期",
                        value=parse_date(proc.get("actual_end_date")),
                        key=f"upd_end_{process_key}",
                    )
                    clear_end = st.checkbox(
                        "🗑️ 标记为未完成（清空完成时间）",
                        value=False,
                        key=f"clear_end_{process_key}",
                        help="勾选后保存将清空实际完成日期，工序恢复为按计划周期自动判定",
                    )
                    c1, c2, c3 = st.columns([1, 1, 2])
                    with c1:
                        if st.button("✅ 保存", key=f"save_{process_key}", type="primary"):
                            # 构建更新数据：勾选清空 → actual_end_date 写 None；否则用日期选择值
                            effective_end = None if clear_end else new_end
                            update_data = {
                                "actual_end_date": (
                                    effective_end.strftime('%Y-%m-%d') if effective_end else None
                                ),
                                "updated_by": st.session_state.get("user", "system"),
                            }

                            # === 核心：保存前内联计算状态（一次写入） ===
                            temp_proc = {
                                **proc,
                                "actual_end_date": update_data["actual_end_date"],
                            }
                            recalced = refresh_processes_from_db([temp_proc])
                            update_data["status"] = recalced[0]["status"]
                            update_data["lag_days"] = recalced[0]["lag_days"]
                            # 同步 completion_pct（已完成=100，其余按计算）
                            if update_data["status"] == "completed":
                                update_data["completion_pct"] = 100.0

                            # === 最高优先级规则：填了完成时间 → 状态强制 completed ===
                            if update_data.get("actual_end_date"):
                                update_data["status"] = "completed"
                                update_data["completion_pct"] = 100.0
                                # lag_days 同步按 完成时间 vs 计划结束 计算
                                pe = parse_date(proc.get("plan_end_date"))
                                ae = parse_date(update_data["actual_end_date"])
                                if pe and ae:
                                    update_data["lag_days"] = (ae - pe).days
                            else:
                                # 清空完成时间 → 按计划周期自动判定（refresh 已算好）
                                update_data["completion_pct"] = 0.0

                            # 一次写入：日期 + 状态 + 滞后天数
                            update_process(proc["id"], update_data)

                            # 刷新其他工序（状态联动）
                            all_procs = get_project_processes(project_id)
                            updated_all = refresh_processes_from_db(all_procs)
                            for up in updated_all:
                                if up["id"] != proc["id"]:
                                    update_process(up["id"], {
                                        "status": up["status"],
                                        "lag_days": up["lag_days"],
                                    })

                            # 先清缓存，确保 update_project_risk_level 读到最新工序状态
                            st.cache_data.clear()
                            update_project_risk_level(project_id)
                            st.cache_data.clear()  # 再清一次，确保后续查询读到新风险等级
                            del st.session_state[f"show_update_{process_key}"]
                            st.success(f"进度已更新 → {recalced[0]['status']}")
                            st.rerun()
                    with c2:
                        if st.button("❌ 取消", key=f"cancel_{process_key}"):
                            del st.session_state[f"show_update_{process_key}"]
                            st.rerun()

            # 异常提报弹窗
            if st.session_state.get(f"show_anomaly_{process_key}"):
                with st.container():
                    st.markdown("---")
                    st.subheader(f"异常提报：{name}")
                    reason = st.text_area("异常原因 *", key=f"anom_reason_{process_key}",
                                          placeholder="描述导致工序滞后的具体原因...")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        resp = st.selectbox("责任分类 *", RESPONSIBILITY_OPTIONS, key=f"anom_resp_{process_key}")
                    with col_b:
                        est_date = st.date_input("预计解决时间", key=f"anom_est_{process_key}",
                                                value=date.today() + timedelta(days=3))
                    measures = st.text_area("处理措施", key=f"anom_measures_{process_key}",
                                           placeholder="计划采取的处理措施...")
                    handler = st.text_input("处理人", key=f"anom_handler_{process_key}",
                                           value=project.get("delivery_person", ""))

                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ 提交异常", key=f"submit_anom_{process_key}", type="primary"):
                            if not reason or not resp:
                                st.error("异常原因和责任分类为必填项")
                            else:
                                insert_anomaly({
                                    "project_id": project_id,
                                    "process_id": proc["id"],
                                    "process_name": name,
                                    "anomaly_reason": reason,
                                    "responsibility": resp,
                                    "estimated_resolve_date": est_date.strftime('%Y-%m-%d'),
                                    "measures": measures,
                                    "handler": handler,
                                })
                                st.cache_data.clear()  # 异常写入后清除只读查询缓存
                                del st.session_state[f"show_anomaly_{process_key}"]
                                st.success("异常已提交")
                                st.rerun()
                    with c2:
                        if st.button("❌ 取消", key=f"cancel_anom_{process_key}"):
                            del st.session_state[f"show_anomaly_{process_key}"]
                            st.rerun()


    # ============================================================
    # 风险与异常管理
    # ============================================================

def _render_risk_anomaly(project_id: int, project: dict, processes: list[dict]):
    """渲染风险清单与异常管理"""
    # 风险清单
    with st.container(border=True):
        st.subheader("🔍 当前风险清单")

        alert_procs = [p for p in processes if p.get("lag_days", 0) > 0]
        if alert_procs:
            for p in alert_procs:
                lag = p.get("lag_days", 0)
                level = "🔴 延期" if lag >= 2 else "🟡 预警"
                st.markdown(
                    f"- {level} **{p.get('process_name')}**：滞后 **{lag}** 天 "
                    f"（计划结束：{p.get('plan_end_date', '-')}）"
                )
        else:
            st.success("✅ 当前无预警/延期工序")

        st.divider()

        # 异常提报入口
        with st.expander("📝 新增异常提报（不限于特定工序）"):
            col1, col2 = st.columns(2)
            with col1:
                proc_options = ["(不关联特定工序)"] + [p.get("process_name") for p in processes]
                sel_proc = st.selectbox("关联工序", proc_options, key="global_anom_proc")
            with col2:
                resp = st.selectbox("责任分类", RESPONSIBILITY_OPTIONS, key="global_anom_resp")

            reason = st.text_area("异常原因 *", key="global_anom_reason",
                                 placeholder="描述异常原因...")
            col_a, col_b = st.columns(2)
            with col_a:
                est_date = st.date_input("预计解决时间", key="global_anom_est",
                                        value=date.today() + timedelta(days=3))
            with col_b:
                handler = st.text_input("处理人", key="global_anom_handler",
                                       value=project.get("delivery_person", ""))
            measures = st.text_area("处理措施", key="global_anom_measures")

            if st.button("✅ 提交异常", key="global_anom_submit", type="primary"):
                if not reason:
                    st.error("异常原因为必填项")
                else:
                    proc_id = None
                    proc_name = sel_proc
                    if sel_proc != "(不关联特定工序)":
                        for p in processes:
                            if p.get("process_name") == sel_proc:
                                proc_id = p.get("id")
                                break

                    insert_anomaly({
                        "project_id": project_id,
                        "process_id": proc_id or processes[0]["id"] if processes else 0,
                        "process_name": proc_name,
                        "anomaly_reason": reason,
                        "responsibility": resp,
                        "estimated_resolve_date": est_date.strftime('%Y-%m-%d'),
                        "measures": measures,
                        "handler": handler,
                    })
                    st.cache_data.clear()  # 异常写入后清除只读查询缓存
                    st.success("异常已提交！")
                    st.rerun()

        st.divider()

        # 历史异常记录
        st.subheader("📋 历史异常记录")

        anomalies = _dbg("风险异常-历史异常", project_id, get_project_anomalies(project_id))
        if not anomalies:
            st.info("暂无异常记录")
            return

        for anom in anomalies:
            status_icon = {"open": "🔴 待处理", "in_progress": "🟡 处理中", "closed": "🟢 已闭环"}
            icon = status_icon.get(anom.get("status", "open"), "❓")
            with st.expander(f"{icon} | {anom.get('process_name')} | {anom.get('responsibility')} | "
                            f"{anom.get('created_at', '')[:10]}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**工序**: {anom.get('process_name')}")
                    st.write(f"**责任分类**: {anom.get('responsibility')}")
                    st.write(f"**异常原因**: {anom.get('anomaly_reason')}")
                    st.write(f"**处理措施**: {anom.get('measures', '暂无')}")
                with col2:
                    st.write(f"**提报时间**: {anom.get('created_at', '-')}")
                    st.write(f"**预计解决**: {anom.get('estimated_resolve_date', '-')}")
                    st.write(f"**实际解决**: {anom.get('actual_resolve_date', '-')}")
                    st.write(f"**处理人**: {anom.get('handler', '-')}")

                # 闭环操作
                if anom.get("status") != "closed":
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ 标记闭环", key=f"close_anom_{anom['id']}"):
                            update_anomaly_status(
                                anom["id"], "closed",
                                actual_resolve_date=date.today().strftime('%Y-%m-%d'),
                            )
                            st.cache_data.clear()  # 闭环后清除只读查询缓存
                            st.success("异常已闭环")
                            st.rerun()
                    with c2:
                        if st.button("🔄 标记处理中", key=f"progress_anom_{anom['id']}"):
                            update_anomaly_status(anom["id"], "in_progress")
                            st.cache_data.clear()  # 状态更新后清除只读查询缓存
                            st.success("状态已更新")
                            st.rerun()


    # ============================================================
    # 里程碑倒排
    # ============================================================

def _render_milestone_planning(project: dict, processes: list[dict]):
    """渲染里程碑倒排工具"""
    _dbg("里程碑倒排-工序", project.get("id"), processes)
    with st.container(border=True):
        st.subheader("📅 里程碑倒排计划")
        st.caption("输入项目最终交付截止日期，系统自动倒排计算每道工序的最晚开始/完成时间。")

        # 交付截止日期输入框 + 生成倒排计划按钮：同一水平线横向对齐（col3 为弹性空列，间距均匀）
        col1, col2, col3 = st.columns([2, 1.2, 3], vertical_alignment="center")
        with col1:
            plan_end_date = project.get("plan_end_date")
            default_deadline = parse_date(plan_end_date) if plan_end_date else date.today() + timedelta(days=30)
            deadline = st.date_input("交付截止日期", value=default_deadline, key="milestone_deadline")
        with col2:
            generate_btn = st.button("🔄 生成倒排计划", type="primary", width="stretch")
        with col3:
            pass  # 弹性空列，保持控件间距均匀

        if generate_btn and deadline:
            backward_plan = _dbg("里程碑倒排-倒排计划", project.get("id"),
                                 generate_backward_plan(deadline),
                                 f"deadline={deadline}")
            today = date.today()

            # 表头
            cols = st.columns([2, 2, 2, 2, 2])
            for col, header in zip(cols, ["工序", "最晚开始", "最晚完成", "当前状态", "偏差分析"]):
                col.markdown(f"**{header}**")
            st.divider()

            for bp, proc in zip(backward_plan, processes if processes else [{}]*12):
                status = proc.get("status", "not_started")
                deviation = "✅ 正常"

                if status == "not_started" and today > bp["backward_start"]:
                    deviation = f"⚠️ 已晚于倒排开始日 ({bp['backward_start']})"
                elif status in ("in_progress", "delayed") and today > bp["backward_end"]:
                    deviation = f"🔴 已超过倒排完成日 ({bp['backward_end']})"

                cols = st.columns([2, 2, 2, 2, 2])
                with cols[0]:
                    st.write(bp["process_name"])
                with cols[1]:
                    st.write(bp["backward_start"].strftime('%m/%d'))
                with cols[2]:
                    st.write(bp["backward_end"].strftime('%m/%d'))
                with cols[3]:
                    status_label = {
                        "not_started": "⬜ 未开始", "in_progress": "🟦 进行中",
                        "completed": "🟩 已完成", "delayed": "🟥 延期"
                    }.get(status, "⬜ 未开始")
                    st.write(status_label)
                with cols[4]:
                    color = "#38a169" if "正常" in deviation else "#e53e3e"
                    st.markdown(f"<span style='color:{color};font-size:13px;'>{deviation}</span>",
                               unsafe_allow_html=True)

            # 预计交付日期推算
            if processes:
                estimated = estimate_delivery_date(
                    refresh_processes_from_db(get_project_processes(project["id"]))
                )
                lag_days = count_workdays_between(deadline, estimated) if estimated > deadline else 0
                st.divider()
                if lag_days > 0:
                    st.warning(f"⚠️ 按当前进度推算，预计交付日期为 **{estimated}**，"
                              f"可能比计划截止日 **{deadline}** 延迟约 **{lag_days}** 个工作日")
                else:
                    st.success(f"✅ 按当前进度推算，预计交付日期为 **{estimated}**，"
                              f"可在计划截止日 **{deadline}** 前完成")


    # ============================================================
    # v4.0: 工序节点计划管控 + 预警（排产矩阵，独立于 processes 12 道工序）
    # ============================================================

def _render_node_schedule_import(project_id: int, project: dict):
    """导入排产计划 Excel（矩阵：多套塔筒 × 9 道排产工序 × 计划完成日期）。"""
    has_plans = bool(get_node_plans(project_id))
    with st.expander("📥 导入排产计划", expanded=not has_plans):
        st.caption(
            "Excel 格式：首列为套序号（如「第1套」），后续 9 列按顺序为："
            "钢板到货 / 法兰到货 / 下料 / 卷制 / 组对 / 黑塔 / 防腐 / 附件安装 / 具备验收。"
            "导入将覆盖该项目的旧节点计划。"
        )
        try:
            import pandas as pd
        except ImportError:
            st.warning("请安装 pandas/openpyxl: pip install pandas openpyxl")
            return

        uploaded = st.file_uploader(
            "上传排产 Excel（.xlsx / .xls）",
            type=["xlsx", "xls"],
            key=f"node_schedule_upload_{project_id}",
        )
        if uploaded is not None:
            import tempfile

            suffix = os.path.splitext(uploaded.name)[1] or ".xlsx"
            tmp_path = ""
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.getbuffer())
                    tmp_path = tmp.name
                plans, errors = parse_node_schedule_excel(tmp_path)
            except Exception as e:
                st.error(f"❌ 解析失败: {e}")
                return
            finally:
                if tmp_path:
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass

            if errors:
                st.warning("解析提示：")
                for e in errors[:20]:
                    st.caption(f"- {e}")
                if len(errors) > 20:
                    st.caption(f"... 共 {len(errors)} 条")

            if not plans:
                st.info("未解析到有效节点计划，请检查 Excel 格式后重试。")
                return

            preview = pd.DataFrame([{
                "工序": p["process_name"],
                "计划日期": p["plan_date"],
                "应完成(套)": p["plan_qty"],
            } for p in plans])
            st.dataframe(preview, use_container_width=True)

            if st.button("✅ 确认导入", type="primary",
                         key=f"confirm_node_schedule_{project_id}"):
                try:
                    n = insert_node_plans(project_id, plans)
                    st.cache_data.clear()
                    st.success(f"✅ 已导入 {n} 个节点计划（覆盖该项目的旧节点计划）")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ 导入失败: {e}")
                    import traceback
                    st.code(traceback.format_exc()[-400:])


def _render_node_timeline(rows: list[dict]):
    """渲染节点计划时间轴：每工序一条线、节点为散点、颜色按状态。"""
    try:
        import plotly.graph_objects as go
        import pandas as pd
    except ImportError:
        st.warning("请安装 plotly: pip install plotly")
        return

    if not rows:
        return

    color_map = {
        "pending": "#cbd5e0",    # ⚪ 未开始 灰
        "done": "#38a169",       # 🟢 已完成 绿
        "in_progress": "#3182ce",  # 🔵 进行中 蓝
        "warning": "#d69e2e",    # 🟡 部分完成 黄
        "overdue": "#e53e3e",    # 🔴 逾期未完成 红
    }
    label_map = {
        "pending": "⚪ 未开始", "done": "🟢 已完成", "in_progress": "🔵 进行中",
        "warning": "🟡 部分完成", "overdue": "🔴 逾期未完成",
    }

    # 按工序分组（保持排产顺序）
    proc_groups = {}
    for r in rows:
        proc_groups.setdefault(r["process_name"], []).append(r)

    fig = go.Figure()
    for pn in SCHEDULE_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = sorted(proc_groups[pn], key=lambda r: str(r["plan_date"]))
        x = [pd.Timestamp(r["plan_date"]) for r in grp]
        marker_colors = [color_map.get(r["status"], "#cbd5e0") for r in grp]
        hover_text = [
            f"{pn}<br>计划 {r['plan_date']}<br>"
            f"应完成 {r['plan_qty']} 套 | 实际 {r['actual_qty']} 套<br>"
            f"{label_map.get(r['status'], r['label'])}"
            + (f" | 滞后 {r['lag_qty']} 套" if r["lag_qty"] > 0 else "")
            for r in grp
        ]
        fig.add_trace(go.Scatter(
            x=x,
            y=[pn] * len(grp),
            mode="markers+lines",
            name=pn,
            text=hover_text,
            hoverinfo="text",
            marker=dict(size=12, color=marker_colors, line=dict(width=1, color="#2d3748")),
            line=dict(color="rgba(148,163,184,0.45)", width=1),
        ))

    fig.add_vline(
        x=pd.Timestamp(date.today()),
        line_dash="dash",
        line_color="#e53e3e",
        annotation_text="今天",
        annotation_position="top",
    )

    visible_proc_count = len([pn for pn in SCHEDULE_PROCESS_NAMES if pn in proc_groups])
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        title=dict(
            text="工序节点计划时间轴",
            font=dict(size=18, color="#222222",
                      family="-apple-system, 'Microsoft YaHei', sans-serif"),
            x=0.01, xanchor="left",
        ),
        # 全局字体：深黑 #222222、加大字号、medium 字重
        font=dict(
            family="-apple-system, 'Microsoft YaHei', sans-serif",
            size=15,
            color="#222222",
        ),
        height=max(480, 85 * max(visible_proc_count, 1)),  # 每工序 85px，保证行间距宽松
        # 左侧给 Y 轴工序名，右侧给垂直图例，上下留白防挤压
        margin=dict(l=160, r=160, t=70, b=60),
        # 图例：右侧垂直排列，自动错开、不重叠
        legend=dict(
            orientation="v",
            yanchor="top", y=1, xanchor="left", x=1.02,
            font=dict(size=14, color="#222222"),
            bgcolor="rgba(255,255,255,0.95)",
            bordercolor="#e2e8f0", borderwidth=1,
        ),
        xaxis=dict(
            tickformat="%m/%d",
            tickfont=dict(size=14, color="#222222"),
            automargin=True,
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(size=15, color="#222222",
                          family="-apple-system, 'Microsoft YaHei', sans-serif"),
            automargin=True,
        ),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(font_size=14, font_color="#222222"),
    )

    st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})


def _render_node_schedule(project_id: int, project: dict):
    """节点计划总览：导入入口 + 顶部指标 + 按工序分组节点列表 + Plotly 时间轴 + 实际填报。"""
    # ---- 填报弹窗保存成功的页面级提示（flash，显示后即清除）----
    flash_key = f"dlg_flash_{project_id}"
    if flash_key in st.session_state:
        st.success(st.session_state.pop(flash_key))

    plans = _dbg("节点计划-计划", project_id, get_node_plans(project_id))
    actuals = get_node_actuals(project_id)

    # ---- 导入排产计划入口 ----
    _render_node_schedule_import(project_id, project)

    if not plans:
        st.info("暂无工序节点计划，请先在上方导入排产 Excel。")
        return

    today = date.today()

    # 富化节点行：计划信息 + 实际完成 + 五态判定（含完成日期与偏差）
    rows = []
    for p in plans:
        node_id = p.get("id")
        act_info = actuals.get(node_id, {})
        actual_qty = act_info.get("actual_qty", 0)
        completion_date = (
            act_info.get("report_date")
            if actual_qty >= p.get("plan_qty", 1) else None
        )
        st_row = judge_node_status(
            p.get("plan_date"), p.get("plan_qty", 1),
            actual_qty, today, completion_date,
        )
        rows.append({
            **p,
            "actual_qty": actual_qty,
            **st_row,
        })

    # 按工序分组（保持 SCHEDULE_PROCESS_NAMES 展示顺序）
    proc_groups = {}
    for r in rows:
        proc_groups.setdefault(r["process_name"], []).append(r)

    # ---- 顶部指标计算（供下方卡片容器使用）----
    per_proc_sets = {pn: sum(r["plan_qty"] for r in grp) for pn, grp in proc_groups.items()}
    total_sets = max(per_proc_sets.values()) if per_proc_sets else 0
    done_count = sum(1 for r in rows if r["status"] == "done")
    overdue_count = sum(1 for r in rows if r["status"] == "overdue")

    # ============================================================
    # 区块 1：顶部指标卡（浅色卡片容器）
    # ============================================================
    with st.container(border=True):
        st.markdown("<div class='node-section-box'>", unsafe_allow_html=True)
        st.subheader("📌 项目节点概览")

        c1, c2, c3, c4, c5 = st.columns(5)  # 在容器内定义 columns，仅渲染一次
        c1.metric("总套数", f"{total_sets} 套")
        c2.metric("工序数", f"{len(proc_groups)} 道")
        c3.metric("节点总数", f"{len(rows)} 个")
        c4.metric("达标节点", f"{done_count} 个")
        c5.metric("🔴 逾期节点", f"{overdue_count} 个")

        st.markdown("</div>", unsafe_allow_html=True)

    # ============================================================
    # 区块 2：工序节点计划时间轴
    # ============================================================
    with st.container(border=True):
        st.markdown("<div class='node-section-box'>", unsafe_allow_html=True)
        st.subheader("📊 工序节点计划时间轴")
        _render_node_timeline(rows)
        st.markdown("</div>", unsafe_allow_html=True)

    # ============================================================
    # 区块 3：工序卡片网格（整片可点击打开详情弹窗）
    # ============================================================
    with st.container(border=True):
        st.markdown("<div class='node-section-box process-card-grid'>", unsafe_allow_html=True)

        # 标题行：左侧图标+标题 / 右侧辅助文字（紧凑，紧贴模块顶部）
        hc1, hc2 = st.columns([2, 1])
        with hc1:
            st.markdown("#### 🏭 工序节点明细")
        with hc2:
            st.markdown(
                "<p style='text-align:right;color:#3182ce;font-size:13px;margin:0;'>"
                "点击工序查看详情</p>",
                unsafe_allow_html=True,
            )

        STATUS_EMOJI = {
            "done": "🟢", "pending": "⚪", "in_progress": "🔵",
            "warning": "🟡", "overdue": "🔴",
        }
        proc_cards = [pn for pn in SCHEDULE_PROCESS_NAMES if pn in proc_groups]
        cols_per_row = 3
        for i in range(0, len(proc_cards), cols_per_row):
            row_cards = proc_cards[i:i + cols_per_row]
            cols = st.columns(len(row_cards))
            for col, pn in zip(cols, row_cards):
                grp = sorted(proc_groups[pn], key=lambda r: str(r["plan_date"]))
                proc_status = judge_process_node_status(grp)
                total_plan = sum(r["plan_qty"] for r in grp)
                total_actual = sum(r["actual_qty"] for r in grp)
                progress = total_actual / total_plan if total_plan else 0
                progress_pct = f"{progress * 100:.1f}%"
                # 填充宽度上限 100%（min(percent, 100)）
                bar_width = min(progress * 100, 100)

                emoji = STATUS_EMOJI.get(proc_status["status"], "⚪")
                # 进度条/边框颜色按状态动态（完成绿/进行中蓝/部分完成蓝/逾期红/未开始灰）
                bar_color = {
                    "done": "#38a169",
                    "pending": "#cbd5e0",
                    "in_progress": "#3182ce",
                    "warning": "#3182ce",
                    "overdue": "#e53e3e",
                }.get(proc_status["status"], "#cbd5e0")
                # 状态胶囊底+文字（用户指定四色：完成绿/部分完成与进行中蓝/逾期红/未开始灰）
                status_bg = {
                    "done": "#f0fff4",
                    "pending": "#f7fafc",
                    "in_progress": "#ebf8ff",
                    "warning": "#ebf8ff",
                    "overdue": "#fff5f5",
                }.get(proc_status["status"], "#f7fafc")

                with col:
                    # 卡片主体 HTML：圆点+工序名+状态胶囊 / 完成数 / 进度条+百分比（真实可视化）
                    st.markdown(
                        f"<div class='process-card-box'>"
                        f"<div class='pc-header'>"
                        f"<span class='pc-dot' style='color:{bar_color};'>{emoji}</span>"
                        f"<span class='pc-title'>{pn}</span>"
                        f"<span class='pc-pill' style='background:{status_bg};color:{bar_color};'>{proc_status['label']}</span>"
                        f"</div>"
                        f"<div class='pc-count'>{total_actual}/{total_plan} 套</div>"
                        f"<div class='pc-progress'>"
                        f"<div class='pc-progress-track'>"
                        f"<div class='pc-progress-bar' style='width:{bar_width:.1f}%;background:{bar_color};'></div>"
                        f"</div>"
                        f"<span class='pc-percent'>{progress_pct}</span>"
                        f"</div>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )

                    # 独立「查看详情」按钮：右下角紧凑样式（CSS .process-card-grid .stButton 控制）
                    if st.button(
                        "查看详情",
                        key=f"open_detail_{project_id}_{pn}",
                        type="secondary",
                        use_container_width=False,
                        help="点击查看工序详情",
                    ):
                        # 记录待打开弹窗与模式，统一由主流程自动打开
                        # （dialog 内 rerun 不保活，模式切换必须经主流程重新调用 dialog）
                        st.session_state[f"dialog_mode_{project_id}_{pn}"] = "detail"
                        st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)

    # ============================================================
    # 弹窗自动打开：根据 dialog_mode_* 标记打开 详情/填报 弹窗
    # （由主流程调用；dialog 内按钮只改标记 + rerun，本段负责重新打开）
    # ============================================================
    for pn in [p2 for p2 in SCHEDULE_PROCESS_NAMES if p2 in proc_groups]:
        m = st.session_state.get(f"dialog_mode_{project_id}_{pn}")
        if m in ("detail", "input"):
            grp = sorted(proc_groups[pn], key=lambda r: str(r["plan_date"]))
            if m == "input":
                _show_process_input_dialog(project_id, grp)
            else:
                _show_process_detail_dialog(project_id, grp)
            break


@st.dialog("工序节点详情", width="large")
def _show_process_detail_dialog(project_id: int, grp: list):
    """工序节点弹窗入口：详情模式 / 填报模式 切换。"""
    if not grp:
        st.info("该工序暂无节点。")
        return
    pn = grp[0]["process_name"]
    mode_key = f"dialog_mode_{project_id}_{pn}"
    mode = st.session_state.get(mode_key, "detail")

    if mode == "input":
        _render_dialog_input_mode(project_id, pn, grp)
    else:
        _render_dialog_detail_mode(project_id, pn, grp)


def _render_dialog_detail_mode(project_id: int, pn: str, grp: list):
    """弹窗详情模式：节点明细表格 + 「📝 填报进度」入口按钮。"""
    proc_status = judge_process_node_status(grp)
    st.markdown(f"### {pn}  {proc_status['label']}")

    # 表头
    header_cols = st.columns([1.2, 1, 1, 1.2, 1, 1.2])
    headers = ["计划日期", "应完成(套)", "实际完成(套)", "完成日期", "偏差", "状态"]
    for col, h in zip(header_cols, headers):
        col.markdown(f"<div class='node-table-header'>{h}</div>", unsafe_allow_html=True)

    # 数据行（斑马纹 + 偏差着色 + 状态徽标）
    for r in grp:
        cd = r.get("completion_date")
        cd_text = str(cd) if cd else "-"
        cols = st.columns([1.2, 1, 1, 1.2, 1, 1.2])
        with cols[0]:
            st.markdown(f"<div class='node-table-row'>{r['plan_date']}</div>", unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f"<div class='node-table-row'>{r['plan_qty']} 套</div>", unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f"<div class='node-table-row'>{r['actual_qty']} 套</div>", unsafe_allow_html=True)
        with cols[3]:
            st.markdown(f"<div class='node-table-row'>{cd_text}</div>", unsafe_allow_html=True)
        with cols[4]:
            st.markdown(
                f"<div class='node-table-row' style='color:{r.get('deviation_color', '#718096')}'>"
                f"{r.get('deviation_label', '-')}</div>",
                unsafe_allow_html=True,
            )
        with cols[5]:
            color = STATUS_COLOR.get(r["status"], "#718096")
            st.markdown(
                f"<div class='node-table-row' style='color:{color};font-weight:600;'>"
                f"{r['label']}</div>",
                unsafe_allow_html=True,
            )

    # 底部操作按钮
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📝 填报进度", type="primary", use_container_width=True,
                     key=f"to_input_mode_{project_id}_{pn}"):
            st.session_state[f"dialog_mode_{project_id}_{pn}"] = "input"
            st.rerun()  # 主流程检测 input 标记后自动打开填报弹窗
    with c2:
        if st.button("关闭", use_container_width=True,
                     key=f"close_detail_{project_id}_{pn}"):
            st.session_state.pop(f"dialog_mode_{project_id}_{pn}", None)
            st.rerun()


def _render_dialog_input_mode(project_id: int, pn: str, grp: list):
    """弹窗内填报界面：今日/逾期/未来/已完成分组 + 保存 + 返回详情。"""
    # ---- 在函数最顶部、任何 number_input 实例化之前，应用待设置的批次值 ----
    # 避免 "cannot be modified after the widget is instantiated" 错误：
    # 批量设置必须发生在对应 number_input 渲染之前，故统一在此处消费 pending 列表。
    pending_key = f"dlg_pending_set_{project_id}_{pn}"
    if pending_key in st.session_state:
        for nid, qty in st.session_state.pop(pending_key):
            st.session_state[f"node_actual_dlg_{project_id}_{nid}"] = qty

    st.markdown(f"### 📝 填报进度：{pn}")
    plans_all = get_node_plans(project_id)   # 用于前序工序联动校验
    actuals = get_node_actuals(project_id)
    today = date.today()

    proc_nodes = sorted(grp, key=lambda r: str(r["plan_date"]))
    a = lambda nid: actuals.get(nid, {}).get("actual_qty", 0)

    # 严格互斥分组
    today_nodes, overdue_nodes, future_nodes, done_nodes = [], [], [], []
    for p in proc_nodes:
        act = a(p["id"])
        if act >= p["plan_qty"]:
            done_nodes.append(p)
        elif p["plan_date"] == today:
            today_nodes.append(p)
        elif p["plan_date"] < today:
            overdue_nodes.append(p)
        else:
            future_nodes.append(p)

    # ---- 互斥手风琴：单选分组，选中即展开该组、其他分组隐藏 ----
    active_key = f"dlg_active_group_{project_id}_{pn}"
    group_labels = {
        "today": "🔵 今日待填报",
        "overdue": "🔴 逾期未完成",
        "future": "⚪ 未来计划",
        "done": "🟢 已完成",
    }
    if hasattr(st, "segmented_control"):
        active_group = st.segmented_control(
            "选择分组",
            options=["today", "overdue", "future", "done"],
            format_func=lambda x: group_labels.get(x, x),
            key=active_key,
            default="today",
            label_visibility="collapsed",
        )
    else:
        active_group = st.radio(
            "选择分组",
            options=["today", "overdue", "future", "done"],
            format_func=lambda x: group_labels.get(x, x),
            key=active_key,
            horizontal=True,
            label_visibility="collapsed",
        )
    if not active_group:
        active_group = "today"

    # 今日待填报
    if active_group == "today":
        with st.expander("🔵 今日待填报", expanded=True):
            st.markdown("<div class='grp-today'>", unsafe_allow_html=True)
            if st.button("⚡ 一键全部按计划完成", key=f"dlg_quick_today_{project_id}_{pn}"):
                # 写入 pending 列表，交由函数顶部统一应用（此时 number_input 尚未实例化）
                pending = [(p["id"], p["plan_qty"]) for p in today_nodes]
                st.session_state[f"dlg_pending_set_{project_id}_{pn}"] = pending
                st.rerun()
            for p in today_nodes:
                _render_dialog_input_row(project_id, p, proc_nodes, plans_all, actuals,
                                         today, "today")
            if not today_nodes:
                st.caption("今日无待填报节点")
            st.markdown("</div>", unsafe_allow_html=True)

    # 逾期未完成（行内复选 + 批量按钮置底）
    if active_group == "overdue":
        with st.expander("🔴 逾期未完成", expanded=True):
            st.markdown("<div class='grp-overdue'>", unsafe_allow_html=True)
            for p in overdue_nodes:
                _render_dialog_input_row(project_id, p, proc_nodes, plans_all, actuals,
                                         today, "overdue", selectable=True)
            if overdue_nodes:
                if st.button("📦 批量按计划完成所选", key=f"dlg_batch_done_{project_id}_{pn}"):
                    checked = [
                        p["id"] for p in overdue_nodes
                        if st.session_state.get(f"dlg_batch_chk_{project_id}_{p['id']}", False)
                    ]
                    # 写入 pending 列表（含各自的计划数量），交由函数顶部统一应用
                    pending = [
                        (nid, next((x["plan_qty"] for x in overdue_nodes if x["id"] == nid), 0))
                        for nid in checked
                    ]
                    st.session_state[f"dlg_pending_set_{project_id}_{pn}"] = pending
                    st.rerun()
            else:
                st.caption("无逾期节点")
            st.markdown("</div>", unsafe_allow_html=True)

    # 未来计划
    if active_group == "future":
        with st.expander("⚪ 未来计划", expanded=True):
            st.markdown("<div class='grp-future'>", unsafe_allow_html=True)
            for p in future_nodes:
                _render_dialog_input_row(project_id, p, proc_nodes, plans_all, actuals,
                                         today, "future")
            if not future_nodes:
                st.caption("无未来计划节点")
            st.markdown("</div>", unsafe_allow_html=True)

    # 已完成
    if active_group == "done":
        with st.expander("🟢 已完成", expanded=True):
            st.markdown("<div class='grp-done'>", unsafe_allow_html=True)
            for p in done_nodes:
                _render_dialog_input_row(project_id, p, proc_nodes, plans_all, actuals,
                                         today, "done")
            if not done_nodes:
                st.caption("暂无已完成节点")
            st.markdown("</div>", unsafe_allow_html=True)

    # 保存 + 返回 + 关闭
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("💾 保存节点进度", type="primary", use_container_width=True,
                     key=f"dlg_save_{project_id}_{pn}"):
            # ---- 只保存当前激活分组的节点（避免覆盖未渲染分组的 0 值）----
            group_map = {
                "today": today_nodes,
                "overdue": overdue_nodes,
                "future": future_nodes,
                "done": done_nodes,
            }
            nodes_to_save = group_map.get(active_group, [])
            group_label = {
                "today": "今日待填报",
                "overdue": "逾期未完成",
                "future": "未来计划",
                "done": "已完成",
            }.get(active_group, active_group)

            if not nodes_to_save:
                st.warning(f"当前分组「{group_label}」没有可保存的节点。")
            else:
                # 前序工序数量联动校验（仅今日待填报节点受限制；逾期/未来/已完成自由填报）
                proc_idx = SCHEDULE_PROCESS_NAMES.index(pn) if pn in SCHEDULE_PROCESS_NAMES else -1
                prev_total = None
                if proc_idx > 0:
                    prev_procs = set(SCHEDULE_PROCESS_NAMES[:proc_idx])
                    prev_total = sum(a(p["id"]) for p in plans_all if p["process_name"] in prev_procs)
                today_node_ids = {p["id"] for p in today_nodes}
                today_total = sum(
                    int(st.session_state.get(f"node_actual_dlg_{project_id}_{p['id']}", 0) or 0)
                    for p in nodes_to_save if p["id"] in today_node_ids
                )
                if prev_total is not None and today_total > prev_total:
                    # 校验失败：保留弹窗（用户可修改后重试），不使用 st.stop()（避免中断 dialog 执行流）
                    st.error(
                        f"❌ 保存失败：{pn} 今日待填报累计 {today_total} 套不能超过前序工序 {prev_total} 套。"
                    )
                else:
                    try:
                        saved = 0
                        for p in nodes_to_save:
                            qty = int(
                                st.session_state.get(f"node_actual_dlg_{project_id}_{p['id']}", 0) or 0
                            )
                            upsert_node_actual(project_id, p["id"], p["process_name"], qty,
                                               today.strftime('%Y-%m-%d'))
                            saved += 1
                        st.cache_data.clear()
                        # 成功：清除弹窗标记（主流程 rerun 后不再重开）→ 弹窗关闭
                        st.session_state.pop(f"dialog_mode_{project_id}_{pn}", None)
                        # 成功提示转页面级 flash（弹窗关闭后仍可见，含分组名）
                        st.session_state[f"dlg_flash_{project_id}"] = (
                            f"✅ 已保存 {saved} 个节点进度（工序：{pn}，{group_label}）"
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ 保存失败: {e}")

    with c2:
        if st.button("← 返回详情", use_container_width=True,
                     key=f"back_to_detail_{project_id}_{pn}"):
            st.session_state[f"dialog_mode_{project_id}_{pn}"] = "detail"
            st.rerun()
    with c3:
        if st.button("关闭", use_container_width=True,
                     key=f"close_input_{project_id}_{pn}"):
            st.session_state.pop(f"dialog_mode_{project_id}_{pn}", None)
            st.rerun()


@st.dialog("填报节点进度", width="large")
def _show_process_input_dialog(project_id: int, grp: list):
    """填报节点进度弹窗（由主流程按 dialog_mode 标记调用）。"""
    if not grp:
        st.info("该工序暂无节点。")
        return
    pn = grp[0]["process_name"]
    _render_dialog_input_mode(project_id, pn, grp)


def _render_dialog_input_row(project_id, p, proc_nodes, plans_all, actuals, today,
                             row_cls, selectable=False):
    """弹窗内单行填报：行背景 + number_input（含前序联动额度）+ 状态胶囊（key 与页面隔离）。"""
    node_id = p["id"]
    saved_qty = actuals.get(node_id, {}).get("actual_qty", 0)
    completion_date = (
        actuals.get(node_id, {}).get("report_date")
        if saved_qty >= p["plan_qty"] else None
    )
    status = judge_node_status(
        p["plan_date"], p["plan_qty"], saved_qty, today, completion_date,
    )

    # 前序联动额度（仅今日待填报使用；逾期/未来自由填报、已完成只能减少）
    proc_idx = SCHEDULE_PROCESS_NAMES.index(p["process_name"]) if p["process_name"] in SCHEDULE_PROCESS_NAMES else -1
    prev_total = None
    if proc_idx > 0:
        prev_procs = set(SCHEDULE_PROCESS_NAMES[:proc_idx])
        prev_total = sum(
            actuals.get(pn["id"], {}).get("actual_qty", 0)
            for pn in plans_all if pn["process_name"] in prev_procs
        )

    # 根据分组决定可填报上限
    if row_cls == "done":
        # 已完成只能减少，不能增加（max = 当前实际完成数）
        max_value = int(saved_qty)
    elif row_cls in ("overdue", "future"):
        # 逾期未完成、未来计划自由填报，不受前序工序额度限制
        max_value = int(p["plan_qty"])
    else:
        # 今日待填报保持前序工序数量联动限制
        others_total = sum(
            int(st.session_state.get(f"node_actual_dlg_{project_id}_{q['id']}",
                                     actuals.get(q["id"], {}).get("actual_qty", 0)) or 0)
            for q in proc_nodes if q["id"] != node_id
        )
        if prev_total is not None:
            max_value = min(int(p["plan_qty"]), max(0, prev_total - others_total))
        else:
            max_value = int(p["plan_qty"])  # 第一道工序不限制

    if selectable:
        cols = st.columns([0.5, 1.2, 1, 1.2, 1.2])
    else:
        cols = st.columns([1.2, 1, 1.2, 1.2])

    with cols[0]:
        if selectable:
            st.checkbox("选择", key=f"dlg_batch_chk_{project_id}_{node_id}",
                        label_visibility="collapsed")
        else:
            st.markdown(f"<div class='cell-{row_cls}'>{p['plan_date']}</div>",
                        unsafe_allow_html=True)

    date_col = 1 if selectable else 0
    qty_col = 2 if selectable else 1
    input_col = 3 if selectable else 2
    status_col = 4 if selectable else 3

    with cols[date_col]:
        if selectable:
            st.markdown(f"<div class='cell-{row_cls}'>{p['plan_date']}</div>",
                        unsafe_allow_html=True)
    with cols[qty_col]:
        st.markdown(f"<div class='cell-{row_cls}'>{p['plan_qty']} 套</div>",
                    unsafe_allow_html=True)
    with cols[input_col]:
        # 已完成节点显示当前保存值（便于知道减多少）；其他节点防旧值超上限
        display_value = int(saved_qty) if row_cls == "done" else min(int(saved_qty), max_value)
        st.number_input(
            "实际完成套数", min_value=0, max_value=max_value, step=1,
            value=display_value,
            key=f"node_actual_dlg_{project_id}_{node_id}",
            label_visibility="collapsed",
        )
    with cols[status_col]:
        color = STATUS_COLOR.get(status["status"], "#718096")
        st.markdown(
            f"<span class='status-pill' style='background:{color}1a;color:{color};'>"
            f"{status['label']}</span>",
            unsafe_allow_html=True,
        )


# 节点状态颜色映射（供抽屉行/分组/卡片共用）
STATUS_COLOR = {
    "done": "#38a169", "pending": "#718096", "in_progress": "#3182ce",
    "warning": "#d69e2e", "overdue": "#e53e3e",
}



def _render_node_warning(project_id: int, project: dict):
    """节点预警汇总：五态统计 + 重点列出 🔴 逾期 / 🟡 部分完成 / 🔵 进行中 节点。"""
    plans = _dbg("节点预警-计划", project_id, get_node_plans(project_id))
    actuals = get_node_actuals(project_id)

    if not plans:
        st.info("暂无工序节点计划，请先在「节点计划」页导入排产 Excel。")
        return

    today = date.today()

    stats = {"done": 0, "warning": 0, "overdue": 0, "pending": 0, "in_progress": 0}
    alerts = []
    for p in plans:
        node_id = p["id"]
        act_info = actuals.get(node_id, {})
        actual_qty = act_info.get("actual_qty", 0)
        completion_date = (
            act_info.get("report_date")
            if actual_qty >= p["plan_qty"] else None
        )
        status = judge_node_status(
            p["plan_date"], p["plan_qty"], actual_qty, today, completion_date,
        )
        stats[status["status"]] += 1
        if status["status"] in ("warning", "overdue", "in_progress"):
            alerts.append({**p, "actual_qty": actual_qty, **status})

    # ---- 汇总统计 ----
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🟢 达标", stats["done"])
    c2.metric("🔵 进行中", stats["in_progress"])
    c3.metric("🟡 部分完成", stats["warning"])
    c4.metric("🔴 逾期未完成", stats["overdue"])
    c5.metric("⚪ 未开始", stats["pending"])

    st.divider()
    st.subheader("⚠️ 重点关注节点（部分完成 / 逾期未完成 / 进行中）")

    if not alerts:
        st.success("✅ 当前无预警/逾期节点")
        return

    alerts_sorted = sorted(alerts, key=lambda a: (-a["level"], str(a["plan_date"])))
    for a in alerts_sorted:
        msg = (
            f"**{a['process_name']}** | 计划 {a['plan_date']} | "
            f"应完成 {a['plan_qty']} 套 | 实际完成 {a['actual_qty']} 套 | "
            f"滞后 {a['lag_qty']} 套 | 偏差 {a.get('deviation_label', '-')}"
        )
        if a["status"] == "overdue":
            st.error(f"🔴 {msg}")
        elif a["status"] == "warning":
            st.warning(f"🟡 {msg}")
        else:
            st.info(f"🔵 {msg}")


if __name__ == "__main__":
    main()
