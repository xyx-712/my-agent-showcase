# 第五阶段遗留问题修复验收

日期：2026-11-24。沿用现有LangChain + LangGraph；未改数据库结构、API请求/响应JSON字段、前端、身份或资料权限。没有新增依赖，没有提交或推送Git。

## 根因与修改

### 带历史的计算被当聊天

复现了“姓名/代号聊天后，先计算100+200，再将结果乘以3”被规划为chat。此前缺少对**当前明确请求是否被计划覆盖**的服务端检查，模型可以直接回答900而不执行工具。

现在从最后一条消息保守生成约束：明确计算需包含calculator、明确时间查询需包含time；明确要求先计算再处理结果，至少两步calculator，后一步必须引用首步ID。历史只用于理解，不授权重放旧任务。示例、文件全文任务和明确不执行的请求不被强制算术路由。模型错误时仍只有原两次结构化尝试，不能通过猜300、预先写900或把两步合成一步蒙混通过。

模型输入仍只有一份当前消息，增加的是current_message_index和派生约束，没有重复正文。原context.py完整轮次与预算机制未改。

### 时间字符串被当数字

真实失败计划为：time s1成功，calculator s2表达式为`$s1.result + 2 + 3`。time实际返回时间字符串，原执行器拒绝它是正确的；问题在于规划校验尚未检查引用的生产工具类型，让不可执行的依赖通过了前置检查。

TaskPlan现在提前验证引用类型：算术只能引用前置calculator，不能引用time。保留严格工具名/参数schema、8步上限、512字符参数上限、前置成功、有限真实数值及原安全算术限制；不转换时间字符串、不接收属性访问或切片、不开放文件路径工具。

对“查询当前时间，并计算2+3”这样的**两个完整、独立、明确子句**，在原纯算式快路径基础上增加有限字面量编排：time与calculator都由原执行器真实调用，表达式直接取用户的2+3，depends_on为空，不把顺序错误解释为数值依赖。支持这类子句的先后顺序；一般自然语言仍走模型规划，不是新增一套Agent。字面量快路径也必须通过相同TaskPlan与工具参数校验。

另一个实际发现是chat.question非空时，旧错误同时说“追问必须有问题”，导致模型反复复制姓名问题。仅把反馈改成按action明确说明空字符串规则，并补充普通姓名问答示例；TaskPlan契约没有放宽，clarify仍必须有有效问题。

### 跨轮结果不是模型猜的

“再将结果乘以3”“结果再乘以3”等受支持的明确数值追问，由后端绑定本聊天上一轮真实calculator结果，再交同一执行器计算。只支持有限的运算与阿拉伯数字形式；无法识别、没有上一轮成功数值、时间字符串、失败结果、过期结果或其他聊天结果时追问，不从聊天文字猜数。

执行记录新增内部source_message_id审计信息，路由核对它是否对应当前近期窗口里的上一用户消息。这样，文件任务绕过主图后遗留的旧计算Checkpoint也不能被误当上一轮结果。旧Checkpoint没有这项来源信息时，保守要求重新给完整算式。没有回填虚假来源或迁移数据库。

原步骤间`$s1.result`仍在执行时解析。故障注入测试把第一步真实返回值改成317，第二步实际得到951，证明没有使用模型预先写出的300或900。字符串"300"、布尔、无穷值和超限数值仍被拒绝。

## 实测结果

环境：Windows，Python3.11.4，Node24.18.0，本机Ollama qwen2.5:7b。核心测试使用替身模型、虚构资料和临时数据库。

| 验收 | 实测 |
| --- | --- |
| 原有及新增单元 | **123/123通过，14.698秒**；保留原109项，新增14项 |
| 新单元 | 当前请求覆盖、时间引用类型、有限重规划、拒绝猜/合并中间值、真实结果动态传递、普通历史追问/解释/禁止执行、独立混合子句、跨轮真实结果、非法/缺失来源、严格question反馈、上一消息来源绑定 |
| 原真实Planner | 两步300→900通过2.830秒；混合time/calculator通过0.989秒；普通聊天无工具通过1.859秒 |
| 真实跨会话原验收 | 共享姓名、私有代号隔离、多轮回忆、历史中两步计算通过；`REAL_DEPENDENCY_TOOL_VALIDATED True`，明确检查两条成功执行记录；精确计算通过，整脚本6.788秒 |
| 新真实集成 | `planner_repair_evaluation --ollama`通过14.559秒：历史中的依赖计算、跨轮2700、另一会话无结果则追问、乙会话独立结果90、文件任务后不复用旧值、混合工具及不计算聊天 |
| 离线实际主图 | 同一新集成用替身模型通过；检查真实参数、成功记录及跨会话来源隔离 |
| 原集成回归 | planner_evaluation、model_prompt_evaluation、chat_routing_evaluation、rag_planner_evaluation、conversations_evaluation、context_evaluation、history_summary_evaluation、memory_management_evaluation、attachment_evaluation通过 |
| 工程 | 前端lint无警告、生产构建、pip check、git diff --check、Python编译检查通过 |

真实计时是本机该用例总耗时，包含后端和模型调用，不是纯推理时间或SLA。中途曾验证“只提前拒绝时间引用”仍不足以修复原模型行为：它会再次尝试字符串切片；安全检查正确拒绝，之后才加入上述明确独立子句编排。相关失败没有当成功记录。

## Windows共享端口复验

本轮新增一次有上限的真实Uvicorn `--workers 2`共享监听复验，使用临时Demo数据、替身对话模型、关闭向量后台。两个PID为28012、31728；40次短连接能观察到两个Worker；4次同身份并发聊天返回**1个200、3个409**，随后历史读取正常，5.000秒结束，没有超时。

这次有限用例通过。409是保留的身份互斥，不是把四次并发都执行成功，更不是高吞吐验收。没有改网络或Worker实现，**不能据此声称之前的偶发共享端口超时根因已找到或彻底消除**；长期压力、真实模型和共享Chroma Server下完整双Worker组合未验证。原超时日志作为历史限制保留。

可核对的本轮报告和日志在忽略目录 `.demo-runtime/shared-worker-recheck/result.json`、`workers.log`。脚本任何超时/异常会保存失败报告并非零退出，不会伪报通过；仅回收自己创建的进程树。

## 复现与启动

没有新依赖或迁移。按README原方式启动Ollama、8000单Worker后端和5173 Vite；已有后端重启即可使用修复。没有操作用户的现有服务进程。之前同一request_id已缓存的响应不会自动重算，应发送一条新消息重试。

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_*.py" -q
.\.venv\Scripts\python.exe -X utf8 -m tests.planner_evaluation --ollama
.\.venv\Scripts\python.exe -X utf8 -m tests.conversations_evaluation --ollama
.\.venv\Scripts\python.exe -X utf8 -m tests.planner_repair_evaluation --ollama
.\.venv\Scripts\python.exe -X utf8 -m tests.windows_shared_worker_evaluation
```

手动聊天可先声明虚构姓名、聊代号，再发送“先计算100+200，再将结果乘以3”，应显示两步真实过程和900；再发送“再将结果乘以3”，应以900继续得到2700。切到新聊天发送“再乘以3”，应要求明确数值；发送“查询当前时间，并计算2+3”，查看时间和5。普通聊天、仅解释算式及明确不要计算不会强制调用工具。

## 文件与边界

生产修改仅3个：src/agent/planner.py（当前意图约束、类型验证、字面量混合及真实结果追问）、tool_router.py（上一轮来源绑定）、tool_executor.py（成功结果来源审计及失败记录工具名）。context.py已检查，无需改造；数据库、API结构、身份、长期记忆、RAG、前端均未改。

新增：tests/test_planner_reliability.py、tests/planner_repair_evaluation.py、tests/windows_shared_worker_evaluation.py、本文。调整已有tests/planner_evaluation.py与conversations_evaluation.py的虚构数据诊断/断言；更新README、第五阶段最终报告索引和local-evaluation记录。未提交Git。

一般自然语言仍依赖模型，不能保证所有复杂表述都能规划成功；验证失败会有限重试后结束或追问，不通过放宽工具权限来“修复”。跨轮结果绑定只针对紧邻的成功数值步骤，不自动查找任意旧历史或其他聊天结果。真实OCR/SMTP、本轮浏览器视觉回归、长时间压力没有重新验证；本轮没有改前端。
