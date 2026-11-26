"""Execute validated registered tools; retain legacy single-call result format."""
from src.tools.registry import TOOL_REGISTRY
import sqlite3

MAX_TOOL_CALLS = 8


def tool_executor(state):
    if state.get("plan") is not None:
        return execute_plan_step(state)
    calls = state.get("tool_calls")
    if calls is None:
        name = state.get("tool_name", "")
        if not name:
            return {"tool_called": False, "tool_result": ""}
        calls = [{"name": name, "args": state.get("tool_args", {})}]
    if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_TOOL_CALLS:
        return {"tool_called": True, "tool_result": "工具执行失败:每轮需1到8个工具调用"}
    results = []
    for call in calls:
        from src.agent.execution import check_budget
        check_budget()
        try:
            if not isinstance(call, dict) or set(call) != {"name", "args"} or not isinstance(call["args"], dict):
                raise ValueError("工具调用参数格式错误")
            name = call["name"]
            if not isinstance(name, str) or name not in TOOL_REGISTRY:
                raise ValueError("工具不存在")
            result = TOOL_REGISTRY[name].invoke(call["args"])
            results.append({"name": name, "result": result})
            if isinstance(result, dict) and (result.get("success") is False or "error" in result):
                break
        except sqlite3.Error:
            raise
        except Exception:
            results.append({"name": call.get("name", "") if isinstance(call, dict) else "", "error": "工具执行失败：名称、参数或工具运行异常"})
            break  # Do not execute later steps after a failed prerequisite.
    if len(calls) == 1:
        item = results[0]
        text = str(item["result"]) if "result" in item else item["error"]
    else:
        text = str(results)
    return {"tool_called": True, "tool_result": text}


def execute_plan_step(state):
    """Execute one step per graph turn; resolve only validated numeric references."""
    from src.agent.execution import check_budget
    check_budget()
    import json
    import math
    from uuid import uuid4
    from langchain_core.messages import AIMessage, ToolMessage
    from src.agent.planner import TaskPlan, REFERENCE, MAX_PLAN_STEPS
    from src.server.coordination import check_lease

    records = list(state.get("execution_records", []))
    messages = list(state.get("execution_messages", []))
    index = state.get("plan_index", 0)
    error = ""
    try:
        plan = TaskPlan.model_validate(state["plan"])
        if plan.action != "execute" or not 0 <= index < min(len(plan.steps), MAX_PLAN_STEPS):
            raise ValueError("执行步数或计划无效")
        step = plan.steps[index]
        completed = {r["id"]: r for r in records if r.get("status") == "completed"}
        if not set(step.depends_on) <= set(completed):
            raise ValueError("前置任务尚未成功")
        args = {}
        for key, value in step.args.items():
            def replace(match):
                prior = completed[match[1]]
                result = prior["result"]
                number = result.get("result") if isinstance(result, dict) else result
                if isinstance(number, bool) or not isinstance(number, (int, float)) or abs(number) > 1e100 or not math.isfinite(number):
                    raise ValueError("引用不是有限数值")
                return "(" + str(number) + ")"
            args[key] = REFERENCE.sub(replace, value)
        tool = TOOL_REGISTRY[step.tool]
        tool.args_schema.model_validate(args)
        check_lease()
    except ValueError:
        error = "计划或参数校验失败，未继续执行工具。"
        steps = (state.get("plan") or {}).get("steps", [])
        if 0 <= index < len(steps):
            records.append({"id": steps[index].get("id", ""), "tool":steps[index].get('tool',''), "status": "failed_validation", "error": error})
            records.extend({"id": s.get("id", ""), "tool":s.get('tool',''), "status": "skipped", "reason": "先前步骤校验失败"} for s in steps[index + 1:])
        return {"execution_error": error, "execution_records": records,
                "execution_messages": messages, "tool_called": True, "tool_result": str(records) if records else error}

    call_id = uuid4().hex
    messages.append(AIMessage(content="", tool_calls=[{"name": step.tool, "args": args, "id": call_id, "type": "tool_call"}]))
    try:
        result = tool.invoke(args)
        failed = isinstance(result, dict) and (result.get("success") is False or "error" in result)
        status = "failed" if failed else "completed"
        if failed:
            reason = result.get("error", "工具未返回成功结果")
            detail = str(reason).replace("\n", " ")[:120] if step.tool == "calculator" else "工具未返回成功结果"
            error = f"步骤{step.id}（{step.tool}）工具执行失败：{detail}；后续步骤未执行。"
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        records.append({"id": step.id, "order": step.order, "tool": step.tool,
                        "args": args, "depends_on": step.depends_on, "status": status, "result": result,
                        "source_message_id":state.get('source_message_id')})
        messages.append(ToolMessage(content=payload, tool_call_id=call_id,
                                    name=step.tool, status="error" if failed else "success"))
    except sqlite3.Error:
        raise
    except Exception:
        error = f"步骤{step.id}工具运行异常，后续步骤未执行。"
        records.append({"id": step.id, "order": step.order, "tool": step.tool,
                        "args": args, "depends_on": step.depends_on, "status": "failed", "error": error})
        messages.append(ToolMessage(content=error, tool_call_id=call_id, name=step.tool, status="error"))
    check_lease()  # A lost lease must propagate before LangGraph persists this step.
    if error:
        records.extend({"id": s.id, "order": s.order, "tool": s.tool, "status": "skipped",
                        "reason": "先前步骤失败"} for s in plan.steps[index + 1:])
    return {"plan_index": index + 1, "execution_records": records, "execution_messages": messages,
            "execution_error": error, "tool_called": True, "tool_name": step.tool,
            "tool_args": args, "tool_result": str(records[0]["result"]) if len(records) == 1 and "result" in records[0] else str(records)}
