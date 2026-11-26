"""Bounded LangGraph workflow for the local project documents."""
import os
import re
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from httpx import HTTPError
from ollama import ResponseError
from pydantic import BaseModel, ConfigDict, Field

from src.config import IS_DEMO
from src.server.schedule_tasks import load_task, save_task
from src.agent.schedule_records import reference, select_record
from src.tools.calculator import calculator
from src.tools.document_search import search_documents


class KeywordArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    keyword: str = Field(pattern=r"^[\w-]{1,32}$")


class CalculatorArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expression: str = Field(pattern=r"^[0-9]{1,4} \+ [0-9]{1,4} \+ [0-9]{1,4}$")


TOOLS = {
    "document_search": (KeywordArgs, search_documents),
    "calculator": (CalculatorArgs, calculator),
}
MAX_STEPS = 4
RESUME = {"继续任务", "重新检索"}
DELAY_PREFIX = re.compile(r"第二阶段.*(?:延后|推迟|延期)")
DELAY_VALUE = re.compile(
    r"(?:(?:第二阶段\s*(?:再\s*)?(?:延后|推迟|延期))\s*)?"
    r"([0-9]{1,3}|[一二两三四五六七八九十百零]{1,6})\s*(周|工作日)(?:呢)?[。？！?]?"
)
PROJECT = re.compile(r"([\w-]{1,32})项目")
VERSION = re.compile(r"(?:用|选|指定)\s*(V[1-9]\d{0,3})\b", re.I)


class Turn(TypedDict, total=False):
    user_id: str
    task: dict
    steps: int
    action: tuple[str, dict] | None
    answer: str
    calls: list[str]


def plan(state):
    task = state["task"]
    if state["steps"] >= MAX_STEPS:
        return {"action": None, "answer": "本轮已到达工具步数上限。请发送「继续任务」。"}
    if "sections" not in task:
        return {"action": ("document_search", {"keyword": task["project"]})}
    try:
        record, source = select_record(task["sections"], task["version"])
    except ValueError as error:
        task = {**task, "pending": "version_or_documents"}
        save_task(state["user_id"], task)
        return {"task": task, "action": None, "answer": str(error)}

    expression = f'{int(record["第一阶段剩余"])} + {int(record["第二阶段剩余"])} + {task["delay"]}'
    if "result" not in task:
        return {"action": ("calculator", {"expression": expression})}

    change_note = ""
    if task["delay"]:
        change_note = f'（第二阶段额外延后 {task["delay"]} 个工作日，来自本会话的假设）'
    return {
        "task": {**task, "pending": None},
        "action": None,
        "answer": (
            f'{task["project"]}项目剩余 {task["result"]} 个工作日{change_note}。\n'
            f'计算：{expression} = {task["result"]}。\n'
            f'口径：{record["统计时点"]}，{record["口径"]}。\n'
            f'依据：已批准 {record["版本"]}（{record["日期"]}），{reference(source)}。'
        ),
    }


def execute(state):
    name, args = state["action"]
    task = state["task"]
    update = {"steps": state["steps"] + 1, "calls": [*state["calls"], name]}
    try:
        if name not in TOOLS:
            raise ValueError("未知工具")
        schema, tool = TOOLS[name]
        arguments = schema.model_validate(args).model_dump()
        if (name == "calculator" and not IS_DEMO
                and os.environ.get("MY_AGENT_FAIL_CALCULATOR_ONCE") == "1"
                and not task.get("fault_injected")):
            task = {**task, "fault_injected": True}
            raise OSError("本地演示注入的临时故障")
        result = tool(**arguments)
        if name == "calculator":
            if not result["success"]:
                raise ValueError(result["error"])
            task = {**task, "result": result["result"], "pending": None}
        else:
            task = {**task, "sections": result, "pending": None}
    except (ValueError, OSError) as error:
        task = {**task, "pending": name}
        save_task(state["user_id"], task)
        return {**update, "task": task,
                "answer": f"{name} 执行失败：{error}。请发送「继续任务」重试。"}
    save_task(state["user_id"], task)
    return {**update, "task": task}


def build_workflow():
    builder = StateGraph(Turn)
    builder.add_node("plan", plan)
    builder.add_node("execute", execute)
    builder.add_edge(START, "plan")
    builder.add_conditional_edges("plan", lambda state: END if state.get("answer") else "execute",
                                  [END, "execute"])
    builder.add_conditional_edges("execute", lambda state: END if state.get("answer") else "plan",
                                  [END, "plan"])
    return builder.compile()


workflow = build_workflow()


def new_task(project):
    return {"id": uuid4().hex, "project": project, "delay": 0, "version": None}


def parse_delay(messages, model):
    """Normalize an explicitly stated amount; the model is not needed for arithmetic."""
    from src.tools.project_schedule import number
    match = DELAY_VALUE.fullmatch(messages[-1].content)
    if not match:
        raise ValueError("ambiguous delay")
    amount = number(match[1])
    if not 0 <= amount <= 999:
        raise ValueError("delay out of range")
    return amount * (5 if match[2] == "周" else 1)


def schedule_turn(messages, model, user_id):
    message = messages[-1].content
    version = VERSION.fullmatch(message)
    is_delay = DELAY_PREFIX.search(message)
    if not is_delay and message not in RESUME and not version and "剩余工期" not in message:
        # Check for a short answer to a previously requested delay.
        if not DELAY_VALUE.fullmatch(message):
            return None
        previous = load_task(user_id)
        if not previous or previous.get("pending") != "delay":
            return None
        is_delay = True
    else:
        previous = load_task(user_id)

    if is_delay:
        if not previous:
            return {"answer": "请先说明要计算哪个项目的剩余工期。", "calls": []}
        task = previous.copy()
        try:
            task["delay"] = task["delay"] + parse_delay(messages, model)
            if task["delay"] > 9999:
                raise ValueError("delay out of range")
        except (HTTPError, ResponseError, ConnectionError, TimeoutError):
            return {"answer": "本机 Ollama 暂时无法解析追问，请恢复服务后重新发送延后条件。", "calls": []}
        except (ValueError, AttributeError, TypeError):
            save_task(user_id, {**previous, "pending": "delay"})
            return {"answer": "请明确第二阶段额外延后多少周或工作日。",
                    "calls": [], "task": {**previous, "pending": "delay"}}
        task.pop("result", None)
    elif message in RESUME or version:
        if not previous:
            return {"answer": "当前会话没有可继续的任务，请先询问项目剩余工期。", "calls": []}
        if message == "继续任务" and previous.get("pending") == "delay":
            return {"answer": "请先补充第二阶段延后的周数或工作日数。", "calls": []}
        task = previous.copy()
        if message == "重新检索":
            task.pop("sections", None)
            task.pop("result", None)
        if version:
            task["version"] = version[1].upper()
            task.pop("result", None)
    elif "剩余工期" in message:
        project = PROJECT.search(message)
        keyword = re.sub(r"^(?:请)?(?:按|根据|计算)", "", project[1]) if project else ""
        if not keyword:
            return {"answer": "请指定项目。", "calls": []}
        task = new_task(keyword)
    save_task(user_id, task)
    return workflow.invoke({"user_id": user_id, "task": task, "steps": 0, "calls": []})
