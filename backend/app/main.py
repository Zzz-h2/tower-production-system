# -*- coding: utf-8 -*-
"""FastAPI 应用入口：CORS、路由挂载、（可选）WebSocket。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import projects, nodes, schedule_import, dashboard, dispatch_import, exceptions, ranking

app = FastAPI(
    title="塔筒生产进度管控系统 API",
    version="1.0.0",
    description="前后端分离式单体后端（FastAPI + MySQL，业务逻辑与 Streamlit 版 1:1 一致）",
)

# CORS：本地 Vite 开发服务器 + CloudBase 静态托管前端域名（直连后端，跨域由 CORS 兜底）
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://tower-frontend-cloudbase-d2g5mgnii8ac68cb7.webapps.tcloudbase.com",
        "https://tower-frontend-cloudbase-d2g5jgnii8ac68cb7.webapps.tcloudbase.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(nodes.router)
app.include_router(schedule_import.router)
app.include_router(dashboard.router)
app.include_router(dispatch_import.router)
app.include_router(exceptions.router)
app.include_router(ranking.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tower-production-api"}


# ---------- 可选：WebSocket 实时进度推送 ----------
# 保留挂载占位；启用时接入 ws 管理器即可。
# from .ws import manager  # noqa
