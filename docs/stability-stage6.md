# 第六阶段：最小稳定性修复

验收日期：2026-11-24。环境：Windows、仓库原有 Python 3.11 虚拟环境。仅修复请求异常收尾、协作式总预算和 SQLite 异常下的重复执行保护；未新增依赖、修改表结构、前端或 API 请求/成功响应结构，未提交推送 Git。

## 原因与实现

- 原先先写 running，再执行消息长度校验；执行抛异常后缺少失败收尾。现在长度检查在登记前完成，统一请求执行入口在同步执行栈退出后登记结果。
- `chat_requests` 原有 state/response 字段分别保存 completed、recoverable、failed、timed_out，不改变表结构。recoverable 表示本轮已结束、文档任务等待继续，原请求返回缓存响应；failed/timed_out 原请求返回已登记错误，不重新调用模型或工具。running 一律拒绝重放。
- 最终登记使用 `WHERE state='running'` 和受影响行数校验，避免覆盖已完成记录。数据库执行、提交或失败登记异常返回 503，不删除记录、不伪造完成、不自动重新执行。
- 新增 execution.py，以 ContextVar 和 monotonic 时间为整轮聊天共享预算。嵌套工作流不重置期限；普通图节点、文档步骤、模型调用前后和工具边界检查预算。同步调用返回后若已超时，停止后续步骤并返回 504，不使用遗留后台线程实现假超时。
- 已持久化的工具结果保留在 checkpoint，文档任务读取最新持久化版本转为 waiting/continue，保留检索和计算成果；不使用旧节点输入覆盖新进度，不降级已完成文档任务。数据库异常时跳过这项补写。
- 摘要、RAG 文档分支和工具执行不把 SQLite 异常伪装成普通模型失败；认证/协调中间件的 SQLite 异常返回统一 503。

## 启动和配置

无需安装依赖或构建前端。停止原后端后，从仓库根目录按原命令启动；预算可选配置：

```powershell
cd <LOCAL_PROJECT_PATH>
$env:MY_AGENT_REQUEST_SECONDS = '180'
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

默认 180 秒，允许大于 0、不超过 3600 的有限数值。该时间是合作停止期限，不是接口必定在该秒数返回的硬时限。现有单次模型网络超时仍保留。

## 本阶段文件清单

新增：

- src/agent/execution.py：统一预算、步骤保护、同步模型调用前后检查。
- tests/test_request_stability.py：16 项隔离单元测试。
- tests/request_stability_evaluation.py：临时三库下的真实 API/图集成验收，使用替身模型。
- docs/stability-stage6.md：本报告。

修改：

- src/server/request_log.py：请求执行、终态登记、缓存和保守拒绝重放。
- src/server/api.py：提前校验、接入预算、SQLite 错误响应。
- src/agent/graph.py：原图节点预算检查和模型调用适配。
- src/agent/skills.py：结构化模型调用共用预算，保留原有限重试。
- src/agent/document_agent.py：工具执行边界与最新持久化任务的失败恢复。
- src/agent/history_summary.py：模型调用预算和数据库错误传播。
- src/agent/tool_executor.py：工具步骤预算与 SQLite 错误传播。
- README.md：预算配置和报告入口。

以上是本轮触及文件；仓库还有先前阶段的未提交成果，不能将全部 git diff 当作本轮修改。

## 实测结果

| 验收 | 结果 |
| --- | --- |
| 修改前完整单元测试 | 123/123，13.014 秒 |
| 最终完整单元测试 | 139/139，13.642 秒，含新增 16 项 |
| 请求稳定性 API 集成 | 通过：提前校验、真实图 300→900、缓存重放、迟到模型结果超时、异常终态、SQLite 不确定状态、后续请求正常 |
| 附件原有回归 | 通过：摘要、引用、15→20 工作日追问、检索后计算故障续跑、删除失效、提示注入和身份隔离 |
| Planner 修复回归 | 通过：上下文意图、多步真实结果、跨轮结果绑定、混合工具和跨会话隔离 |
| 原协调备份恢复回归 | 通过：独立进程互斥、幂等、维护屏障、运行中拒绝恢复、完整恢复；未开展新的双 Worker 优化 |
| RAG Planner 集成回归 | 通过：共享检索、引用、工具、完整摘要路径和删除后禁止引用；替身模型/Embedding、本地 Chroma |
| 历史摘要回归 | 通过：新进程恢复、失败回退和重试、用户纠正、记忆删除保护、备份恢复 |
| 多会话回归 | 通过：历史/摘要/checkpoint/附件/任务隔离、共享记忆、第二客户端和备份恢复 |
| 认证回归 | 通过：迁移、归属保留、账号隔离、令牌轮换、并发与限速 |
| git diff --check | 通过 |

阻塞模型测试用事件控制实际调用返回：返回前 running 保持、重复请求 409；返回后记录 timed_out，后续步骤零调用。另验证 checkpoint 保留上一节点真实结果、文档清理使用最新证据、数据库错误不补写、已完成任务不被降级。

新增测试首次运行遇到 Windows 临时数据库连接未显式关闭导致的清理失败，已修正测试夹具并全部复跑通过。最终无失败用例。前端未修改，按本次要求未重建。

复现命令（均使用临时数据库和虚构数据）：

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_request_stability
.\.venv\Scripts\python.exe -m tests.request_stability_evaluation
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m tests.attachment_evaluation
.\.venv\Scripts\python.exe -m tests.planner_repair_evaluation
.\.venv\Scripts\python.exe -m tests.concurrency_backup_evaluation
.\.venv\Scripts\python.exe -m tests.rag_planner_evaluation
.\.venv\Scripts\python.exe -m tests.history_summary_evaluation
.\.venv\Scripts\python.exe -m tests.conversations_evaluation
.\.venv\Scripts\python.exe -m tests.auth_evaluation
```

## 恢复与限制

- 超时不强制中断正在执行的同步模型、SQLite 或工具调用；调用实际返回或抛错后才收尾。若底层永久不返回，预算本身不能终止它，也不承诺停止 Ollama 服务端的推理。没有引入遗留执行线程。
- request_id 用于同一会话请求的防重放；未提供 ID 的请求仍接受预算和错误处理，但不能据此证明两次请求是重复。不同 ID 代表新请求，不能保证跨新请求的任意操作恰好执行一次。
- 数据库不可用、进程被强制终止以及旧版本遗留的 running 记录继续保守保护；不因记录过旧就自动重放。先核对历史、任务和 checkpoint，再决定是否用新消息继续。保留原有请求记录数量上限。
- 文档任务按现有持久化机制复用证据和结果。普通 Planner 的 checkpoint 保留已完成步骤，但本轮未新增任意普通计划自动续跑协议；不宣称所有步骤都支持自动恢复或永不重算。
- 多库写入未改造成跨库事务。出现部分持久化时保留进度并阻止原请求重放，不宣称回滚全部历史、记忆或 checkpoint。
- 本轮未重新验证真实 Ollama、浏览器、Windows 共享端口双 Worker、长期压力、真实 OCR 和 SMTP。原有这些验收记录不作为本轮重新通过的证据。
