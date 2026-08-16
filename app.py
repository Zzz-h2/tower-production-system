"""
app.py — 塔筒生产进度管控系统 主入口

Streamlit 多页面应用入口。
支持页面路由：项目总览(主页) → 项目详情(子页)。

启动方式：
    streamlit run app.py

Author: Senior Developer
Date: 2026-08-03
"""

import streamlit as st
import sys
import os
from datetime import date

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import PAGE_CONFIG, CUSTOM_CSS
from database import init_database


def main():
    """主入口 — 初始化数据库并展示项目总览"""
    # 页面配置
    st.set_page_config(**PAGE_CONFIG)
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    # 初始化数据库
    if "db_initialized" not in st.session_state:
        try:
            init_database()
            st.session_state.db_initialized = True
        except Exception as e:
            st.error(f"数据库初始化失败: {e}")
            return

    # 页面标题
    col1, col2 = st.columns([3, 1])
    with col1:
        st.title("🏭 塔筒生产进度管控系统")
        st.caption("陆基风电塔筒制造工序追踪 · 风险预警 · 异常闭环管理")
    with col2:
        st.markdown("""
        <div style="text-align:right; padding-top:20px;">
            <span style="color:#718096; font-size:13px;">v1.0 | 工业制造版</span>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ============================================================
    # 数据概览区 — 4个指标卡片
    # ============================================================
    from database import get_dashboard_stats

    stats = get_dashboard_stats()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="在产项目总数",
            value=stats.get('total_projects', 0),
            delta=None,
        )
    with col2:
        st.metric(
            label="预警项目",
            value=stats.get('warning_count', 0),
            delta=None,
        )
    with col3:
        st.metric(
            label="延期项目",
            value=stats.get('delayed_count', 0),
            delta=None,
        )
    with col4:
        st.metric(
            label="本月计划出品总量",
            value=f"{stats.get('total_monthly_plan', 0)} 段",
            delta=None,
        )

    st.divider()

    # ============================================================
    # 导入调度令区域
    # ============================================================
    with st.expander("📁 导入月度调度令（Excel）", expanded=False):
        _render_import_section()

    st.divider()

    # ============================================================
    # 项目列表区
    # ============================================================
    _render_project_table()


def _render_import_section():
    """渲染 Excel 导入区域"""
    from utils.excel_parser import (
        read_excel_headers, auto_detect_mapping,
        parse_schedule_excel, REQUIRED_FIELDS
    )
    from database import upsert_project, init_project_processes, insert_import_log

    uploaded_file = st.file_uploader(
        "上传月度调度令 Excel 文件（.xlsx）",
        type=["xlsx"],
        help="支持标准月度调度令格式，导入后自动去重更新"
    )

    if uploaded_file:
        # 保存临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = tmp.name

        # 读取表头
        try:
            headers = read_excel_headers(tmp_path)
        except Exception as e:
            st.error(f"读取文件失败: {e}")
            try:
                os.unlink(tmp_path)
            except:
                pass
            return

        if not headers:
            st.error("未能识别到有效表头列，请确认 Excel 文件包含表头行（如'项目名称''钢塔厂家'等），且非空文件。")
            try:
                os.unlink(tmp_path)
            except:
                pass
            return

        # 自动检测列映射（隐藏列检测提示/字段匹配提示/映射配置界面，直接采用自动检测结果）
        auto_mapping = auto_detect_mapping(headers)
        final_mapping = dict(auto_mapping)  # {excel_col: sys_field}

        # 必填字段是否全部完成映射
        mapped_required = [f for f in REQUIRED_FIELDS if any(v == f for v in final_mapping.values())]
        all_required_mapped = len(mapped_required) >= len(REQUIRED_FIELDS)

        # 导入按钮（仅自动识别缺字段时提示，不渲染任何映射界面）
        import_disabled = not all_required_mapped
        if import_disabled:
            st.error("⚠️ 未能自动识别全部必填字段，无法导入。请确认 Excel 表头包含：项目名称、钢塔厂家、本月计划出品、交付负责人。")
        if st.button(
            "🚀 开始导入",
            type="primary",
            use_container_width=True,
            disabled=import_disabled,
        ):
            if len(final_mapping) < 4:
                st.error(f"请至少映射 {len(REQUIRED_FIELDS)} 个必填字段")
            else:
                # ===== 全链路异常捕获 =====
                import_ok = False
                try:
                    with st.spinner("正在解析并导入数据..."):
                        # 重新确保临时文件存在（Streamlit rerender 会重建）
                        if not os.path.exists(tmp_path):
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp2:
                                tmp2.write(uploaded_file.getvalue())
                                tmp_path = tmp2.name

                        data, errors = parse_schedule_excel(tmp_path, final_mapping)

                        if not data:
                            st.warning("⚠️ 未解析到有效数据行，请确认 Excel 格式。")
                            if errors:
                                for err in errors[:10]:
                                    st.caption(f"· {err}")
                        else:
                            success_count = 0
                            skip_count = 0

                            for item in data:
                                try:
                                    project_id, is_new = upsert_project(item)
                                    if is_new:
                                        # 新项目初始化工序
                                        try:
                                            start_date = item.get('plan_start_date') or date.today().strftime('%Y-%m-%d')
                                            init_project_processes(project_id, start_date)
                                            # 初始化后立即计算初始风险等级
                                            from database import update_project_risk_level
                                            update_project_risk_level(project_id)
                                        except Exception as e_proc:
                                            errors.append(
                                                f"「{item.get('project_name', 'N/A')}」项目导入成功，"
                                                f"但工序生成失败: {e_proc}"
                                            )
                                        success_count += 1
                                    else:
                                        skip_count += 1
                                        st.info(f"「{item.get('project_name', 'N/A')}」已存在，已跳过")
                                except Exception as e:
                                    errors.append(
                                        f"导入「{item.get('project_name', 'N/A')}」失败: {e}"
                                    )

                            # 记录日志
                            insert_import_log(
                                uploaded_file.name,
                                len(data) + len(errors),
                                success_count + skip_count,
                                len(errors),
                                "\n".join(errors[:50]),
                            )

                            if success_count > 0:
                                # 导入写入后清除只读查询缓存，保证列表读到最新数据
                                st.cache_data.clear()
                                st.success(f"✅ 成功导入 {success_count} 个项目（自动生成12道标准工序）")
                                import_ok = True
                            if skip_count > 0:
                                st.info(f"📋 {skip_count} 个项目已存在，已跳过")
                            if errors:
                                st.warning(f"⚠️ {len(errors)} 条异常:")
                                for err in errors[:15]:
                                    st.caption(f"· {err}")
                                if len(errors) > 15:
                                    st.caption(f"· ... 还有 {len(errors) - 15} 条")

                except Exception as e_fatal:
                    st.error(f"❌ 导入过程发生异常: {e_fatal}")
                    import traceback
                    st.code(traceback.format_exc()[-500:])

                # 导入成功 → 不立即 rerun，让用户看到结果
                if import_ok:
                    # 清除文件上传状态，触发页面刷新项目列表
                    st.session_state._import_done = True

        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except:
            pass


def _reset_project_page():
    """筛选/每页条数变化时，将页码重置为第1页（on_change 回调，组件实例化前执行，安全）"""
    st.session_state.project_list_page = 1


def _render_project_table():
    """渲染项目列表表格（含分页）"""
    from database import get_all_projects
    import pandas as pd

    # 分页状态初始化（持久保留，重渲染不重置）
    if "project_page_size" not in st.session_state:
        st.session_state.project_page_size = 10
    if "project_list_page" not in st.session_state:
        st.session_state.project_list_page = 1

    # 操作结果反馈（添加成功后由 flash 机制在此展示，rerun 不吞提示）
    flash = st.session_state.pop("add_flash", None)
    if flash:
        kind, msg = flash
        if kind == "success":
            st.success(msg)
        else:
            st.error(msg)

    # 单次加载项目列表（@st.cache_data 缓存复用，交互间不再重复查库）
    projects_all = get_all_projects()

    # 筛选栏：项目名称搜索 → 交付负责人 → 项目状态 → 刷新（单行水平排布，隐藏静态标题，垂直居中对齐）
    col1, col2, col3, col4 = st.columns([3, 2, 2, 1], vertical_alignment="center")
    with col1:
        search_text = st.text_input(
            "项目名称",
            placeholder="输入项目名称关键词...",
            key="project_search",
            label_visibility="collapsed",   # 隐藏静态标题，保留占位符「输入项目名称关键词...」
            on_change=_reset_project_page,   # 搜索变化 → 页码归 1
        )
    with col2:
        # 从已加载列表推导负责人选项（不再二次查库）
        persons = sorted(set(p.get("delivery_person", "") for p in projects_all if p.get("delivery_person")))
        person_filter = st.selectbox(
            "交付负责人",
            options=["全部交付负责人"] + persons,
            key="project_person_filter",
            label_visibility="collapsed",  # 隐藏静态标题，保留默认选项「全部交付负责人」及全部业务选项
            on_change=_reset_project_page,  # 负责人筛选变化 → 页码归 1
        )
    with col3:
        risk_filter = st.selectbox(
            "项目状态",
            options=["全部项目状态", "正常", "预警", "延期"],
            key="project_risk_filter",
            label_visibility="collapsed",  # 隐藏静态标题，保留默认选项「全部项目状态」及全部业务选项
            on_change=_reset_project_page,  # 状态筛选变化 → 页码归 1
        )
    with col4:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()

    # 复用已加载列表（去掉第二次 get_all_projects 调用）
    projects = projects_all

    # 筛选
    if search_text:
        projects = [p for p in projects if search_text.lower() in p.get("project_name", "").lower()]
    if person_filter != "全部交付负责人":
        projects = [p for p in projects if p.get("delivery_person") == person_filter]
    if risk_filter != "全部项目状态":
        risk_map = {"正常": "normal", "预警": "warning", "延期": "delayed"}
        projects = [p for p in projects if p.get("risk_level") == risk_map.get(risk_filter)]

    if not projects:
        st.info("暂无项目数据，请先导入月度调度令或手动添加项目。")
        # 手动添加按钮
        with st.expander("➕ 手动添加项目"):
            _render_add_project_form()
        return

    # === 分页切片（在搜索/筛选之后执行） ===
    page_size = int(st.session_state.get("project_page_size", 10))
    page_size = page_size if page_size > 0 else 10
    total_count = len(projects)
    total_pages = (total_count + page_size - 1) // page_size  # ceil 向上取整
    total_pages = max(1, total_pages)

    page = int(st.session_state.get("project_list_page", 1))
    if page > total_pages:
        # 新增/删除后当前页超出范围 → 回退到最后一页
        page = total_pages
        st.session_state.project_list_page = page
    page = max(1, page)

    start_idx = (page - 1) * page_size
    page_projects = projects[start_idx:start_idx + page_size]

    # 表头（与数据行同比例列宽）——项目名称右侧、钢塔厂家左侧新增「机型」列
    header_cols = st.columns([3, 1.5, 2, 1, 1, 2, 1.5, 1.2, 1])
    header_titles = ["项目名称", "机型", "钢塔厂家", "截止上月", "本月计划",
                     "整体进度", "交付负责人", "风险状态", "操作"]
    for col, title in zip(header_cols, header_titles):
        col.markdown(f"**{title}**")
    st.markdown("---")
    st.markdown("<style>.prj-row{margin:2px 0;}</style>", unsafe_allow_html=True)

    # 逐行渲染当前页数据：每行末尾独立「详情」按钮
    for p in page_projects:
        pid = p.get("id")
        risk = p.get("risk_level", "normal")
        risk_label = {"normal": "🟢 正常", "warning": "🟡 预警", "delayed": "🔴 延期"}.get(risk, "🟢 正常")
        risk_color = {"normal": "#38a169", "warning": "#d69e2e", "delayed": "#e53e3e"}.get(risk, "#38a169")
        progress = p.get("progress_pct", 0) or 0
        progress = max(0, min(progress, 100))

        cols = st.columns([3, 1.5, 2, 1, 1, 2, 1.5, 1.2, 1])
        with cols[0]:
            st.write(p.get("project_name", ""))
        with cols[1]:
            st.write((p.get("machine_type") or "").strip() or "—")
        with cols[2]:
            st.write(p.get("factory_name", ""))
        with cols[3]:
            st.write(str(p.get("last_month_output", 0)))
        with cols[4]:
            st.write(str(p.get("monthly_plan", 0)))
        with cols[5]:
            st.markdown(
                f"""<div style="background:#e2e8f0;border-radius:6px;height:10px;width:100%;">
                    <div style="background:{risk_color};border-radius:6px;height:10px;width:{progress}%;"></div>
                </div><span style="font-size:12px;color:#718096;">{progress:.0f}%</span>""",
                unsafe_allow_html=True,
            )
        with cols[6]:
            st.write(p.get("delivery_person", ""))
        with cols[7]:
            st.markdown(
                f"<span style='color:{risk_color};font-weight:600;'>{risk_label}</span>",
                unsafe_allow_html=True,
            )
        with cols[8]:
            # 独立详情按钮：唯一 key 防冲突
            if st.button("详情", key=f"view_detail_{pid}", type="secondary",
                         use_container_width=True):
                if pid:
                    st.session_state.selected_project_id = int(pid)
                    # 把项目ID写入URL，刷新后仍能从URL恢复（须在 switch_page 之前）
                    st.query_params["project_id"] = str(pid)
                    st.switch_page("pages/2_项目详情.py")
        st.markdown("<div style='border-top:1px solid #e2e8f0;margin:2px 0;'></div>",
                    unsafe_allow_html=True)

    # === 分页栏：弹性空列推右 + 组合列（文本+下拉紧贴）+ 固定顺序 ===
    # 顺序：共X条 → 页码 → 每页条数 → 上一页 → 下一页，整体贴靠右边缘
    # 文本与下拉合并进 horizontal container 并排（无列内空白，二者间仅 gap small）
    # 总份数守恒 10.8 → 上一页/下一页按钮列占比 1/10.8 不变
    # CSS 通过 pag-anchor 锚点 class 限定分页容器内的 selectbox，仅缩小分页下拉框（筛选栏等不受影响）
    st.markdown(
        """
        <style>
        /* 缩小分页「每页显示」下拉框：高度、内边距、字号收紧（仅限含 pag-anchor 的分页容器） */
        div[data-testid="stHorizontalBlock"]:has(div.pag-anchor) div[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
        div[data-testid="stVerticalBlock"]:has(div.pag-anchor) div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
            min-height: 24px !important;
            height: 24px !important;
            padding: 0 4px !important;
            font-size: 13px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    _, c_group, c_prev, c_next = st.columns(
        [5.5, 2.9, 1, 1], vertical_alignment="center", gap="small")

    with c_group:
        # 文本 + 下拉框同一 horizontal 容器紧贴排布，消除模块间列内空白
        with st.container(key="pag_text_size", horizontal=True,
                          vertical_alignment="center", border=False, gap="small"):
            st.markdown(
                # translateY 上移使文本顶部与下拉框顶部对齐
                f"<div class='pag-anchor' style='font-size:18px;white-space:nowrap;"
                f"transform:translateY(-5px);'>"
                f"<span style='color:#4a5568;'>共 {total_count} 条项目记录</span>"
                f"<span style='color:#718096;margin-left:12px;'>"
                f"第 <b>{page}</b> / {total_pages} 页</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            size_options = [10, 20, 50, 100]
            st.selectbox(
                "每页显示",
                options=size_options,
                format_func=lambda x: f"{x}/页",  # 展示文本：10/页、20/页…；取值仍为数字
                index=size_options.index(page_size) if page_size in size_options else 0,
                key="project_page_size",
                label_visibility="collapsed",
                width=87,  # 固定小宽度：框体仅略大于内部文字（1.60 selectbox 无 use_container_width）
                on_change=_reset_project_page,  # 切换每页条数 → 页码归 1
            )
    with c_prev:
        if st.button("◀ 上一页", key="prev_page_btn", type="secondary",
                     use_container_width=True, disabled=(page <= 1)):
            st.session_state.project_list_page = max(1, page - 1)
            st.rerun()
    with c_next:
        if st.button("下一页 ▶", key="next_page_btn", type="secondary",
                     use_container_width=True, disabled=(page >= total_pages)):
            st.session_state.project_list_page = min(total_pages, page + 1)
            st.rerun()

    # 手动添加
    with st.expander("➕ 手动添加项目"):
        _render_add_project_form()


def _render_add_project_form():
    """手动添加项目表单 — st.form + clear_on_submit 原生清空 + 四字段组合查重 + 结果反馈"""
    from database import upsert_project, init_project_processes, get_duplicate_project

    with st.form("add_project_form", clear_on_submit=True):
        st.caption("填写项目基础信息，带 * 为必填项（同一项目不同机型可分别新建）")
        col1, col2 = st.columns(2)
        with col1:
            # 顺序：项目名称 → 机型 → 钢塔厂家 → 交付负责人（机型位于名称与厂家之间）
            project_name = st.text_input("项目名称 *", key="add_name")
            machine_type = st.text_input("机型 *", key="add_machine_type")
            factory_name = st.text_input("钢塔厂家 *", key="add_factory")
            delivery_person = st.text_input("交付负责人 *", key="add_person")
        with col2:
            monthly_plan = st.number_input("本月计划出品（段）*", min_value=0, value=0,
                                           key="add_plan")
            last_month_output = st.number_input("截止上月出品（段）", min_value=0, value=0,
                                                key="add_last")
            plan_start_date = st.date_input("计划开工日期", key="add_start", value=None)
            plan_end_date = st.date_input("计划交付日期", key="add_end", value=None)

        submitted = st.form_submit_button("✅ 确认添加", type="primary",
                                          use_container_width=True)

    # 提交后由 clear_on_submit 原生清空表单，此处不再手动修改任何 widget 的 session_state
    if submitted:
        machine_type = (machine_type or '').strip()
        # ---- 必填校验（机型为必填） ----
        if not project_name or not factory_name or not delivery_person \
                or not machine_type or monthly_plan <= 0:
            st.error("请填写所有必填字段（项目名称、钢塔厂家、交付负责人、机型、本月计划出品）")
            return

        # ---- 四字段组合查重：名称+厂家+负责人+机型 全部一致才拦截 ----
        if get_duplicate_project(project_name, factory_name, delivery_person, machine_type):
            st.error("项目名称、厂家、负责人、机型均一致，该项目已存在，请勿重复添加")
            return

        try:
            data = {
                "project_name": project_name,
                "factory_name": factory_name,
                "last_month_output": last_month_output,
                "monthly_plan": monthly_plan,
                "delivery_person": delivery_person,
                "machine_type": machine_type,
                "plan_start_date": plan_start_date.strftime('%Y-%m-%d') if plan_start_date else None,
                "plan_end_date": plan_end_date.strftime('%Y-%m-%d') if plan_end_date else None,
            }
            project_id, is_new = upsert_project(data)
            if is_new and plan_start_date:
                init_project_processes(project_id, plan_start_date.strftime('%Y-%m-%d'))
                # 初始化后立即计算初始风险等级
                from database import update_project_risk_level
                update_project_risk_level(project_id)
            # 写入后清除只读查询缓存，保证列表读到最新数据
            st.cache_data.clear()
            # 成功：flash 为独立状态键（非 widget key），安全可写；rerun 刷新列表
            st.session_state["add_flash"] = ("success", f"项目「{project_name}」添加成功")
            st.rerun()
        except Exception as e:
            st.error(f"操作失败: {e}")


if __name__ == "__main__":
    main()
