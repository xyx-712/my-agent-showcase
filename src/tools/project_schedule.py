"""Deterministic remaining-duration DAG and explicit working calendar."""
from datetime import date, timedelta
import re

from pydantic import BaseModel, ConfigDict, Field


DIGITS = dict(zip("零一二三四五六七八九", range(10)))
DIGITS["〇"] = 0


def number(value):
    value = str(value).strip().replace("两", "二").replace("〇", "零")
    if re.fullmatch(r"[0-9]+", value):
        return int(value)
    if not value or not re.fullmatch(r"[零一二三四五六七八九十百千]+", value):
        raise ValueError("工期数字无法确定")
    if len(value) > 1 and not re.search("[十百千]", value):
        raise ValueError("中文数量缺少明确的十百千单位")
    if re.search(r"[一二三四五六七八九]{2}|[百千][一二三四五六七八九]$", value):
        raise ValueError("中文数量存在歧义，请使用完整数量或阿拉伯数字")
    total = current = 0
    previous_unit = 10000
    for char in value:
        if char in DIGITS:
            current = DIGITS[char]
        else:
            unit = {"十": 10, "百": 100, "千": 1000}[char]
            if unit >= previous_unit:
                raise ValueError("中文数量单位顺序不明确")
            previous_unit = unit
            total += (current or 1) * unit
            current = 0
    return total + current


def normalized_date(value):
    value = value.strip().removesuffix(" 收工").removesuffix("收工").strip()
    numeric = re.fullmatch(r"([0-9]{4})[-/]([0-9]{1,2})[-/]([0-9]{1,2})", value)
    if numeric:
        return date(*map(int, numeric.groups()))
    try:
        return date.fromisoformat(value)
    except ValueError:
        match = re.fullmatch(r"([0-9零〇一二三四五六七八九]{4})年([0-9一二三四五六七八九十]+)月([0-9一二三四五六七八九十]+)[日号]", value)
        if not match:
            raise ValueError("请补充明确的年月日")
        year = int("".join(str(DIGITS.get(c, c)) for c in match[1]))
        return date(year, number(match[2]), number(match[3]))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Activity(Strict):
    name: str = Field(min_length=1, max_length=100)
    remaining: int = Field(ge=0, le=10000)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    as_of: str
    release: int = Field(default=0, ge=0, le=10000)


class WorkCalendar(Strict):
    start: str
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)
    holidays: list[str] = Field(default_factory=list, max_length=1000)
    workdays: list[str] = Field(default_factory=list, max_length=1000)


def calculate_network(activities, calendar=None):
    nodes = [Activity.model_validate(a) for a in activities]
    if not nodes or len(nodes) > 200:
        raise ValueError("请提供 1–200 项任务")
    by_name = {a.name: a for a in nodes}
    if len(by_name) != len(nodes):
        raise ValueError("任务名称重复")
    dates = {normalized_date(a.as_of) for a in nodes}
    if len(dates) != 1:
        raise ValueError("统计日期不同，不能合并剩余工期")
    for node in nodes:
        if len(set(node.dependencies)) != len(node.dependencies):
            raise ValueError("依赖重复")
        if any(dep not in by_name for dep in node.dependencies):
            raise ValueError("依赖任务不存在")
    pending = list(by_name)
    timeline = {}
    critical_parent = {}
    while pending:
        ready = [name for name in pending if all(dep in timeline for dep in by_name[name].dependencies)]
        if not ready:
            raise ValueError("任务依赖存在循环")
        for name in ready:
            node = by_name[name]
            parent = max(node.dependencies, key=lambda dep: timeline[dep]["finish"], default=None)
            dependency_end = timeline[parent]["finish"] if parent else 0
            start = max(node.release, dependency_end)
            timeline[name] = {"start": start, "finish": start + node.remaining}
            critical_parent[name] = parent if dependency_end >= node.release else None
            pending.remove(name)
    finish = max(timeline, key=lambda name: timeline[name]["finish"])
    duration = timeline[finish]["finish"]
    path = []
    current = finish
    while current:
        path.append(current)
        current = critical_parent[current]
    successors = {name: [] for name in by_name}
    for node in nodes:
        for dependency in node.dependencies:
            successors[dependency].append(node.name)
    for name in reversed(list(timeline)):
        latest_finish = min((timeline[child]["latest_start"] for child in successors[name]), default=duration)
        latest_start = latest_finish - by_name[name].remaining
        timeline[name].update({"latest_start": latest_start, "slack": latest_start - timeline[name]["start"]})
    result = {"remaining": duration, "critical_path": list(reversed(path)), "critical_tasks": [name for name in timeline if timeline[name]["slack"] == 0], "timeline": timeline,
              "as_of": next(iter(dates)).isoformat(),
              "calendar_note": "未提供工作日历，仅计算工作日长度，不推算完成日期"}
    if calendar:
        cal = WorkCalendar.model_validate(calendar)
        weekdays = set(cal.weekdays)
        if not weekdays <= set(range(7)):
            raise ValueError("工作周需使用 0–6（周一到周日）")
        holidays = {normalized_date(d) for d in cal.holidays}
        workdays = {normalized_date(d) for d in cal.workdays}
        if holidays & workdays:
            raise ValueError("节假日与补班日期冲突")
        start = normalized_date(cal.start)
        if start < next(iter(dates)):
            raise ValueError("起算日期早于统计日期")
        day = start
        counted = 0
        for _ in range(50000):
            is_workday = day in workdays or (day.weekday() in weekdays and day not in holidays)
            if is_workday:
                counted += 1
            if counted >= duration:
                break
            day += timedelta(days=1)
        else:
            raise ValueError("日历计算超过范围")
        result.update({"finish_date": day.isoformat() if duration else start.isoformat(),
                       "calendar_note": "起算日计入首个工作日；仅采用用户指定工作周、节假日和补班日期"})
    return result
