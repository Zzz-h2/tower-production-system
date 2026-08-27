# -*- coding: utf-8 -*-
"""FastAPI 应用入口：CORS、路由挂载、（可选）WebSocket。"""
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.deps import require_login
from .routers import (config, projects, nodes, schedule_import, dashboard,
                      dispatch_import, exceptions, ranking, auth)

app = FastAPI(
    title="塔筒生产进度管控系统 API",
    version="1.0.0",
    description="塔筒生产进度管控后端：调度令/排产导入、项目与工序节点进度、填报联动校验、异常预警、里程碑倒排与出品排名（FastAPI + MySQL）",
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

# 认证 router：公开（登录/登出/当前用户）
app.include_router(config.router, dependencies=[Depends(require_login)])
app.include_router(auth.router)

# 业务 router：统一登录保护（T01 预期行为：无 token 访问业务接口返回 401）
# 行级数据隔离注入由 T02 完成；此处仅做 router 级登录校验。
app.include_router(projects.router, dependencies=[Depends(require_login)])
app.include_router(nodes.router, dependencies=[Depends(require_login)])
app.include_router(schedule_import.router, dependencies=[Depends(require_login)])
app.include_router(dashboard.router, dependencies=[Depends(require_login)])
app.include_router(dispatch_import.router, dependencies=[Depends(require_login)])
app.include_router(exceptions.router, dependencies=[Depends(require_login)])
app.include_router(ranking.router, dependencies=[Depends(require_login)])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tower-production-api"}
