# ✅ 第七阶段第二小阶段：最终验收与发布检查

日期：2026-11-24。结论：**当前环境的本地主线功能通过，但 GitHub 发布检查尚未全部通过。** Git 历史中的 checkpoint 数据库需要另行处理；本轮 Edge 页面验收未通过。不提交、不推送、不打标签、不删除旧数据或重写历史。

## 1. 本轮修改和发布材料

- `.gitignore`：增加 `.env.*` 并保留 `!.env.example`；增加 SQLite / SQLite3 数据及其旁文件忽略规则。没有移除任何已跟踪文件或运行数据。
- `README.md`：链接本轮真实结果、失败项和发布候选清单，不覆盖历史报告。
- `docs/final-stage7-2.md`：本报告。
- `docs/release-candidate-files.txt`：当前跟踪文件与未忽略的新文件的路径清单。它是审阅材料，不代表已暂存、已提交或已安全净化 Git 历史。

没有新增依赖、业务功能或修改源码、测试标准、数据库结构及 API；既有未提交成果保留。前端构建只刷新被忽略的 dist。验收结束时暂存区为空。

## 2. 环境、依赖和启动

本机环境：Windows、Python 3.11.4、Node.js v24.18.0、npm 11.16.0。当前 Ollama 本地服务可访问，已安装 qwen2.5:7b 和 embeddinggemma；本轮真实模型脚本明确指定 `http://127.0.0.1:11434`，不使用云端密钥或付费服务。

| 检查 | 结果 |
| --- | --- |
| `python -m pip check` | 通过，无冲突 |
| `pip install --dry-run --no-index -q -r requirements.txt` | 通过；仅检查现有环境，不执行安装 |
| `npm --prefix frontend ls --depth=0 --offline` | 通过；React/React DOM 19.3.0、Vite 8.2.2、oxlint 1.82.0，满足当前清单范围 |
| 前端 lint | 通过 |
| 前端生产构建 | 通过，20 模块，构建输出 106 ms |
| Local 后端启动 / health | 通过，约 0.219 秒；8000 端口，`/health` 返回 200 和 `{"status":"ok"}` |
| Vite 开发入口与代理 | 通过，5173 返回带 Vite 客户端的 HTML；经代理进入访客、建立 Cookie、计算 1+4=5、读取两条历史 |
| 本轮测试服务退出 | 通过，自己的 Node/Vite 进程和 Uvicorn 线程均退出，临时资料清理完成 |

启动检查使用临时三库覆盖 Local 路径，运行相同 app 的 Uvicorn Server（单 Worker）和真实 Vite CLI 入口，参数/端口与 README 对齐；未启动或写入用户的 Local 三库。Vite 用 Node 直接运行 package.json 所对应入口，避免 Windows npm 启动器的子进程清理问题。没有修改应用退出逻辑，也没有据此推断所有子进程场景都已修复。

首次安装说明与当前配置一致，但**未在全新虚拟环境/全新机器重新联网安装**，未重下模型，不能声称已通过全新机器验收。

## 3. 已通过的功能测试

除真实模型行外，其余业务验收使用替身模型或替身 Embedding；所有附件、账号和数据库均为隔离虚构测试资料。

| 命令（虚拟环境 Python） | 结果及覆盖 |
| --- | --- |
| `-m unittest discover -s tests -p "test_*.py"` | **139/139**，14.320 秒 |
| `-m tests.request_stability_evaluation` | 真实 API/主图：300→900、防重放、失败/超时收尾、SQLite 结果未知时保守保护、后续请求正常 |
| `-m tests.planner_repair_evaluation --ollama` | **真实 qwen2.5:7b**：普通/多轮上下文、依赖计算、真实前步结果、跨聊天隔离、时间/计算混合；14.287 秒 |
| `-m tests.rag_planner_evaluation --real` | **真实模型与 Embedding、本地 Chroma**：上传、索引、Planner knowledge/document 路由、引用、普通工具、全文摘要和删除后引用失效 |
| `-m tests.rag_closure_evaluation` | **真实模型与 Embedding**：跨两文件回答、主题相近但无答案拒答、PDF 页码、DOCX 段落和表格、阈值比较；24.748 秒 |
| `-m tests.memory_management_evaluation` | 记忆查看、来源、修订、并发版本校验、删除防回放、暂停/恢复、聊天/工具/RAG、认证与备份恢复 |
| `-m tests.conversations_evaluation` | 多聊天历史/摘要/checkpoint/附件/任务/RAG 隔离、共享记忆、第二客户端、软删恢复、备份恢复；脚本记录 5.229 秒 |
| `-m tests.conversations_evaluation --restart` | 新进程创建和读取：会话、任务、checkpoint 恢复通过 |
| `-m tests.history_summary_evaluation` | 新进程摘要构建/续跑/读取、失败回退重试、用户纠正、记忆删除保护、隔离和备份恢复 |
| `-m tests.history_summary_evaluation --ollama` | **真实 qwen2.5:7b**：旧背景与决定摘要、回答使用旧约束、更正项目后采用新值；7.301 秒 |
| `-m tests.attachment_evaluation` | 摘要引用、版本工期 15→20、计算故障续跑、旧证据失效和文档提示注入；没有放宽标准 |
| `-m tests.concurrency_backup_evaluation` | 原有独立进程互斥、防重放、维护屏障、在线拒绝恢复和完整恢复通过；不代表 Windows 共享端口双 Worker 复测 |
| `-m tests.auth_evaluation` | 注册/登录、迁移回滚、归属保留、跨客户端隔离、令牌轮换、并发和限速通过 |

RAG 验收保持原门槛 0.65、Top-K=4，没有为通过而降低校验。实际模型曾生成不一致初稿，后端既有证据/结构校验和有限重试后通过。中文同义表达仍有分数低于门槛而拒答的情况，不能将一次套件成功描述为任意问题都可回答。

## 4. 未通过项

### Edge 完整页面流程

执行 `python -X utf8 -m tests.conversations_browser_evaluation`，退出码 1。Edge/CDP WebSocket 在等待 `.auth-panel` 的第一项页面断言时发生 `WinError 10054` / `ConnectionClosedError`。

这次没有完成注册、上传、引用点击、多会话切换和窄屏布局的浏览器链路，不能把后端接口或 HTTP 冒烟代替 GUI 验收。没有降低断言、修改前端或循环重试；具体连接关闭原因尚未定位，按本轮范围保留。

### Git 历史隐私检查

当前 HEAD 可达历史含 **3 个 `agent_checkpoints.db` blob**，仅核对对象元数据，未读取数据库内容：

| 对象前缀 | 大小（字节） |
| --- | ---: |
| 11a1aff6ba2b | 438272 |
| 1fe93f95ac0a | 380928 |
| 76495c20d964 | 360448 |

这些数据库可能含旧状态或对话。当前工作树忽略数据库，不会清除旧提交里的对象。**因此隐私发布门槛未通过。** 没有自行改写历史、删除用户数据库、强制推送或创建替代仓库。

## 5. 当前文件隐私与发布候选检查

- 当前候选路径中没有 `.env`、运行数据库、聊天 JSON、data/、.demo-runtime/、.venv/、node_modules/、dist/ 或运行 Chroma 数据；已有数据仍留在本机。
- 用 `git check-ignore --no-index` 验证真实/代表性路径，`.env`、`.env.local`、`.env.production`、数据库和向量数据被忽略；`.env.example` 保持可发布。
- 只扫描 Git 当前候选文本，检查私钥 PEM、常见 GitHub/OpenAI 令牌格式与含明文凭据的 URL，没有发现匹配。**未读取私人 .env 和附件数据库；这不是完整的所有密钥/所有历史内容安全审计。**
- 当前唯一非 UTF-8 候选 `frontend/src/assets/hero.png` 已查看，是前端几何示意图，不是用户附件或照片。
- 检查所有候选 Markdown 的相对文件链接，未发现引用被排除的本地文件；README 架构图与实际主图/文档前置分流、RAG 和 Memory 一致。Mermaid 未另行做 GitHub 页面渲染验收。
- `.env.example` 仍为占位示例，真实配置未复制进发布材料。候选清单不含任何 Git 数据库 blob 内容，但提交当前分支仍会携带其旧历史，不能因此绕过上面的发布阻碍。
- 候选文件清单保留当前全部业务、测试、文档、构建配置和前端资源。不会执行 `git add .` 或自动暂存；发布说明可据本报告撰写，版本/标签待用户确认。
- 交付前复核：候选清单共 **174 个路径**，与 Git 当前候选一致；业务源码、测试和前端源文件的汇总哈希与本轮开始时一致，暂存区为空。Markdown 本地文件链接有效，`git diff --check` 通过，本次启动检查的 8000/5173 端口已释放。

## 6. 启动与复现

在仓库根目录，首次安装沿用 README：

```powershell
cd <LOCAL_PROJECT_PATH>
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm --prefix frontend ci
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
ollama pull qwen2.5:7b
ollama pull embeddinggemma
```

开机启动 Ollama 并确认 `ollama list`，终端一：

```powershell
cd <LOCAL_PROJECT_PATH>
$env:MY_AGENT_MODE='local'
$env:MY_AGENT_MODEL='qwen2.5:7b'
$env:MY_AGENT_OLLAMA_URL='http://127.0.0.1:11434'
$env:MY_AGENT_EMBEDDING_MODEL='embeddinggemma'
$env:MY_AGENT_EMBEDDING_URL='http://127.0.0.1:11434'
$env:MY_AGENT_RAG_ENABLED='1'
Remove-Item Env:MY_AGENT_CHROMA_URL -ErrorAction SilentlyContinue
# 同时确认 .env 没有启用共享 Chroma URL。
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

终端二：

```powershell
cd <LOCAL_PROJECT_PATH>
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

浏览器打开 `http://127.0.0.1:5173`，后端健康检查 `http://127.0.0.1:8000/health`。不要在已有服务占用端口时重复启动。数据路径、配置与演示细节以 [README](../README.md) 为准。

必要离线复验：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m tests.request_stability_evaluation
.\.venv\Scripts\python.exe -m tests.memory_management_evaluation
.\.venv\Scripts\python.exe -m tests.conversations_evaluation --restart
npm --prefix frontend run lint
npm --prefix frontend run build
git diff --check
```

## 7. 未验证与剩余工作

- 本次浏览器 GUI 完整流程未通过，需要单独复核 Edge 调试连接或亲自在浏览器按 README 完成验收；不能以历史通过替代。
- 发布前需明确对旧 checkpoint Git 历史的处理方案，并在获准后重新检查；这会涉及超出本轮的 Git 历史操作，本轮不执行。
- 全新机器联网依赖安装、共享 Chroma Server/Windows 双 Worker、长期压力、真实 OCR、SMTP、Docker/Render 和公网入口本轮未验证，未自动部署或发邮件。
- 本轮未进行全历史文本密钥审计、漏洞数据库检查或 GitHub 远端页面核验；不要把当前有限检查描述为完整安全认证。
- 协作超时、SQLite 不确定状态、旧 running 保护、跨库部分持久化和普通 Planner 自动恢复边界沿用 README，不在验收阶段扩展实现。

**交付状态：测试与发布材料已整理，当前未发布；等待用户确认后续处理。**
