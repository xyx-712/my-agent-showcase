# 🧹 第七阶段第一小阶段：项目整理与文档完善

日期：2026-11-24。范围仅为目录、依赖、配置与说明整理，没有新增功能、改动业务代码、数据库结构、API 或依赖版本，未提交推送 Git。

## 修改与清理

| 文件 | 本轮处理 |
| --- | --- |
| README.md | 从阶段追加日志整理为当前能力、技术栈、目录、LangGraph 架构、Planner/Tools/RAG/Memory 流程、多会话与持久化、Windows 启动、演示、备份和限制 |
| .env.example | 修正“仅向量索引”的旧描述；补请求总预算、认证有效期、OCR 和 SMTP 的可选配置；保留原有模型、RAG、上下文与摘要配置 |
| .gitignore | 仅删除第二组重复的 `__pycache__/`、`*.pyc` 规则，保留第一组及所有数据忽略规则 |
| docs/readme-history-through-stage6.md | 存档整理前的完整 README，注明历史性质，并调整迁移后的相对链接，保留先前工作 |
| docs/project-stage7-1.md | 本轮检查、验收与未解决事项 |

没有删除代码、夹具、个人数据、历史数据库或既有文档。仅清理本轮隔离启动检查产生的临时测试目录；前端构建刷新被忽略的 frontend/dist，不修改前端源文件。

## 目录与调用关系检查

- 主入口 `src/server/api.py`，不是旧独立 Memory 示例。前置 document_turn 可直接处理文件问题；普通主图也可经 knowledge/document 节点进入同一文档能力。README 不再把所有请求描述为单一路由，也不宣称另建 RAG Agent。
- `model_provider.py`、提示模板、`context.py` 与 `execution.py` 分别负责模型配置、提示、上下文预算和协作期限；保留现有 LangGraph 状态与图。
- `registry.py` 用 LangChain Tools 包装原函数，并为 project_schedule 保留 SimpleTool 适配。原函数与包装器不是应删除的重复实现；Planner 自动工具白名单实际只有 calculator/time。
- `retrieval/loaders.py` 是基于现有安全解析器和原始片段的 LangChain 适配，不是重新绕过归属打开路径。索引、语义问答和完整文档任务职责保持分离。
- 认证身份、聊天会话、任务和 checkpoint 各有既有绑定；长期记忆按用户共享。SQLite 原文是事实来源，Chroma 为派生索引。
- 本轮源文件内容比对未发现非空 Python 文件完全重复。空包入口不作为重复垃圾删除；未把“未发现静态引用”等同于绝对无用。

## 保留的兼容内容

| 内容 | 判断与处理 |
| --- | --- |
| src/memory/memory.py、profile_memory.py | 旧 JSON 帮助函数，当前主图不依赖它们；可能存在外部调用或历史用法，保留 |
| src/memory/database.py | 旧数据库模块，导入会建立连接；本轮仅阅读，不导入或创建其旧数据库 |
| src/agent/memory_load.py | 旧加载节点，当前主图未连接，含历史打印；保留，避免未经确认改变旧入口 |
| src/tools/base.py、schema.py、tool_schema.py | 旧工具类型/参数/导出兼容层，保留，未为统一外观重写 |
| registry.py 中可选 memory 工具导入 | 潜在扩展入口，当前对应文件不存在；不因当前缺失而删除兼容逻辑 |
| demo_files/、Dockerfile、render.yaml | 内部文件读取夹具和既有部署材料；没有恢复默认文档加载，也未部署或创建公网入口 |
| chat_history.json、*.db、WAL/SHM、data/、.demo-runtime/ | 运行数据或历史成果，原样保留，不能当垃圾清理 |

## 依赖与配置

- `requirements.txt` 保持原有锁定版本。langchain-community / langchain-classic 有已安装元数据中的相互依赖；Chroma 的 Kubernetes、ONNX、OpenTelemetry 等为传递依赖，不能因 src 不直接 import 就删掉。
- `.venv` 内 `pip check` 通过；`pip install --dry-run --no-index -r requirements.txt` 退出 0，没有执行安装或联网解析。它只证明当前环境满足依赖，不证明全新机器安装可复现，也不是完整传递依赖锁文件。
- 前端 package-lock.json 保留，首次安装统一 `npm --prefix frontend ci`；开发入口固定 5173、代理后端 8000。没有更改 package.json、锁文件或 Vite 配置。
- `.env` 不读取、不覆盖；示例共有 33 个无重复的 MY_AGENT 配置名。进程环境优先于根目录 .env，切换 Chroma 模式时需同时检查两处。
- 统一默认本地方案为 Ollama + 单 Worker 后端 + Vite；首次准备同时下载 qwen2.5:7b 和 embeddinggemma。共享 Chroma、OCR、SMTP、Demo 列为可选条件，不混入默认启动必需项。
- Local checkpoint 仍依赖工作目录，因此明确要求从仓库根目录启动。没有借整理修改路径或迁移数据库。

## 本轮实际验收

环境：Windows，Python 3.11.4，Node.js v24.18.0，npm 11.16.0。

| 检查 | 实际结果 |
| --- | --- |
| Python 依赖一致性 | `python -m pip check` 通过，无冲突 |
| requirements 当前环境离线 dry-run | 通过，未安装/升级依赖 |
| Python 源码与测试 AST 解析 | 通过，未导入应用或旧兼容数据库模块 |
| 完整单元测试 | 139/139，13.472 秒 |
| 请求稳定性集成 | 通过，临时数据库、替身模型与真实 API/主图；包含 300→900、超时、SQLite 不确定状态与防重放 |
| 前端 lint | oxlint 通过 |
| 前端生产构建 | Vite 8.2.2 通过；20 模块，构建报告 142 ms |
| Chroma 命令兼容性 | 本机 `chroma run --help` 确认 host/port/path 参数，未启动共享服务 |
| 文档链接与配置 | README、存档、报告的本地文件链接通过；示例 33 个配置名无重复，均在实际源码中存在 |
| 既有工作保护 | 整理前后哈希一致：src、frontend/src、tests、requirements、前端 package/lock/Vite、Dockerfile 与 render.yaml |
| 格式检查 | `git diff --check` 通过 |
| Uvicorn 单进程隔离启动 | 两次均 Application startup complete，`/health` 返回 200 / `{"status":"ok"}`，约 1.75 秒；使用临时 Demo 数据目录、动态本地端口、关闭 RAG，不接触 Local 数据 |
| 启动检查的自动退出清理 | 未通过：Windows 虚拟环境子进程/文件占用及进程树终止权限导致测试脚本退出非零；不能把整条脚本描述为通过。随后关闭本次已确认 PID 的临时后端并清理其测试目录，未停止用户原有服务 |

除已说明的测试退出清理问题，本轮必要单元、接口和构建检查没有失败。

## 尚未解决与未验证

- 不扩大范围修复 Windows 测试进程退出权限/清理问题，没有重构应用生命周期或双 Worker。该问题不等于后端启动失败；健康响应也不能证明真实模型问答可用。
- 未重跑真实 Ollama/Embedding、浏览器视觉、Windows 双 Worker、长期压力、真实 OCR、SMTP 或公网验收；历史报告明确保留但不算本轮通过。
- 未在全新虚拟环境执行联网安装、`npm ci`、Docker 构建或 Render 部署；本轮验证的是现有环境的版本一致性与构建能力。
- 旧模块的外部使用情况无法仅从仓库静态搜索完全证明；本轮没有删除任何可能被外部调用的代码。完整废弃兼容层、依赖最小化或路径修复需要另行确认。
- Checkpoint 相对路径、协作超时的同步阻塞边界、进程级限速、孤立旧向量清理和多库部分持久化边界沿用原实现，README 已明确。

后续阶段应另行确认。本阶段完成后停止，不提交或推送 Git。
