# 架构升级第一阶段：统一模型与提示词

## 范围与实现

基线为v1.3.0 / ad19a95，开始时工作区干净。只检查仓库代码和虚构测试资料，没有读取个人附件或迁移真实用户数据库。

- 新增 src/agent/model_provider.py：get_chat_model 每进程缓存一个基础ChatOllama，保留 MY_AGENT_MODEL、MY_AGENT_OLLAMA_URL、MY_AGENT_OLLAMA_API_KEY 及HTTPS限制、90秒客户端超时、temperature=0、Demo num_predict=4096 / Local未指定。运行中更改环境变量不会重新创建模型，需要重启进程。
- structured_model 为真实ChatOllama创建保留原配置的浅拷贝，指定JSON Schema、num_ctx=8192、num_predict=4096；不改变共享实例，不另行初始化模型连接。invoke兼容的替身直接使用，不要求实现bind/model_copy。
- graph.py 继续暴露llm供API文档流程复用，也保留现有测试替换general_agent.llm的入口；从provider获取基础模型，使用CHAT_PROMPT与消息占位符组装消息。
- prompts/agent_prompt.py 集中ChatPromptTemplate：普通聊天、工具结果模板、结构化模板。原有SYSTEM_PROMPT常量仅保留兼容，活跃调用不切换为该旧提示词。变量中的JSON大括号不会再次被解释为模板字段。
- skills.py 让skill选择、字段提取、文档问答、归纳合并及路由的model_json共用结构化模板；保留原业务指令、Pydantic严格校验、引用校验、两次尝试和错误路径。

没有调整LangGraph拓扑、工具、Planner、检索、记忆提取、数据库、API契约或前端。工具结果仍按原顺序使用system消息，本阶段只保持行为，不提前做第三阶段的ToolMessage迁移。没有恢复默认资料或日历界面。

## 基线与实测

动工前使用临时库复跑：local_evaluation（附件/引用、15→20、临时故障与独立进程恢复）、abstract_evaluation（摘要缩写、跨批次/重启）、chat_routing_evaluation、network_evaluation，全部通过。网络排程离线基线2.020秒。

改造后：

| 检查 | 实际结果 |
| --- | --- |
| 原提示词等价检查 | 从Git基线只读提取旧提示文本，对照模板渲染，聊天system、工具system、结构化system/user逐字一致；包含JSON大括号与重试反馈 |
| unittest discover | 14/14通过，2.070秒；含新增5项模型配置/缓存/HTTPS限制/结构化不变性/消息角色模板测试 |
| model_prompt_evaluation | 通过；真实FastAPI临时库，替身注入、同一历史消息顺序、当前消息恰好一次、工具提示、文档共享调用、失败后重试及最多两次截止 |
| local_evaluation | 通过；原附件分析、引用、15→20、计算故障恢复与独立进程重启复用证据 |
| abstract_evaluation | 通过；摘要缩写、错误引文拒绝、多候选、身份隔离、首批完成后失败并由独立进程续跑 |
| network_evaluation | 通过，1.843秒；多阶段依赖、日历后端兼容、延后追问、复用证据 |
| advanced_evaluation | 通过；综合摘要、多任务切换、暂停与恢复 |
| chat_routing_evaluation | 通过；上传后普通聊天、独立计算与任务保留 |
| auth_evaluation | 通过；身份、令牌、迁移回滚、隔离 |
| concurrency_backup_evaluation | 通过；租约、重复请求、维护屏障、备份恢复、恢复后的待完成任务 |
| 前端lint / build | 均通过；生产构建113ms，前端代码未修改 |
| 真实Ollama两轮普通聊天 | qwen2.5:7b通过，5.735秒；第一轮提供虚构代号“蓝杉”，第二轮正确回忆，历史恰好四条 |
| 真实Ollama多阶段工期 | 通过，15.492秒；skill选择、中文数字提取、计算、引用与延后追问7→12 |
| 真实Ollama虚构PDF摘要 | 通过，10.332秒；定位摘要、压缩改写、证据校验，fiction.pdf第1页L2–5引用 |

新增测试均配置临时数据库后才导入API，虚构文件不写入个人资料范围。运行环境沿用Windows、Python3.11.4、Node24.18.0、langchain-core1.6.3、langchain-ollama1.1.0、LangGraph1.2.11，无新增依赖。

## 修改文件

修改：src/agent/graph.py、src/agent/skills.py、src/prompts/agent_prompt.py、README.md、docs/local-evaluation.md。

新增：src/agent/model_provider.py、tests/test_model_prompts.py、tests/model_prompt_evaluation.py、本记录。

## 启动与验证

无需重新安装依赖，无数据库迁移。停止旧后端，在仓库根目录原终端按README命令启动：

```powershell
cd <LOCAL_PROJECT_PATH>
$env:MY_AGENT_MODE = 'local'
$env:MY_AGENT_MODEL = 'qwen2.5:7b'
$env:MY_AGENT_OLLAMA_URL = 'http://127.0.0.1:11434'
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

前端仍使用 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort`。先确认Ollama已运行且有qwen2.5:7b，然后测试两轮聊天、上传文件摘要并点击引用；已有任务可以继续。

可重复执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.model_prompt_evaluation
.\.venv\Scripts\python.exe -X utf8 -m tests.model_prompt_evaluation --ollama
.\.venv\Scripts\python.exe -X utf8 -m tests.abstract_evaluation --ollama
```

## 验证边界

本轮没有重新运行浏览器、真实双Worker、SMTP/OCR或公网测试；不将历史通过视为本轮新通过。真实模型仅短资料代表性验证，不保证任意资料稳定成功；已有原两阶段真实模型历史失败记录继续保留。未升级到LangChain标准工具、with_structured_output、ToolNode或语义RAG；这些属于后续阶段。没有提交或推送Git，完成本阶段后停止等待确认。
