# 塔筒生产进度管控系统 - 后端镜像
# 架构：FastAPI + MySQL，桥接复用根 directory database.py + backend/ 包
# 构建上下文 = 项目根目录（tower_production_system/）
FROM python:3.11-slim

WORKDIR /app

# 编译依赖（pandas/openpyxl 等多为预编译 wheel，gcc 仅作兜底）
# tzdata：提供 IANA 时区数据（/usr/share/zoneinfo），使下面的 ENV TZ 生效，
#         并让 Python 的 zoneinfo.ZoneInfo("Asia/Shanghai") 可用（python:3.11-slim
#         默认不含 tzdata）。DEBIAN_FRONTEND=noninteractive 避免装 tzdata 时交互询问。
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends gcc tzdata \
    && rm -rf /var/lib/apt/lists/*

# 先装 Python 依赖（利用镜像层缓存）
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# 桥接依赖（关键）：
#   backend/app/core/db.py  -> from database import ...
#   database.py             -> from backend.app.core.config import MYSQL_CONFIG
# config.py 加载时会把项目根插入 sys.path，桥接自洽。
# 二者缺一不可，必须一起打进镜像，且 cwd = 项目根。
COPY database.py /app/database.py
COPY backend/ /app/backend/

# 注意：根目录 test_bugs.py / test_business_format.py 仍 import 旧 utils.*，
#       仅测试用，勿复制进镜像（本 Dockerfile 只 COPY database.py + backend/，已避开）。

# 业务时区固定东八区：容器系统时间/日志/原生 date.today() 均为北京时间；
# 与 backend/app/core/timeutil.py 的 BUSINESS_TZ（"Asia/Shanghai"）保持同一基准。
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# CloudRun 会注入 PORT 环境变量；缺省回退 8000。
# 服务「监听端口」须与此一致（建议设为 8000）。
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
