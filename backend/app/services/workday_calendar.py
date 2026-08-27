"""
workday_calendar.py — 工作日历工具模块 (v3.0 自然日模式)
负责日期计算、节假日管理。
默认按自然日历天排产，每一天均为生产日，不跳过周末/节假日。

Author: Senior Developer
Date: 2026-08-03 / 2026-08-06 (v3.0)
"""

from datetime import datetime, date, timedelta
from typing import Optional


# 全局节假日缓存（保留接口，默认不参与计算）
_CUSTOM_HOLIDAYS: list[date] = []


def set_holidays(holidays: list[date]) -> None:
    """设置自定义节假日列表"""
    global _CUSTOM_HOLIDAYS
    _CUSTOM_HOLIDAYS = sorted(holidays)


def get_holidays() -> list[date]:
    """获取当前节假日列表"""
    return _CUSTOM_HOLIDAYS.copy()


def add_holiday(holiday_date: date) -> None:
    """添加单个节假日"""
    if holiday_date not in _CUSTOM_HOLIDAYS:
        _CUSTOM_HOLIDAYS.append(holiday_date)
        _CUSTOM_HOLIDAYS.sort()


def remove_holiday(holiday_date: date) -> None:
    """移除单个节假日"""
    if holiday_date in _CUSTOM_HOLIDAYS:
        _CUSTOM_HOLIDAYS.remove(holiday_date)


def parse_date(date_str: Optional[str]) -> Optional[date]:
    """
    将日期值解析为 date 对象。
    支持格式：str (YYYY-MM-DD, MM/DD/YY, YYYY/MM/DD)、datetime、Timestamp、date。
    """
    if date_str is None:
        return None

    if isinstance(date_str, datetime):
        return date_str.date()

    if isinstance(date_str, date):
        return date_str

    try:
        import pandas as pd
        if isinstance(date_str, pd.Timestamp):
            return date_str.date()
    except ImportError:
        pass

    if isinstance(date_str, str):
        date_str = date_str.strip()
        if not date_str:
            return None

        for fmt in ['%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        for fmt in ['%m/%d/%y', '%m/%d/%Y', '%m-%d-%Y', '%m-%d-%y']:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        try:
            import pandas as pd
            num = float(date_str)
            if 40000 < num < 100000:
                return pd.Timestamp('1899-12-30') + pd.Timedelta(days=int(num))
        except (ImportError, ValueError, OverflowError):
            pass

    return None


# ============================================================
# v3.0: 自然日历天模式 — 每一天均为生产日
# ============================================================

def is_workday(check_date: date) -> bool:
    """v3.0 自然日模式：每一天都是生产日。"""
    return True


def next_workday(from_date: date) -> date:
    """v3.0: 自然日模式下直接返回自身"""
    return from_date


def prev_workday(from_date: date) -> date:
    """v3.0: 自然日模式下直接返回自身"""
    return from_date


def add_workdays(from_date: date, days: int) -> date:
    """v3.0: 按自然日累加 from_date + days。"""
    if days <= 0:
        return from_date
    return from_date + timedelta(days=days)


def subtract_workdays(from_date: date, days: int) -> date:
    """v3.0: 按自然日回退 from_date - days。"""
    if days <= 0:
        return from_date
    return from_date - timedelta(days=days)


def count_workdays_between(start_date: date, end_date: date) -> int:
    """v3.0: 直接计算日历天数 (end - start).days + 1（含起止日）。"""
    if start_date > end_date:
        return 0
    return (end_date - start_date).days + 1


def calculate_lag_days(plan_end_date_str: str,
                        current_date: Optional[date] = None,
                        is_completed: bool = False) -> int:
    """
    计算滞后天数（自然日历天）。
    """
    if is_completed:
        return 0

    plan_end = parse_date(plan_end_date_str)
    if not plan_end:
        return 0

    today = current_date or date.today()

    if today <= plan_end:
        return 0

    return (today - plan_end).days


# ============================================================
# 单元测试（可通过 python -m utils.workday_calendar 运行）
# ============================================================
if __name__ == '__main__':
    set_holidays([])

    # 测试1: 自然日模式下每一天都是工作日
    mon = date(2026, 8, 3)   # 周一
    sat = date(2026, 8, 8)   # 周六
    assert is_workday(mon) == True, f"周一应为生产日"
    assert is_workday(sat) == True, f"周六应为生产日（自然日模式）"
    print("✅ 测试1 通过：自然日模式每一天都是生产日")

    # 测试2: 添加2个自然日 — 周一+2=周三
    result = add_workdays(date(2026, 8, 3), 2)
    assert result == date(2026, 8, 5), f"期望 08-05(周三), 实际 {result}"
    print("✅ 测试2 通过：自然日累加")

    # 测试3: 跨周末 — 周五+1=周六（不跳过）
    result = add_workdays(date(2026, 8, 7), 1)
    assert result == date(2026, 8, 8), f"期望 08-08(周六，不跳过), 实际 {result}"
    print("✅ 测试3 通过：跨周末不跳过")

    # 测试4: 回退自然日 — 周五-2=周三
    result = subtract_workdays(date(2026, 8, 7), 2)
    assert result == date(2026, 8, 5), f"期望 08-05(周三), 实际 {result}"
    print("✅ 测试4 通过：自然日回退")

    # 测试5: 滞后天数 — 自然日历天
    set_holidays([])
    lag = calculate_lag_days('2026-07-31', date(2026, 8, 3), is_completed=False)
    assert lag == 3, f"期望滞后3天(日历), 实际 {lag}"
    print("✅ 测试5 通过：滞后天数=3天（自然日）")

    # 测试6: 跨周末滞后天数
    lag = calculate_lag_days('2026-07-30', date(2026, 8, 3), is_completed=False)
    assert lag == 4, f"期望滞后4天(日历), 实际 {lag}"
    print(f"✅ 测试6 通过：滞后天数={lag}天（自然日）")

    print("\n🎉 全部测试通过！(v3.0 自然日模式)")
