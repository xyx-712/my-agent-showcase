import re


EXPRESSION = re.compile(
    r"(?<![\w.])(?:[0-9]{1,6}(?:\.[0-9]{1,6})?|\()"
    r"[0-9 .()+*/×÷加减乘除以去-]{0,62}[0-9)](?![\w.])",
    re.ASCII,
)


def tool_router(state, llm):
    if llm is not None:
        from src.agent.planner import plan_task
        from src.agent.context import ContextBudgetError
        from httpx import HTTPError
        from ollama import ResponseError
        try:
            files = []
            if state.get('user_id') and state.get('mode') != 'chat':
                from src.server.documents import documents
                files = [{'id':d['id'], 'name':d['name']} for d in documents(state['user_id'])]
            from src.agent.history_summary import live as live_summary
            prior_records=state.get('execution_records')
            if state.get('source_message_id') is not None and prior_records:
                # A document turn can bypass the main graph and leave old numeric
                # records in its checkpoint. Reuse only the actual previous turn.
                preceding=[m for m in state.get('messages',[])[:-1] if m.type=='human']
                source=prior_records[-1].get('source_message_id')
                if not preceding or source is None or str(source)!=preceding[-1].id:prior_records=[]
            plan = plan_task(llm, state.get("messages", []), files,
                             history_summary=live_summary(state.get('user_id'),state.get('history_summary')),
                             previous_records=prior_records)
            if state.get('mode') == 'chat' and plan.action in {'knowledge', 'document'}:
                from src.agent.planner import TaskPlan
                plan = TaskPlan(action='chat', steps=[], question='')
            return {"plan": plan.model_dump(), "need_tool": plan.action == "execute",
                    "tool_name": plan.steps[0].tool if plan.steps else "", "tool_args": {}}
        except ContextBudgetError as error:
            return {'need_tool':False,'tool_name':'','tool_args':{},'plan':None,'plan_error':str(error)}
        except (ValueError, HTTPError, ResponseError, ConnectionError, TimeoutError):
            return {"need_tool": False, "tool_name": "", "tool_args": {}, "plan": None,
                    "plan_error": "任务规划未通过校验或模型暂不可用，未执行任何工具。请明确任务和参数后重试（最多8步）。"}
    messages = state.get("messages", [])
    text = messages[-1].content if messages else ""
    profile_questions = ("我叫什么", "我是谁", "我的名字", "我的兴趣", "我的爱好", "我的工作", "我的职业")
    matches = [] if any(question in text for question in profile_questions) else list(EXPRESSION.finditer(text))
    matches = [m for m in matches if re.search(r"[+*/×÷加减乘除-]", m[0])]
    if len(matches) > 1:
        return {"need_tool": True, "tool_name": "calculator", "tool_args": {},
                "tool_calls": [{"name": "calculator", "args": {"expression": m[0]}} for m in matches[:9]]}
    match = matches[0] if matches else None
    if match:
        expression = match[0]
        if re.search(r"[+*/×÷加减乘除-]", expression):
            return {"need_tool": True, "tool_name": "calculator",
                    "tool_args": {"expression": expression}}
    return {"need_tool": False, "tool_name": "", "tool_args": {}}
