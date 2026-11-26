# 🧬 第四阶段第二小阶段：Embedding 与 Chroma 索引

日期：2026-11-24。仅建设向量索引和检索接口，不将向量结果接入 Planner、LangGraph 或 document_agent 的最终回答。原聊天、摘要、引用、工具、记忆与任务恢复调用链保持。此前各阶段未提交修改全部保留，本轮未提交或推送 Git。

## ✅ 环境与依赖

Windows、Python 虚拟环境、Ollama 0.40.17。改造前单元基线 27/27 通过。下载前确认 C 盘约 98 GB、D 盘约 474 GB 可用，并检查本机模型列表和官方模型信息；随后下载 embeddinggemma（约 622 MB）。真实调用得到 **768 维**，没有用聊天模型的配置字段推测维度。

首个模型 digest：`85462619ee721b466c5927d109d4cb765861907d5417b9109caebc4e614679f1`。程序运行时重新读取实际 digest，并附加可配置 revision；模型同名替换也会失效重建。

新增直接依赖：`langchain-chroma==1.2.0`、`chromadb==1.5.9`。使用现有 `langchain-ollama==1.1.0` 的 OllamaEmbeddings。原 langchain-core 1.6.3、LangGraph 1.2.11、Pydantic 2.13.5、LangSmith 0.12.4 均保留。

Chroma 必需的传递依赖也精确锁定在 requirements.txt，包括 kubernetes 36.0.0、python-dateutil 2.9.0.post0、onnxruntime 1.32.0、tokenizers 0.23.3 等，共新增 48 个版本约束。首次解析在 Kubernetes 新版要求更高 Pydantic 时出现回溯，停止该解析、固定兼容版本后重新 dry-run 再安装；未全面升级原核心。最终 `pip check` 通过。解析报告位于忽略目录 `.demo-runtime/chroma-pinned-resolution.json`，部署以 requirements.txt 为准。依赖安装和首次模型下载需要网络，索引运行使用本机服务，无付费 API。

## 🗂️ 本小阶段文件

新增：

- `src/retrieval/embeddings.py`：独立配置、真实模型标识、维度和有限数值校验、30 秒调用超时。
- `src/retrieval/store.py`：Chroma 本地持久化及可选 HTTP Server 适配、写入/过滤查询/删除。
- `src/retrieval/service.py`：独立状态迁移、索引代次、后台任务、授权检索与清理。
- `tests/test_embeddings.py`：配置与向量校验单元测试。
- `tests/vector_index_evaluation.py`：真实 Chroma，替身/真实 Embedding、API、故障和跨进程恢复测试。
- `tests/fixtures/rag_chinese.json`：独立虚构中文测试集。
- `tests/__init__.py`：默认关闭评测进程自动向量后台工作；指定真实后台测试显式开启。
- 本文。

修改：`requirements.txt`、`.env.example`、`.gitignore`、`src/server/api.py`、`src/server/backup.py`、`frontend/src/App.jsx`、`frontend/src/App.css`、`frontend/vite.config.js`（代理新增检索接口）、`tests/auth_browser_evaluation.py`、`tests/concurrency_backup_evaluation.py`、`README.md`、`docs/local-evaluation.md`。

以上仅列本小阶段；工作区还有先前阶段文件，未删除或回退。loaders.py、splitter.py、Planner、图、记忆和 document_agent 没有为本小阶段重写。

## 🔎 数据与授权流程

上传 → 现有安全解析 → SQLite 原文件与规范原文 → PENDING → INDEXING → Document 派生切分 → Ollama Embedding → Chroma 完整性检查 → READY。失败为 FAILED，记录有界错误，页面可重新索引。原文解析成功和向量可检索是两个独立状态。

SQLite 增量迁移版本 6 使用可重复执行的建表及迁移记录，不修改 documents 核心字段。`rag_indexes` 以身份/文档 ID 为主键，记录内容哈希、模型、配置指纹、切分版本、UUID 代次、状态、模型 digest、实际维度、片段数、时间、失败原因、持有者令牌及租约。`rag_cleanup` 保存废弃代次的待清理记录及重试次数。

Chroma collection 按身份、配置指纹、模型 digest 的哈希隔离；余弦距离。向量 ID 为代次加稳定子片段 ID，元数据包含身份、文档 ID、代次及子片段 ID。同一配置/内容普通重复 enqueue 不重复计算；显式重新索引生成新代次，分批 upsert 幂等。

建索引每批 16 片段，持有 120 秒租约，批次更新租约；向量数量、维度、模型版本及原文哈希检查全部通过才以代次/持有者比较更新 READY。宕机后等旧租约过期，继续该代次的幂等写入，部分批次可能重做；配置/模型更换则创建新代次。不能将部分写入直接标记可用。

新增 `POST /documents/{id}/reindex`，空 JSON 请求；新增 `POST /retrieval/search`，请求为 `query`、可选 `document_ids`、`top_k`（1–20）。统一服务端 Cookie 身份和 Origin 防护，拒绝额外 user_id、collection、filter 参数，外部文件 ID 返回 404。未提供文档范围时仅取当前身份文件，空数组返回空结果。

搜索先校验全部文件归属，再构造身份/文件/代次过滤，绝不全库搜索后才过滤。只查询当前配置、模型 digest 和维度匹配的 READY 索引，最后复核活文档与代次。命中内容还需与 SQLite 派生原文逐字一致；来源位置从 SQLite 重新生成，避免信任向量库内伪造引用。返回文本、文档 ID、子片段 ID、页/行/段落/单元格位置、代次、余弦 distance 与 similarity=1-distance（有界），不是模型置信度。

删除文件在同一 SQLite 事务撤销索引并删除原文、排队物理清理，立即无法通过检索读取。Chroma 暂不可用时物理清理延后；每项最多自动重试 3 次、间隔 30 秒，错误保留在 rag_cleanup。超出次数需运维在服务修复后重置该待清理项的 attempts/retry_at，再启动后台清理；本版没有清理管理页面。旧物理向量即使暂存，也过不了授权与 READY 代次检查。恢复备份后可能遗留无状态关联的旧向量，需要停服后按部署目录进行维护，不自动删除整个目录。

## ▶️ 从开机启动和演示

1. 启动 Ollama 桌面程序。没有后台服务时在独立终端运行 `ollama serve`；若已运行不要重复开。
2. 首次更新时停止旧后端，在 PowerShell 安装依赖和模型：

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama list
ollama pull embeddinggemma
```

3. 后端终端（保持打开）：

```powershell
cd <LOCAL_PROJECT_PATH>
$env:MY_AGENT_MODE = 'local'
$env:MY_AGENT_MODEL = 'qwen2.5:7b'
$env:MY_AGENT_OLLAMA_URL = 'http://127.0.0.1:11434'
$env:MY_AGENT_RAG_ENABLED = '1'
$env:MY_AGENT_EMBEDDING_MODEL = 'embeddinggemma'
$env:MY_AGENT_EMBEDDING_URL = 'http://127.0.0.1:11434'
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

4. 前端另一个终端（保持打开）：

```powershell
cd <LOCAL_PROJECT_PATH>
npm install
npm run dev -- --host 127.0.0.1
```

打开终端显示的本地页面，通常 http://127.0.0.1:5173 。登录或显式进入访客，上传虚构 TXT/PDF/DOCX，观察等待索引→正在索引→可检索，刷新后状态仍在。点击重新索引可重建，删除后立即取消访问。小文件可能快到看不见中间状态。页面约每 3 秒刷新状态，后台约每 15 秒同步原文/模型状态。

**聊天文件回答仍走原有流程，尚未接入语义 RAG 回答。** 向量查询可通过 `/docs` 的 `/retrieval/search` 验证（需要同源身份/请求防护），或直接运行以下独立验收脚本。最简真实后台演示是 `--auto-real`，不需要人工操作接口。

故障演示：将后端 `MY_AGENT_EMBEDDING_MODEL` 临时改为不存在的模型并重启，上传虚构文件，看到索引失败，普通聊天/计算仍可使用。恢复 embeddinggemma 后重启并重新索引，等待可检索。不要为制造故障停掉正在供其他任务使用的 Ollama 服务。

默认 Chroma 位于 APP_DB 同目录的 `<数据库文件名去后缀>_chroma`；本地为 `data/local_sessions_chroma`。可用 MY_AGENT_CHROMA_DIR 指定独立持久化目录。切分默认 800/100，配置见 .env.example；改模型、模型修订或切分参数会重建，不改旧引用。

## 🧪 实际验收

| 验收 | 结果 |
| --- | --- |
| 全部单元测试 | 29/29，最终复跑 4.925 秒 |
| 替身 Embedding + 真实持久化 Chroma | 成功、幂等、范围、双身份、跨账号 ID 拒绝、删除物理清理、服务失败、批次中断与重试通过 |
| 模型名/digest/代次变化 | 旧索引拒绝，重新排队；写入中代次替换不得发布 READY，通过 |
| 实际进程退出/重启 | build→read→recover 三进程通过；READY 直接读取不再嵌入，过期 INDEXING 续跑通过 |
| 真实 embeddinggemma | 中文 768 维；4 文档/8 问题 Top-1 8/8，约 2.53 秒单次嵌入探测 |
| 真实自动后台流程 | 上传→READY→API 检索→重建新代次→普通工具→删除，6.078 秒 |
| 原功能离线回归 | local、auth、document_preparation、abstract、network、advanced、chat_routing、model_prompt、planner、account_management 脚本通过 |
| 备份恢复 | concurrency_backup_evaluation 通过；新增 READY 索引恢复后清空状态并由原文重建验证，原账号/历史/引用/记忆/未完成任务恢复通过 |
| 浏览器 | Edge auth_browser_evaluation 通过，包含文件索引失败状态与重试操作 |
| 原双 Worker | multiworker_evaluation 通过，明确关闭向量后台；不是嵌入式 Chroma 双 Worker 验收 |
| 真实 qwen2.5:7b | 依赖计算 900：7.209 秒；混合工具 8.505 秒；普通聊天 20.095 秒，均通过 |
| 前端 lint / 生产构建 / pip check / git diff --check | 通过 |

所有脚本使用临时数据库、临时 Chroma 目录和虚构资料，不读取个人 PDF。测试进程默认关闭自动索引，专门后台测试显式开启。真实检索 8/8 是小型固定测试集结果，不代表任意中文知识库效果；本轮没有对其作一般化承诺。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.vector_index_evaluation
.\.venv\Scripts\python.exe -X utf8 -m tests.vector_index_evaluation --real
.\.venv\Scripts\python.exe -X utf8 -m tests.vector_index_evaluation --auto-real
.\.venv\Scripts\python.exe -X utf8 -m tests.concurrency_backup_evaluation
npm --prefix frontend run lint
npm --prefix frontend run build
```

## 📌 边界与待验证

- 默认后台开启，**嵌入式 Chroma 仅支持单 Worker**。原双 Worker 回归需设置 MY_AGENT_RAG_ENABLED=0；不要据此宣称向量并发可用。MY_AGENT_CHROMA_URL 预留共享 HTTP 服务适配，真实 Server、鉴权/TLS及多 Worker向量协调没有验收，不建议公开部署该可选模式。
- Embedding 故障或缺模型不会阻止 API 启动与旧聊天/工具，索引失败有限重试后需显式重新索引。索引运行按有限批次同步工作，不是分布式队列。
- 查询是 top-k 相似片段，不设置通用相关性阈值，不自动判断“有无答案”；本阶段不生成 RAG 最终回答，因此还没有验证基于向量的无依据拒答。
- 完整摘要/版本核对仍使用原逻辑，不改为仅看 top-k。长文本原有规模限制继续生效，没有新做压力测试。
- SQLite 原文为事实来源。备份沿用维护屏障覆盖三个原数据库，Chroma 不属于一致快照；恢复撤销旧登录令牌、清空派生索引状态，重新同步建立新代次。不能将复制 Chroma 文件夹声称为跨库在线一致备份。
- 本轮真实 OCR、SMTP、共享 Chroma Server、长期压力和所有窄屏组合未验证；没有创建公网入口或发送真实邮件。

本小阶段完成后停止，下一小阶段经确认后再将语义检索接入现有回答链。
