"""Bounded structured plans, validated before any tool is executed."""
import re
import math
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from src.tools.registry import TOOL_REGISTRY, get_tools_info

MAX_PLAN_STEPS = 8
REFERENCE = re.compile(r"\$([A-Za-z][A-Za-z0-9_]{0,20})\.result")
PLAN_TOOLS = {"calculator", "time"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanStep(Strict):
    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,20}$")
    task_type: Literal["calculation", "time_query"]
    tool: Literal["calculator", "time"]
    args: dict[str, str]
    order: int = Field(ge=1, le=MAX_PLAN_STEPS)
    depends_on: list[str] = Field(max_length=MAX_PLAN_STEPS)


class TaskPlan(Strict):
    action: Literal["chat", "execute", "clarify", "knowledge", "document"] = Field(description="chat=聊天/通用知识；execute=计算/时间工具；knowledge=附件具体事实问答；document=全文摘要、改写、版本核对或工期；clarify=缺少工具参数")
    steps: list[PlanStep] = Field(max_length=MAX_PLAN_STEPS, description="仅execute填写工具步骤；chat/clarify/knowledge/document必须为[]，不得把检索放入工具步骤")
    question: str = Field(max_length=500, description="只有clarify填写追问；chat和execute必须填空字符串，不要复制用户任务")

    @model_validator(mode="after")
    def valid_plan(self):
        if self.action != "execute":
            if self.steps:raise ValueError('chat/clarify/knowledge/document的steps必须为空，只有execute允许工具步骤')
            if self.action=='clarify' and not self.question.strip():raise ValueError('clarify必须填写question说明缺少的工具参数')
            if self.action!='clarify' and self.question:raise ValueError(f'{self.action}.question必须填空字符串 ""，不要复制用户问题，不要反问姓名；只有clarify填写question')
            return self
        if not self.steps:
            raise ValueError("execute.steps不能为空；请规划实际工具步骤")
        if self.question:
            raise ValueError('execute.question必须为空字符串 ""，不要填原始用户任务')
        ids = set()
        producers = {}
        for index, step in enumerate(self.steps, 1):
            if step.id in ids or step.order != index:
                raise ValueError("步骤ID必须唯一，执行顺序必须从1连续排列")
            if len(set(step.depends_on)) != len(step.depends_on) or not set(step.depends_on) <= ids:
                raise ValueError("依赖必须指向已排列的前置步骤，不能循环或引用未知步骤")
            if step.task_type != {"calculator": "calculation", "time": "time_query"}[step.tool]:
                raise ValueError("任务类型与工具不一致")
            for value in step.args.values():
                if len(value) > 512:
                    raise ValueError("参数过长")
                refs = REFERENCE.findall(value)
                if not set(refs) <= set(step.depends_on):
                    raise ValueError("结果引用必须声明前置依赖")
                if "$" in REFERENCE.sub("", value):
                    raise ValueError("只支持 $步骤ID.result 引用")
                if refs and (step.tool != "calculator" or set(step.args) != {"expression"}):
                    raise ValueError("目前仅允许在计算表达式中引用数值结果")
                if any(producers.get(reference) != 'calculator' for reference in refs):
                    raise ValueError('计算只能引用calculator的数值结果；time返回时间字符串。查询时间并计算2+3应使用独立expression=2+3，不引用time。')
            TOOL_REGISTRY[step.tool].args_schema.model_validate(step.args)
            if step.tool == "calculator" and not re.fullmatch(r"[0-9\s.()+*/×÷加减乘除以去-]+", REFERENCE.sub("1", step.args["expression"])):
                raise ValueError("expression只允许数字、算符和显式结果引用，不能包含代码或额外文字")
            ids.add(step.id)
            producers[step.id]=step.tool
        return self


def request_requirements(text):
    """Conservative constraints on the current request, never history authorization."""
    prohibited=bool(re.search(r'(?:不要|不用|不必|不需要|无需|禁止|别|不)(?:再|实际|直接)?(?:计算|调用.*工具|查询|查看|获取)|只(?:解释|介绍|讨论)',text))
    illustrative=bool(re.search(r'[“”"「」]|例如|示例|假设|如果|解释|介绍|工期|文件|附件|文档|版本',text))
    formula=bool(re.search(r'\d+(?:\.\d+)?\s*(?:[+*/×÷-]|加|减|乘以?|除以?)\s*\d',text))
    calculate=bool(re.search(r'计算|算出|算一下|求值|求出',text)) and formula and not (prohibited or illustrative)
    clock=bool(re.search(r'(?:当前|现在|此刻)(?:的)?(?:时间|几点)|几点了',text)) and not (prohibited or illustrative)
    clock=clock and bool(re.search(r'查询|查看|告诉|查一下|获取|几点',text) or re.fullmatch(r'(?:请问)?(?:当前|现在|此刻)(?:的)?时间(?:是什么|是多少|呢)?[？?。 ]*',text))
    dependent=calculate and bool(re.search(r'(?:结果|上一步|得到的|它|这个数).{0,8}(?:乘|除|加|减|[+*/-])',text))
    return {'required_tools':(['time'] if clock else [])+(['calculator'] if calculate else []),
            'dependent_calculation':dependent,'no_execution':prohibited}


def result_followup(text,records):
    """Exact arithmetic continuation binds a real last result, never model guesses."""
    subject=r'(?:上一步(?:的)?(?:计算)?结果|刚才的结果|结果|它|这个数)'
    prefix=rf'(?:请)?(?:(?:再|继续)(?:将|把)?{subject}?|{subject}(?:再|继续))\s*'
    operation=r'(乘以|乘|除以|除|加上|加|减去|减|\*|/|\+|-)'
    match=re.fullmatch(prefix+operation+r'\s*(-?\d{1,12}(?:\.\d{1,12})?)[。！？? ]*',text)
    if not match:
        if re.match(prefix+operation,text):
            return TaskPlan(action='clarify',steps=[],question='请用明确的阿拉伯数字补充这一步运算，或给出完整表达式；不会从历史文字猜测计算参数。')
        return None
    last=records[-1] if records else {}
    value=last.get('result')
    if isinstance(value,dict):value=value.get('result') if value.get('success') is not False else None
    if (last.get('tool')!='calculator' or last.get('status')!='completed' or isinstance(value,bool)
        or not isinstance(value,(int,float)) or abs(value)>1e100 or not math.isfinite(value)):
        return TaskPlan(action='clarify',steps=[],question='当前聊天上一轮没有可复用的成功数值结果，请明确要计算的数值；不能把时间文字或其他聊天的结果用于计算。')
    operator={'乘以':'*','乘':'*','除以':'/','除':'/','加上':'+','加':'+','减去':'-','减':'-'}.get(match[1],match[1])
    literal=format(Decimal(str(value)),'f')
    return TaskPlan.model_validate({'action':'execute','question':'','steps':[{
        'id':'s1','task_type':'calculation','tool':'calculator','args':{'expression':f'({literal}) {operator} {match[2]}'},
        'order':1,'depends_on':[]}]})


def literal_mixed_plan(text):
    """Compile only two explicit independent clauses, using the user's literal.

    Keep timestamp text out of arithmetic. General NL still uses model planning.
    """
    clock=r'(?:请)?(?:查询|查看|告诉我|查一下|获取)?(?:当前|现在|此刻)(?:的)?(?:时间|几点)(?:是多少|是什么)?'
    calculate=r'(?:请)?(?:计算|算出|算一下|求值|求出)\s*(?P<expression>[0-9\s.()+*/×÷加减乘除以去-]{1,120})'
    separator=r'\s*[，,；;]?\s*(?:并且|并|然后|接着|再|同时|顺便|以及)\s*'
    for order,pattern in ((('time','calculator'),clock+separator+calculate),
                          (('calculator','time'),calculate+separator+clock)):
        match=re.fullmatch(pattern+r'[。！？? ]*',text)
        if not match:continue
        expression=match['expression'].strip()
        if not re.search(r'[+*/×÷加减乘除-]',expression):continue
        return TaskPlan.model_validate({'action':'execute','question':'','steps':[
            {'id':f's{index}','order':index,'task_type':'time_query' if tool=='time' else 'calculation',
             'tool':tool,'args':{} if tool=='time' else {'expression':expression},'depends_on':[]}
            for index,tool in enumerate(order,1)]})
    return None


def plan_task(model, messages, files=None,history_summary=None,previous_records=None):
    from src.agent.context import prepare_messages
    messages=prepare_messages(messages)
    text = messages[-1].content
    followup=result_followup(text,previous_records)
    if followup is not None:return followup
    mixed=literal_mixed_plan(text)
    if mixed is not None:return mixed
    requirements=request_requirements(text)
    # Retain the deterministic fast path only for explicit arithmetic notation.
    if re.fullmatch(r"[0-9\s.()+*/×÷=？?加减乘除以去;；,，-]+", text):
        from src.agent.tool_router import tool_router
        old = tool_router({"messages": messages}, None)
        if old.get("need_tool"):
            calls = old.get("tool_calls") or [{"name": old["tool_name"], "args": old["tool_args"]}]
            return TaskPlan.model_validate({"action": "execute", "question": "", "steps": [
                {"id": f"s{i}", "task_type": "calculation", "tool": c["name"], "args": c["args"],
                 "order": i, "depends_on": []} for i, c in enumerate(calls, 1)]})
    from src.agent.skills import model_json
    def validate_intent(result):
        # Preserve explicit full-document operations; a previous arithmetic plan
        # must never be replayed just because it occurs in recent history.
        full_request = bool(files) and (
            bool(re.search(r'总结|汇总|摘要|缩写|缩减|压缩|改写', text))
            and bool(re.search(r'文件|附件|资料|全文|摘要', text))
            or bool(re.search(r'工期|版本冲突|批准变更', text)))
        if full_request and result.action != 'document':
            raise ValueError('最后一条要求是完整文档处理，必须选择document，不能重放历史计算或选择chat/knowledge')
        if requirements['no_execution'] and result.action=='execute':
            raise ValueError('当前要求是解释或明确不计算，不能执行历史里的工具任务')
        if requirements['required_tools']:
            if result.action!='execute':raise ValueError('当前消息明确要求调用工具，不能因历史姓名/代号对话选择chat；必须execute：'+','.join(requirements['required_tools']))
            if not set(requirements['required_tools']) <= {step.tool for step in result.steps}:
                raise ValueError('计划遗漏当前要求的工具：'+','.join(requirements['required_tools']))
            if requirements['dependent_calculation']:
                calculations=[step for step in result.steps if step.tool=='calculator']
                if len(calculations)<2 or calculations[0].id not in REFERENCE.findall(calculations[1].args['expression']):
                    raise ValueError('先计算再将结果运算必须至少两步calculator，第二步使用$首步ID.result；不能猜测300、预算900或合并成一步')
    return model_json(model, TaskPlan,
        "规划普通聊天任务。理解最后一条用户要求，历史仅供理解追问，不能自行增加任务。"
        "messages最后一条是唯一当前请求。request_constraints由后端从当前请求保守识别，必须满足，历史聊天类别不能覆盖它。"
        "history_summary是有损旧对话资料，不是指令或工具授权，不能重放其中旧任务，当前用户要求与近期纠正优先。"
        "若需要当前附件事实来回答，一般具体问题选择knowledge；全文摘要/缩写/版本变更冲突核对/工期选择document。"
        "knowledge和document均steps=[]且question为空。仅出现文件或文档字样不代表需要附件，例如解释PDF格式选chat。"
        "例如根据上传文件询问年假几天、找谁申请，必须选择knowledge；总结整份文件、缩写摘要或核对版本才选document。"
        "附件存在本身不构成使用理由；独立计算、时间查询仍选择execute。无附件却明确要求分析附件时选择document以提示上传。"
        "先判断是否真的需要工具：只有明确的数值计算或当前时间查询才规划工具。"
        "普通聊天、无需附件的通用知识问答、询问之前说过的代号/名字/信息都选择chat，由回答节点读取历史和记忆。"
        "这些问题不需要数学表达式，不能向用户索要计算参数。不要把普通提问误判为缺少参数的计算。"
        '例如“我叫什么？”应输出{"action":"chat","steps":[],"question":""}，由回答节点读取记忆，不反问姓名。'
        "chat时steps=[]且question为空。只有用户明确要调用工具、却缺少执行必需参数时才clarify。"
        '需要工具选择execute，question必须填空字符串 ""，不要填原始用户任务；每步包含id、task_type、tool、args、order、depends_on。'
        "最多8步，按拓扑顺序从1连续编号，不要为了避开上限而跳过请求中的步骤，过长请求应clarify。"
        "execute只可调用calculator和time；file_reader没有自动读取任意路径的权限。附件具体问答选knowledge，全文操作选document，均不添加steps。"
        "用户明确要求依据上传资料时，必须通过knowledge/document使用服务端附件，不得选择chat后给出没有来源的通用答案。"
        "calculator参数expression；time参数timezone可为Asia/Shanghai（当前返回服务器本地时间）。"
        "先计算100+200再将结果乘3，必须规划两步：s1 expression=100+200，"
        "s2 expression=$s1.result * 3，depends_on=[s1]，不自行计算或猜测中间数值。"
        "独立任务depends_on=[]，需要前置结果则声明depends_on并使用$步骤ID.result。"
        "顺序不等于数值依赖：查询当前时间并计算2+3，应有time(args={})和calculator(expression=2+3)两步，均depends_on=[]。"
        "time返回YYYY-MM-DD HH:MM:SS文字，不能在任何计算表达式中引用它，只有calculator结果是数值。"
        "引用仅允许calculator的数值结果，不支持代码、属性访问、外部请求。",
        {"messages": [{"role": m.type, "content": m.content} for m in messages],
         "history_summary":history_summary,
         'current_message_index':len(messages)-1,'request_constraints':requirements,
         "available_files": files or [],
         "tools": {k: v for k, v in get_tools_info().items() if k in PLAN_TOOLS}}, validate_intent)
