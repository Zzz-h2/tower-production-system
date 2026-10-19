# -*- coding: utf-8 -*-
"""MySQL 连接池（DBUtils ``PooledDB`` 封装）—— 本项目「新建连接」唯一入口。

背景（2026-10 生产卡顿修复）：
    改造前 ``core/db.py`` 与根 ``database.py`` 的 ``get_connection()`` 都是**每次调用
    直接 ``pymysql.connect()``**：一个请求内 5~11 次建连，每次要走 TCP 握手 + MySQL
    handshake。云上服务未配 VPC，实际公网连库，单次建连 30~80ms → 单请求 0.3~0.6s。
    接口返回 89 字节也要 0.62s 即由此而来（瓶颈是往返次数，不是数据量）。

设计取舍（为什么这样配）：
    * ``mincached=2 / maxcached=20 / maxconnections=20 / blocking=True``
        - ``blocking=True`` 让「并发超过池上限」的请求**排队等待**而不是抛
          ``TooManyConnections``（并发下不产生 5xx）。
        - ``maxcached`` 取 **20 = maxconnections**（2026-10 实测，见
          ``qa_tmp/perf_pool_tune.py`` / ``qa_tmp/perf_verify2.py``）：
          DBUtils 归还连接时**只保留 maxcached 条 idle，超出即真关闭**；
          ``maxcached < maxconnections`` 且小于典型并发时（FastAPI 线程池 40），
          高并发会反复「关掉—重建」，公网环境下每次 30~60ms 握手全部白付。
          取 20 后池内连接只增不销毁（上限 20），实测新建物理连接 35 → 0~2 条，
          p50 0.345s → 0.167s。
    * ⚠️ **每副本物理连接上限 = 两个池 × maxconnections = 40 条**（不是 20）：
        本项目云库实测 ``max_connections = 1000``、历史峰值 ``Max_used_connections = 6``
        —— 按 5 副本 × 40 = 200 仍远低于 1000，**无需保守**。
        若将来副本数/池参数上调，请按「副本数 × 2 × maxconnections」复核云库上限，
        必要时用环境变量 ``DB_POOL_MAX_CONNECTIONS`` 下调。
    * ``ping=1``：**取连接时**探测一次，连接被 MySQL 重启 / 云上 idle 超时
      （``wait_timeout``）掐断后自动重连，避免「服务器已断开」类 5xx。

    * ``reset``：
        - ``autocommit=True`` 池（``core/db.py`` 语义）：每条语句独立提交，池内连接
          **不存在未提交事务**，故 ``reset=False`` —— 省掉归还连接时那次多余 ROLLBACK
          往返（公网环境下每次约 30~40ms）。
        - ``autocommit=False`` 池（根 ``database.py`` 语义，显式 commit）：必须
          ``reset=True``，归还连接时自动 ROLLBACK 掉未提交事务 —— 与改造前「关掉连接
          = 未提交内容丢弃」的语义**完全一致**，绝不让上一个请求的半截事务留给下一个请求。
    * ``init_command="SET FOREIGN_KEY_CHECKS=1"``：根 ``database.py`` 原本在**每次建连**
      后执行该语句（历史 SQLite→MySQL 迁移遗留）。放进 ``init_command`` 后变成
      「每建立一条物理连接执行一次」，语义不变、且不再每次取连接都多一次往返。

调用方**无需修改**：``PooledDB`` 返回的连接对象 ``close()`` 的语义就是**归还连接**
（不是真关闭），现有 ``conn = get_connection() ... try/finally: conn.close()`` 全部照旧。
"""
import logging
import os
import threading
from typing import Any

import pymysql
import pymysql.cursors

from .config import MYSQL_CONFIG

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量（非法值回退默认，避免启动即崩）。"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回退默认值 %d", name, raw, default)
        return default


# ---------- 池参数（可用环境变量覆盖，便于压测与线上微调） ----------
# ⚠️ 每副本实际物理连接上限 = 2 个池 × POOL_MAX_CONNECTIONS（默认 20）= 40；
#    本项目云库实测 max_connections=1000、历史峰值 Max_used_connections=6，
#    5 副本 × 40 = 200 仍安全。
#    maxcached 取 = maxconnections（20）：避免「并发 > maxcached 就关连接再重建」的抖动，
#    依据见模块 docstring 与 qa_tmp/perf_pool_tune.py、qa_tmp/perf_verify2.py 实测。
POOL_MIN_CACHED = _env_int("DB_POOL_MIN_CACHED", 2)
POOL_MAX_CACHED = _env_int("DB_POOL_MAX_CACHED", 20)
POOL_MAX_CONNECTIONS = _env_int("DB_POOL_MAX_CONNECTIONS", 20)

# 两种 autocommit 语义各一个池（互不串扰：autocommit 是连接级属性，不能共用）
_POOLS: dict[bool, Any] = {}
_POOL_LOCK = threading.Lock()


def _build_pool(autocommit: bool) -> Any:
    """构建一个 ``PooledDB``。首次取连接时才真正建物理连接（导入时不连库）。"""
    from dbutils.pooled_db import PooledDB

    return PooledDB(
        creator=pymysql,
        mincached=POOL_MIN_CACHED,
        maxcached=POOL_MAX_CACHED,
        maxconnections=POOL_MAX_CONNECTIONS,
        blocking=True,
        # 取连接时探活 + 自动重连（连接被 kill / 被 wait_timeout 掐断后自愈）
        ping=1,
        # autocommit=True 的连接无未提交事务，归还时无需 ROLLBACK（省一次往返）；
        # autocommit=False 必须 rollback，保持「关连接=丢弃未提交事务」原语义。
        reset=not autocommit,
        maxusage=None,
        # 建物理连接时设置一次，替代原先每次建连后的 SET FOREIGN_KEY_CHECKS=1
        init_command="SET FOREIGN_KEY_CHECKS=1",
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        charset=MYSQL_CONFIG["charset"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=autocommit,
    )


def get_pool(autocommit: bool = True) -> Any:
    """取（必要时惰性创建）指定 autocommit 语义的连接池（进程内单例）。

    Args:
        autocommit: True = 与 ``core/db.py`` 原实现一致（每条语句自动提交）；
            False = 与根 ``database.py`` 原实现一致（显式 commit / rollback）。

    Returns:
        PooledDB: 连接池对象。
    """
    pool = _POOLS.get(autocommit)
    if pool is not None:
        return pool
    with _POOL_LOCK:
        pool = _POOLS.get(autocommit)
        if pool is None:
            pool = _build_pool(autocommit)
            _POOLS[autocommit] = pool
            logger.info(
                "MySQL 连接池已初始化：autocommit=%s mincached=%d maxcached=%d "
                "maxconnections=%d ping=1 host=%s:%s/%s",
                autocommit, POOL_MIN_CACHED, POOL_MAX_CACHED, POOL_MAX_CONNECTIONS,
                MYSQL_CONFIG["host"], MYSQL_CONFIG["port"], MYSQL_CONFIG["database"],
            )
    return pool


def get_connection(autocommit: bool = True) -> Any:
    """从池中取一条连接（``close()`` 即归还）。

    Args:
        autocommit: True/False 决定使用哪个池（见 ``get_pool``）。

    Returns:
        PooledDedicatedDBConnection: 池化连接，接口与 pymysql.Connection 兼容
        （cursor / commit / rollback / close）。
    """
    return get_pool(autocommit).connection()


def pool_stats() -> dict:
    """池内连接统计（自测/排障用；不影响业务）。

    Returns:
        dict: 每个池的 {mincached, maxcached, maxconnections, idle, in_use}。
        说明：``idle`` 为当前空闲缓存数；``in_use`` 为已借出数（未做精确追踪，
        以 maxconnections - idle 近似不可靠，故只返回能直接读到的计数）。
    """
    out = {}
    for autocommit, pool in _POOLS.items():
        try:
            idle = len(pool._idle_cache)          # noqa: SLF001 — 只读观测，不参与业务
            shared = len(getattr(pool, "_shared_cache", []) or [])
            out[str(autocommit)] = {
                "mincached": POOL_MIN_CACHED,
                "maxcached": POOL_MAX_CACHED,
                "maxconnections": POOL_MAX_CONNECTIONS,
                "idle": idle,
                "shared": shared,
            }
        except Exception as exc:  # noqa: BLE001 — 观测接口不得影响业务
            out[str(autocommit)] = {"error": str(exc)}
    return out
