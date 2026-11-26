from src.config import debug_print
import sqlite3


from src.config import CHECKPOINT_DB


from langgraph.graph import (
    StateGraph,
    START,
    END
)


from langgraph.checkpoint.sqlite import SqliteSaver


from langchain_core.messages import (
    AIMessage
)


from src.agent.model_provider import get_chat_model
from src.agent.execution import budgeted_step, invoke_model
from src.prompts.agent_prompt import CHAT_PROMPT, TOOL_RESULT_PROMPT


from src.agent.state import AgentState


from src.agent.history_node import history_node


from src.agent.memory_node import memory_extractor_node


from src.agent.tool_router import tool_router


from src.agent.tool_executor import tool_executor


# =====================================================
# 长期记忆数据库
# =====================================================

from src.memory.store import memory_store


# =====================================================
# ENV
# =====================================================



# =====================================================
# LLM
# =====================================================

llm = get_chat_model()


# =====================================================
# Format Memory
# =====================================================

def format_memory(memory):


    if not memory:

        return "无"


    result = []


    for item in memory:


        if isinstance(item, dict):


            key = item.get(
                "key",
                ""
            )


            value = item.get(
                "value",
                ""
            )


            if key and value:

                result.append(

                    f"{key}: {value}"

                )


    return "\n".join(result)


# =====================================================
# Agent Node
# =====================================================

def agent_node(state):
    plan = state.get("plan") or {}
    error = state.get("plan_error") or state.get("execution_error")
    if error or plan.get("action") == "clarify":
        return {"response": error or plan["question"], "step": "finished"}
    records = state.get("execution_records", [])
    if plan.get('action')=='chat' and any(item['status']=='deleted_barrier' for item in state.get('memory_outcomes',[])):
        return {'response':'该信息已删除，本次没有重新保存。若确实需要恢复，请明确使用“重新记住…”；缺少删除来源的旧记录还需要匹配修订版本。','step':'finished'}
    if plan.get('action')=='chat' and any(item['status'] in {'candidate','duplicate_candidate'} for item in state.get('memory_outcomes',[])):
        return {'response':'新信息存在冲突或尚未确认，原有记忆未被覆盖。请用“更正，我的名字是…”或“更正，我的职业是…”等明确陈述确认。','step':'finished'}
    if records and all(r.get("status") == "completed" and r["tool"] == "calculator" for r in records):
        lines = [f'{r["args"]["expression"]} = {r["result"]["result"]}' for r in records]
        return {"response": "计算结果：" + str(records[-1]["result"]["result"]) + "。\n过程：" + "；".join(lines), "step": "finished"}


    messages = state.get(

        "messages",

        []

    )


    # =================================================
    # 获取 user_id
    # =================================================

    user_id = state.get(

        "user_id",

        "default"

    )


    # =================================================
    # 关键修复
    #
    # 不再完全相信 checkpoint 中的 state["memory"]
    #
    # 每次回答之前，直接从 SQLite memory.db
    # 重新读取最新长期记忆
    # =================================================

    current_rows = memory_store.search(

        user_id

    )


    current_memory = []


    for key, value in current_rows:


        current_memory.append(

            {

                "key": key,

                "value": value

            }

        )


    memory = format_memory(

        current_memory

    )


    # =================================================
    # 工具信息
    # =================================================

    tool_name = state.get(

        "tool_name",

        ""

    )


    tool_result = state.get(

        "tool_result",

        ""

    )


    # =================================================
    # System Prompt
    # =================================================

    from src.agent.context import chat, ContextBudgetError
    execution_messages = state.get('execution_messages', [])
    from src.agent.history_summary import live as live_summary
    historical=live_summary(user_id,state.get('history_summary'))
    try:
        input_messages = chat(messages,memory=current_memory,tool_name='' if execution_messages else tool_name,
                              tool_result=tool_result,execution_messages=execution_messages,
                              task_context={'memory_notices':state['memory_notes']} if state.get('memory_notes') else None,
                              history_summary=historical)
    except ContextBudgetError as error:
        return {'response':str(error),'step':'finished'}

    from src.agent.context import bounded_model
    result = invoke_model(bounded_model(llm),

        input_messages

    )


    from src.server.coordination import check_lease
    check_lease()
    response = result.content


    # =================================================
    # DEBUG
    # =================================================

    debug_print()

    debug_print(

        "===== AGENT MEMORY ====="

    )


    debug_print(

        "USER ID:",

        user_id

    )


    debug_print(

        "CURRENT MEMORY:",

        current_memory

    )


    debug_print(

        "========================"

    )


    # =================================================
    # Return
    # =================================================

    return {

        "messages": [

            AIMessage(

                content=response

            )

        ],


        "response":

            response,


        "memory":

            current_memory,


        "step":

            "finished"

    }


# =====================================================
# Planner
# =====================================================

def planner_node(state):


    result = tool_router(state, llm)
    return {**result, "tool_called": False, "tool_result": "", "tool_calls": None,
            "citations": [], "task": {}, "document_calls": [],
            "plan_error": result.get("plan_error", ""), "plan_index": 0,
            "execution_records": [], "execution_messages": [], "execution_error": ""}



# =====================================================
# Router
# =====================================================

def route_tool(state):
    if not state.get('plan_error') and (state.get('plan') or {}).get('action') in {'knowledge', 'document'}:
        return (state['plan']['action'])


    if (

        state.get(

            "need_tool",

            False

        )

        and not state.get(

            "tool_called",

            False

        )

    ):

        return "tool"


    return "agent"


# =====================================================
# Build Graph
# =====================================================

builder = StateGraph(

    AgentState

)


# =====================================================
# History
# =====================================================

builder.add_node(

    "history",

    budgeted_step(history_node)

)


# =====================================================
# Memory
# =====================================================

builder.add_node(

    "memory",

    budgeted_step(memory_extractor_node)

)


# =====================================================
# Planner
# =====================================================

builder.add_node(

    "planner",

    budgeted_step(planner_node)

)


# =====================================================
# Tool
# =====================================================

builder.add_node(

    "tool",

    budgeted_step(tool_executor)

)


# =====================================================
# Agent
# =====================================================

builder.add_node(

    "agent",

    budgeted_step(agent_node)

)


# =====================================================
# Flow
# =====================================================

builder.add_edge(

    START,

    "history"

)


builder.add_edge(

    "history",

    "memory"

)


builder.add_edge(

    "memory",

    "planner"

)


# =====================================================
# Planner -> Tool / Agent
# =====================================================

def document_node(state):
    from src.agent.document_agent import document_turn
    result = document_turn(state['messages'], llm, state['user_id'], 'documents',
                           state.get('calendar'), state.get('task_id'))
    return {'response':result['answer'], 'citations':result.get('citations', []),
            'task':result.get('task', {}), 'document_calls':result.get('calls', []),
            'step':'finished'}


builder.add_node('knowledge', budgeted_step(document_node))
builder.add_node('document', budgeted_step(document_node))
builder.add_edge('knowledge', END)
builder.add_edge('document', END)

builder.add_conditional_edges(

    "planner",

    route_tool,

    {
        "knowledge": "knowledge",
        "document": "document",

        "tool":

            "tool",

        "agent":

            "agent"

    }

)


# =====================================================
# Tool -> Tool / Agent
# =====================================================

def route_after_tool(state):
    plan = state.get("plan") or {}
    if plan.get("action") == "execute" and not state.get("execution_error") and state.get("plan_index", 0) < len(plan.get("steps", [])):
        return "tool"
    return "agent"


builder.add_conditional_edges("tool", route_after_tool, {"tool": "tool", "agent": "agent"})


# =====================================================
# Agent -> END
# =====================================================

builder.add_edge(

    "agent",

    END

)


# =====================================================
# Checkpoint
# =====================================================

conn = sqlite3.connect(

    CHECKPOINT_DB,

    check_same_thread=False

)


checkpointer = SqliteSaver(

    conn

)


# =====================================================
# Compile
# =====================================================

graph = builder.compile(

    checkpointer=checkpointer

)
