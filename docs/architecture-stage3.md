# 第三阶段：结构化Planner与依赖工具执行

验收日期：2026-11-24。承接第一、第二阶段未提交修改，本阶段不提交或推送Git。

## 本阶段修改清单

业务代码修改：
- src/agent/planner.py：将未接入且导入失效的旧规划器升级为真实使用的Pydantic任务计划。
- src/agent/tool_router.py：模型规划与原算式快路径的适配；规划错误不执行工具。
- src/agent/tool_executor.py：每次执行一个计划步骤、结果引用解析、记录和ToolMessage。
- src/agent/state.py：增加计划、索引、执行记录、工具消息和错误字段；不修改数据库表。
- src/agent/graph.py：复用原节点，增加tool自循环与条件退出；确定性计算结果及错误回答。

测试修改：tests/attachment_evaluation.py（共享替身支持规划输出）、tests/auth_evaluation.py、tests/auth_browser_evaluation.py（聊天替身支持新增规划调用）、tests/model_prompt_evaluation.py（验证算式结果而非旧system工具提示）。

新增：tests/test_planner.py、tests/planner_evaluation.py、本记录。更新：README.md、docs/local-evaluation.md。model_provider、skills、prompts、registry等工作区文件仍包含前两阶段未提交成果，不是本阶段重新开发。

## 工作原理

Planner通过第一阶段统一模型与结构化模板生成TaskPlan，action为chat、execute或clarify。PlanStep包含id、task_type、tool、args、order、depends_on。模型输出与业务参数均严格校验，最多两次格式尝试。

普通自然语言由模型理解，不再只提取出现的算式。只有完全由算式符号构成的输入保留原确定性快路径，避免简单计算多余模型调用。

先计算100+200再乘3的计划形式：

```json
{"action":"execute","question":"","steps":[
 {"id":"s1","task_type":"calculation","tool":"calculator","args":{"expression":"100+200"},"order":1,"depends_on":[]},
 {"id":"s2","task_type":"calculation","tool":"calculator","args":{"expression":"$s1.result * 3"},"order":2,"depends_on":["s1"]}
]}
```

后端先验证ID唯一、顺序连续、依赖只指向前面的已声明步骤、引用与依赖一致、工具允许及参数schema。禁止循环、未来/未知引用、额外字段、代码和任意属性访问。执行器取得s1实际返回的300，将第二步变为(300)*3，而不是让模型猜测中间值。

## LangGraph与消息流

```text
history → memory → planner
                     ├─ chat/clarify/规划错误 → agent → END
                     └─ execute → tool（单步骤）
                                     ├─ 尚有步骤且无错误 → tool
                                     └─ 完成或失败 → agent → END
```

没有创建另一套Agent。保留原StateGraph、history/memory/planner/tool/agent节点与SQLite checkpoint。每轮最多8个工具步骤，循环只推进计划索引，不允许模型在执行时无限增加步骤；9步计划在执行前拒绝。独立任务也按给定拓扑顺序执行，不做并行。

每步追加成对AIMessage(tool_calls)与ToolMessage，tool_call_id一致；工具内容不再作为高权限system消息传入普通回答节点。执行结果和记录经现有tool_result接口字段返回，结构化记录及消息同时存入现有checkpoint。没有新增API或React界面。

纯计算的最终结果由真实工具返回值与已解析公式直接组成，避免回答模型重新计算或编造。混合工具任务使用原Agent模型结合标准工具消息回答。原第二阶段执行器接口仍可供直接内部调用。

失败步骤记录failed或failed_validation，之后的步骤标为skipped并终止，不继续执行独立分支。计算器除零等原因明确返回，未知运行异常不泄露内部异常详情。工具执行前后检查现有身份租约。新请求会清空上一轮计划/工具状态，防止checkpoint中的旧工具继续执行。

## 安全与兼容

模型自动规划白名单为calculator、time。file_reader没有删除，标准工具和原函数保持，但仍仅供显式授权内部调用；不会让模型生成任意路径并读取本机文件。附件分析继续走原身份校验和文档工作流，不改RAG或文件接口。

引用传递当前仅支持calculator表达式中的$步骤ID.result，要求前置步骤成功且结果是有限数值（绝对值不超过1e100）。不支持传入任意Python代码、工具文本转代码或任意字段/对象路径。模型输出的数值与任务语义仍需评测，结构校验本身不能证明语义完全正确。

长期记忆提取/存储、数据库结构、FastAPI和React均未修改，无新增依赖。旧checkpoint由Planner每轮初始化新字段；原附件任务恢复行为保持。

## 基线与测试

改造前：单元16/16通过（1.928秒）、model_prompt_evaluation和chat_routing_evaluation通过。

改造后实际通过：

| 测试 | 结果 |
| --- | --- |
| unittest discover | 21/21；新增5组Planner契约测试 |
| planner_evaluation | 实际FastAPI与主图：单工具、两个独立任务、三步依赖、300→900、时间+计算、参数错误、除零失败/跳过、8步完成/9步拒绝、追问、普通聊天、逐轮状态重置、身份隔离 |
| 工具消息校验 | 成对AI/ToolMessage、调用ID对应、通过checkpoint读取记录，混合回答不将实际工具内容塞入system消息 |
| model_prompt_evaluation | 第一阶段模型注入、角色/上下文/当前消息一次、第二阶段多算式与清理、结构化有限重试，通过 |
| local_evaluation | 附件、引用、两阶段15→20、提示注入、计算失败与独立进程恢复，通过 |
| abstract_evaluation | 摘要缩写、引用拒绝、分批失败/独立进程续跑，通过 |
| network_evaluation / advanced_evaluation | 多阶段工期、综合摘要、多任务切换与暂停，通过 |
| chat_routing_evaluation | 上传后普通聊天、独立计算和附件任务保留，通过 |
| auth_evaluation / account_management_evaluation | 认证隔离、令牌、迁移回滚与账号管理，通过；邮件为替身 |
| concurrency_backup_evaluation | 身份租约、去重、备份恢复及恢复后续算，通过 |
| auth_browser_evaluation | Edge隔离浏览器注册/上传/聊天/退出/登录/刷新/延迟响应/过期草稿回归通过 |
| multiworker_evaluation | 两个真实Uvicorn worker（PID23200、28140）共享身份/历史/checkpoint/附件任务通过，模型为替身 |
| 前端lint/build | 通过，生产构建112ms；未修改前端源码 |

真实本机Ollama qwen2.5:7b，临时数据库与虚构消息：

- 最终planner_evaluation --ollama：依赖计算300→900通过，8.275秒；额外断言原始计划确有结果占位符和前置依赖，不是直接让模型输出900。
- 时间与计算混合调用、标准ToolMessage回答通过，7.545秒。
- 普通问候未调用工具，通过，8.066秒。
- 第一阶段真实两轮上下文回忆通过，12.364秒，正确回忆虚构代号“蓝杉”。

开发中保留两类实际失败：模型最初把原需求填入execute.question导致拒绝执行；曾把代号回忆误判为缺少计算参数。补充字段描述、具体校验反馈和chat优先意图说明后，相关真实复验通过。没有通过放宽依赖校验、硬编码900或无限重试掩盖失败。

测试全部使用虚构资料与临时数据库，未读取个人附件、迁移/恢复真实用户库或创建公网入口。

## 启动和复现

无需安装新依赖或迁移数据库。停止旧后端，按README原命令重新启动。在聊天页面选择“自由聊天”，发送“先计算100+200，再将结果乘以3。”，预期：

```text
计算结果：900。
过程：100+200 = 300；(300) * 3 = 900
```

发送“查询当前时间，并计算2+3。”可验证不同工具。time仍是服务器本地时间，timezone参数不做时区转换。

自动验收：

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.planner_evaluation
.\.venv\Scripts\python.exe -X utf8 -m tests.planner_evaluation --ollama
.\.venv\Scripts\python.exe -X utf8 -m tests.model_prompt_evaluation --ollama
```

真实模型测试要求Ollama运行且有qwen2.5:7b。

## 当前边界与下一阶段

计划一次生成，按静态依赖顺序执行；不支持基于运行结果动态增加/重规划工具步骤。普通聊天会多一次模型意图规划调用，因此延迟可能增加。模型语义理解仍可能失败，并非任意自然语言100%成功。

步骤记录保存在checkpoint和现有tool_result，不新增执行记录可视化页面。通用规划的中断没有新增恢复API，用户新消息会重新规划；不承诺工具副作用exactly-once。当前自动工具仅计算与读时间，原附件任务恢复另行保持。失败时保守停止整条计划，独立分支也不继续。

本轮未复跑真实个人PDF、OCR或SMTP；历史真实两阶段模型的其他失败记录不因本轮测试而删除。没有开发语义RAG。确认后第四阶段再围绕本地Retriever/索引/语义检索单独实施。
