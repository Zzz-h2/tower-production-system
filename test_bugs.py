"""验证用户报告的两个 bug 是否修复"""
import sys; sys.path.insert(0, '.')
from datetime import date, timedelta
from utils.business_logic import refresh_processes_from_db
from utils.workday_calendar import parse_date

T = date.today()

def _calc_deviation(proc):
    today = date.today()
    actual_start = parse_date(proc.get('actual_start_date')) if proc.get('actual_start_date') else None
    actual_end   = parse_date(proc.get('actual_end_date'))   if proc.get('actual_end_date')   else None
    plan_end     = parse_date(proc.get('plan_end_date'))     if proc.get('plan_end_date')     else None
    if not actual_start:
        return ('—', '#718096')
    if actual_end and actual_start and actual_end < actual_start:
        return ('时间倒序', '#e53e3e')
    if not actual_end:
        if plan_end and today > plan_end:
            days = (today - plan_end).days
            return (f'滞后{days}天', '#e53e3e')
        return ('—', '#718096')
    if not plan_end:
        return ('—', '#718096')
    if actual_end < plan_end:
        days = (plan_end - actual_end).days
        return (f'提前{days}天', '#38a169')
    elif actual_end == plan_end:
        return ('准时', '#718096')
    else:
        days = (actual_end - plan_end).days
        return (f'滞后{days}天', '#e53e3e')

# === BUG 1: 坡口 — 计划 08-05~08-06, 实际 08-04~08-07 ===
procs_bug1 = [{
    'process_order': 1, 'process_name': '下料', 'standard_days': 2,
    'plan_start_date': '2026-08-03', 'plan_end_date': '2026-08-04',
    'actual_start_date': '2026-08-03', 'actual_end_date': '2026-08-04',
}, {
    'process_order': 2, 'process_name': '坡口', 'standard_days': 2,
    'plan_start_date': '2026-08-05', 'plan_end_date': '2026-08-06',
    'actual_start_date': '2026-08-04', 'actual_end_date': '2026-08-07',
}]
r1 = refresh_processes_from_db(procs_bug1)
s = r1[1]['status']
d = _calc_deviation(r1[1])
print(f'BUG1 坡口: status={s}, deviation={d[0]}')
assert s == 'completed', f'BUG1 FAIL: status={s}, expected completed'
assert '滞后' in d[0], f'BUG1 FAIL: deviation={d[0]}, expected 滞后'
print('  OK: completed + 滞后')

# === BUG 2: 卷板 — 计划 08-07~08-07, 实际 08-08~08-08 ===
procs_bug2 = [{
    'process_order': 1, 'process_name': '下料', 'standard_days': 2,
    'plan_start_date': '2026-08-03', 'plan_end_date': '2026-08-04',
    'actual_start_date': '2026-08-03', 'actual_end_date': '2026-08-04',
}, {
    'process_order': 2, 'process_name': '坡口', 'standard_days': 2,
    'plan_start_date': '2026-08-05', 'plan_end_date': '2026-08-06',
    'actual_start_date': '2026-08-05', 'actual_end_date': '2026-08-06',
}, {
    'process_order': 3, 'process_name': '卷板', 'standard_days': 1,
    'plan_start_date': '2026-08-07', 'plan_end_date': '2026-08-07',
    'actual_start_date': '2026-08-08', 'actual_end_date': '2026-08-08',
}]
r2 = refresh_processes_from_db(procs_bug2)
s2 = r2[2]['status']
d2 = _calc_deviation(r2[2])
print(f'BUG2 卷板: status={s2}, deviation={d2[0]}')
assert s2 == 'completed', f'BUG2 FAIL: status={s2}, expected completed'
assert '滞后' in d2[0], f'BUG2 FAIL: deviation={d2[0]}, expected 滞后'
print('  OK: completed + 滞后')

print('\nBOTH bugs FIXED')
