# -*- coding: utf-8 -*-
"""进程内 TTL 缓存（轻量、线程安全、零依赖）—— 用于「读多写少且允许秒级延迟」的聚合结果。

适用场景（本次优化）：
    1. 首页 KPI（``get_dashboard_stats``）：4 个数字要跑一遍全量项目的风险判定，
       而它被首页每次刷新都调用 → 加 30 秒 TTL 内存缓存。
    2. 每个需认证请求都要查一次 ``users``（``get_user_by_id``）→ 加 30 秒 TTL 缓存。

⚠️ 一致性局限（必须知晓）：
    * 本缓存**进程内**：CloudRun 多副本时各副本各自一份，彼此不共享。因此
      「A 副本写入 → 清 A 副本缓存」不会清掉 B 副本的缓存，最坏情况其它副本
      会在 TTL（默认 30s）内继续返回旧值。对首页 KPI（允许 30~60s 延迟）可接受。
    * 单副本（本地/单实例部署）时由写操作显式失效，行为等同「实时」。
    * 若将来要求多副本强一致：把 ``_store`` 换成 Redis，或在响应头带
      ``X-Data-Version`` 让前端轮询；本模块接口保持不变即可无痛替换。

键设计约定：
    * 每个缓存实例自己持有独立命名空间，key 必须包含**全部影响结果的入参**
      （例如 KPI 的 key 必须含 month + big_area_person，绝不能只按 month 建键，
      否则大区数据会互相串）。
"""
import threading
import time
from typing import Any, Callable, Optional


class TTLCache:
    """带过期时间的线程安全内存缓存（key → (值, 过期时间戳)）。"""

    def __init__(self, name: str, ttl_seconds: float, max_entries: int = 512) -> None:
        """初始化。

        Args:
            name: 缓存名字（仅用于日志/统计）。
            ttl_seconds: 默认存活秒数；<= 0 表示**禁用缓存**（每次都回源，便于 A/B 比对）。
            max_entries: 条目上限，超出时按「最早过期」清理，避免异常 key 组合撑爆内存。
        """
        self.name = name
        self.ttl_seconds = float(ttl_seconds)
        self.max_entries = int(max_entries)
        self._store: dict[Any, tuple[Any, float]] = {}
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @property
    def enabled(self) -> bool:
        """缓存是否启用（TTL > 0）。"""
        return self.ttl_seconds > 0

    def get(self, key: Any) -> Optional[Any]:
        """取未过期的缓存值；未命中或已过期返回 None。"""
        if not self.enabled:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            value, expire_at = entry
            if expire_at <= now:
                self._store.pop(key, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: Any, value: Any, ttl_seconds: Optional[float] = None) -> None:
        """写入缓存（``ttl_seconds`` 缺省用实例 TTL）。"""
        if not self.enabled:
            return
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        if ttl <= 0:
            return
        now = time.monotonic()
        with self._lock:
            if len(self._store) >= self.max_entries:
                self._evict_locked(now)
            self._store[key] = (value, now + ttl)

    def get_or_set(self, key: Any, factory: Callable[[], Any]) -> Any:
        """命中则返回缓存值，否则调用 ``factory()`` 计算并写入缓存。"""
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return value

    def invalidate(self, key: Any = None) -> int:
        """失效单条（``key`` 给定）或全部条目，返回清除条数。"""
        with self._lock:
            if key is None:
                count = len(self._store)
                self._store.clear()
                return count
            return 1 if self._store.pop(key, None) is not None else 0

    def invalidate_where(self, predicate: Callable[[Any], bool]) -> int:
        """按谓词批量失效（如「只清某个 month 的所有大区」），返回清除条数。

        Args:
            predicate: 入参为 key，返回 True 则删除该条目。
        """
        with self._lock:
            victims = [k for k in self._store if predicate(k)]
            for k in victims:
                self._store.pop(k, None)
            return len(victims)

    def _evict_locked(self, now: float) -> None:
        """清理过期条目；若仍超限，按过期时间升序淘汰到上限的 80%。"""
        expired = [k for k, (_, exp) in self._store.items() if exp <= now]
        for k in expired:
            self._store.pop(k, None)
        if len(self._store) < self.max_entries:
            return
        ordered = sorted(self._store.items(), key=lambda item: item[1][1])
        target = max(1, int(self.max_entries * 0.8))
        for k, _ in ordered[: max(0, len(ordered) - target)]:
            self._store.pop(k, None)

    def stats(self) -> dict:
        """缓存运行状态（自测/排障用）。"""
        with self._lock:
            size = len(self._store)
        total = self.hits + self.misses
        return {
            "name": self.name,
            "enabled": self.enabled,
            "ttl_seconds": self.ttl_seconds,
            "entries": size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }

    def clear_stats(self) -> None:
        """清零命中统计（压测分段统计用）。"""
        with self._lock:
            self.hits = 0
            self.misses = 0
