"""Interpret schedule records and cite their original locations."""
from datetime import date
import re


FIELDS = ("项目", "版本", "日期", "状态", "替代", "统计时点", "口径", "第一阶段剩余", "第二阶段剩余")
BASIS = "剩余工作日，阶段串行，每周五个工作日"


def reference(section):
    return f'{section["file"]}「{section["heading"]}」L{section["start"]}–{section["end"]}'


def records(sections):
    parsed = []
    for section in sections:
        pairs = [line.split("：", 1) for line in section["lines"] if "：" in line]
        fields = dict(pairs)
        if (any(key not in fields or not fields[key] for key in FIELDS)
                or any(sum(pair[0] == key for pair in pairs) != 1 for key in FIELDS)):
            raise ValueError(f'{reference(section)} 缺少必填字段或字段重复。')
        try:
            if fields["状态"] not in {"已批准", "草案"} or fields["口径"] != BASIS:
                raise ValueError()
            if not re.fullmatch(r"V[1-9]\d{0,3}", fields["版本"]):
                raise ValueError()
            published = date.fromisoformat(fields["日期"])
            as_of = date.fromisoformat(fields["统计时点"].removesuffix(" 收工"))
            durations = [fields[key] for key in FIELDS[-2:]]
            if any(not re.fullmatch(r"\d{1,4}", value) for value in durations) or published > as_of:
                raise ValueError()
        except ValueError as error:
            raise ValueError(f'{reference(section)} 的日期、工期或口径无法判定。') from error
        parsed.append((fields, section))
    return parsed


def select_record(sections, requested):
    parsed = records(sections)
    approved = [(data, source) for data, source in parsed if data["状态"] == "已批准"]
    if not approved:
        raise ValueError("缺少已批准的计划或变更记录，请补充资料后发送「重新检索」。")
    by_version = {data["版本"]: (data, source) for data, source in approved}
    if len(by_version) != len(approved):
        raise ValueError("存在同版本的多份批准记录，请核对资料后发送「重新检索」。")
    if requested:
        if requested not in by_version:
            raise ValueError("请指定资料中已批准的版本。")
        return by_version[requested]

    heads = set(by_version) - {data["替代"] for data, _ in approved}
    visited = set()
    version = next(iter(heads)) if len(heads) == 1 else None
    chosen = version
    while version in by_version and version not in visited:
        visited.add(version)
        current = by_version[version][0]
        version = current["替代"]
        if version in by_version and by_version[version][0]["日期"] > current["日期"]:
            break
    if version != "无" or visited != set(by_version):
        citations = "；".join(f'{data["版本"]} {reference(source)}' for data, source in approved)
        raise ValueError(f"批准记录的替代关系不明确（{citations}）。请指定版本，例如「用 {approved[0][0]['版本']}」。")
    return by_version[chosen]
