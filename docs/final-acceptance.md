# ✅ 最终验收报告（2026-11-23）

本轮只检查、修复验收缺陷、测试和整理文档，没有新增业务功能，没有提交或推送 Git，也没有创建公网入口、部署云服务或发送真实邮件。基线提交为 0932895，所有修改已写入磁盘但未提交。

## 已完成能力

- 保留注册/登录、访客升级、Argon2id 密码、会话轮换与隔离；新增修改密码、设备列表与撤销、退出全部设备。邮箱验证与找回提供本地可配置流程。
- 自由聊天与独立计算仍可使用，上传文件不会强制所有消息走文档分析。
- TXT/Markdown/文字 PDF/XLSX 上传、身份归属、页码/行号/单元格引用；扫描 PDF 本地 OCR 接口与缺依赖提示。
- 有证据的事实、推断、变更对比；超长资料分批持久化、续跑及跨批次合并，保留分批原文引用。
- 多阶段 DAG 串行/并行/混合依赖、剩余工期与关键路径；自定义工作周、节假日、补班及起算日；延后含义确认。旧两阶段 15→20 流程保持兼容。
- 多任务列表、切换、暂停、继续、附件范围和步骤独立持久化；普通聊天保留附件任务。
- SQLite 版本化迁移、请求去重、跨进程身份租约、维护屏障、一致性备份、停机恢复、失败回滚及恢复中断标记。

## 代码检查与本轮修复

检查原有 19 个修改文件和 15 个新增文件，并复核本轮额外修改。按 API/认证、任务编排、工具与证据、文件解析、前端身份切换、协调/备份及测试进行交叉检查。未发现需要移除的重复文件、临时文件或无关业务修改；虚构账号和示例资料为验收所需。未删除已有成果。

修复内容：新建任务后日历参数被覆盖；延后追问未正确标记等待；解析超时的子进程清理兜底；备份回滚逐次检查维护租约；缺失任一业务数据库时禁止发布不可恢复的备份；跨批次合并只接收引用校验后的文本，忽略未经引用校验的自由摘要；拒绝“一百一”等歧义数量；默认关闭活跃调用链中聊天/记忆调试输出；上传提示补上 XLSX。

为默认日志修复额外修改 config.py、history_node.py、memory_node.py、tool_executor.py、calculator.py 五个现有文件，均围绕保护已有内容。显式启用 Python DEBUG 日志仍可能输出诊断内容，不应在真实资料环境中启用。旧未接入当前 graph 的 planner.py、memory_load.py 保留原样。

检查了身份派生、文件/任务归属、Origin、严格参数、引用真实位置、受控工具列表、有限模型重试、解析规模与超时、备份校验与恢复边界。此检查与测试不等于独立安全审计。

## 实际执行的最终测试

环境：Windows、Python 3.11.4、Node.js 24.18.0、Vite 8.2.2、qwen2.5:7b（Ollama 模型 ID 845dbda0ea48，4.7GB）、websockets 16.1.1、httpx 0.28.1。测试采用临时数据库、虚构账号与资料，未对真实用户库执行恢复。

| 命令（在仓库根目录） | 最终结果与范围 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` | 9/9 通过，最终 1.845 秒；排程、日历/歧义、Excel、OCR替身/缺依赖、原记忆测试 |
| `npm --prefix frontend run lint` | 通过 |
| `npm --prefix frontend run build` | 通过，Vite 生产构建 123ms |
| `.\.venv\Scripts\python.exe -m pip check` | 通过，无依赖冲突 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.auth_evaluation` | 通过，认证、令牌、并发注册、迁移/回滚、访客保留、跨浏览器与隔离、Origin、限速 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.local_evaluation` | 离线通过：附件总结、原两阶段15→20、缺资料/冲突/参数、注入、独立进程故障恢复、PDF与Demo接口 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.chat_routing_evaluation` | 通过，附件存在时普通聊天、独立计算、模式与任务保留 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.network_evaluation` | 通过，最终1.447秒；新任务日历、7→12、延后确认、临时计算故障复用证据 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.advanced_evaluation` | 通过；综合摘要、多批次合并、无依据摘要拒绝、多个任务交替、暂停、旧任务、越权 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.account_management_evaluation` | 通过；密码/会话撤销，邮箱与找回使用本地邮件替身，非真实发信 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.concurrency_backup_evaluation` | 通过；真实独立进程互斥、请求去重、维护屏障、拒绝在线恢复、不完整备份拒绝、失败回滚、全量恢复及原任务续算 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.multiworker_evaluation` | 通过，两个真实Uvicorn worker PID 11224/22940；共享账号、历史、checkpoint、附件、15→20追问，模型为替身 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.auth_browser_evaluation` | Edge 无头真实浏览器通过；注册→上传→聊天→退出→登录→刷新，账号切换延迟响应隔离、过期草稿、设备/任务入口；1280及390宽度无横向溢出 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.network_evaluation --ollama` | 真实本机模型通过，15.571秒，上传→skill→中文数字提取→并行计算/日历→引用→歧义追问→7→12 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.summary_ollama_evaluation` | 真实本机模型通过，独立脚本17.127秒；五份虚构资料跨批次归纳、合并、五个引用。此前同场景stdin试跑17.916秒 |
| `.\.venv\Scripts\python.exe -X utf8 -m tests.local_evaluation --ollama` | **未通过**：摘要31.446秒后因两次引文不匹配暂停，断言无引用失败；本次该套件后续两阶段步骤未执行 |
| `git diff --check` | 通过，仅有原工作区LF/CRLF提示，无空白错误 |

失败实例：原文“截至 2026-04-10 收工，第一阶段剩余 4 个工作日，第二阶段剩余 8 个工作日。”，模型截取前半句并自行增加句号，已不是原文的连续片段。两次格式/证据校验均拒绝后保存待续任务。这是模型稳定性问题，不放宽原文验证来伪造通过。历史版本曾跑通该套件，但历史结果不能替代本次失败。

所有已启动测试均已结束；没有未结束、卡住或无限重复的测试。保留有限重试（每次模型格式最多两次、每轮工作流最多六步），不保证模型每次都成功。

## 双 Worker 与备份验收边界

双 worker 是真实两个进程的本地HTTP冒烟测试，使用替身模型。测试为验证Demo共享数据，显式转发Secure Cookie到loopback HTTP；这不代表真实公网HTTPS链路验收。未做长期并发压力、进程在任意写入点崩溃的穷举或共享网络磁盘验证。登录限速仍为每进程内存计数，重启会清空；默认启动仍保留单worker。

备份测试保存账号、历史、附件、长期记忆、checkpoint与待计算任务，恢复后撤销旧令牌，重新登录，禁用模型仍能只补做计算并访问原文。恢复只允许停完全部worker；所有写入方必须为当前版本并经过协调层。外部脚本直接写库、旧服务不受屏障保护。协调库不恢复。恢复中断标记要求重新完成恢复。操作真实资料前仍应保存整套离线副本。

迁移3/4/5和已有迁移以临时旧库/旧JSON验收，重复执行不重复导入。真实用户库在后续启动新后端时才升级，本轮没有替用户重启或迁移其正在使用的数据。

## 待验证与外部环境

- **Tesseract/中文语言包未配置，真实扫描OCR未验证**。只有OCR替身、来源标记和缺依赖路径通过；Poppler工具也需在运行环境中可定位。
- **SMTP未配置，真实邮件未发送**。本地替身证明令牌逻辑通过；需STARTTLS服务、发件人与凭据后再验证真实送达、垃圾邮件及失败重试。
- 未创建/复验公网Tunnel、真实移动设备、跨机器部署。浏览器只做脚本化功能及尺寸检查，不宣称完成所有视觉细节的人工审美验收。
- 任意自然语言提取、跨文件复杂指代、漏提取和综合推断仍可能失败；逐字证据校验不能证明模型语义完整。当前工期数值绑定仍依赖“阶段…剩余…工作日”等明确表达；小时、资源容量、自动地区法定假日、加密PDF、Excel公式重算未实现。
- 原两阶段“延后一周”兼容既有增加时长口径；多阶段明确确认增加时长或推迟开始。“周”按配置工作周长度换算，不能把所有地区周末当假日。
- 当前轮次暂停而非强行中断工具，重试纯计算可能重做；没有承诺邮件、任意外部写入等副作用的全局exactly-once。

## 从开机启动与演示

完整安装、Ollama/OCR/SMTP变量、备份命令见README，保持仓库根目录启动。

1. 打开Ollama，`ollama list` 确认 qwen2.5:7b；首次需要 `ollama pull qwen2.5:7b`。
2. 首次或更新依赖：`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`、`npm --prefix frontend ci`。浏览器测试额外需要 `websockets==16.1.1`；缺虚拟环境先 `py -m venv .venv`。
3. 后端PowerShell：

```powershell
cd <LOCAL_PROJECT_PATH>
$env:MY_AGENT_MODE = 'local'
$env:MY_AGENT_MODEL = 'qwen2.5:7b'
$env:MY_AGENT_OLLAMA_URL = 'http://127.0.0.1:11434'
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

4. 第二个PowerShell：

```powershell
cd <LOCAL_PROJECT_PATH>
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

5. 打开 http://127.0.0.1:5173，注册虚构账号；上传 demo_files/network-plan.md，问“计算剩余工期”，预期7工作日。追问“第二阶段再延后一周呢”，再回复“增加时长”，预期12工作日。点击引用核对。
6. 新建任务，问“总结所有文件”，检查事实/推断/引用；发送“1+4=?”或选择自由聊天，验证不被附件阻塞。切换旧任务继续追问，退出/再登录/刷新检查附件与历史。
7. 故障演示：停止后端，在后端终端设置 `$env:MY_AGENT_FAIL_CALCULATOR_ONCE = '1'` 再启动。新建工期任务，首次计算提示故障；Ctrl+C停止并重启，原账号发送“继续任务”，复用证据续算。演示结束用 `Remove-Item Env:MY_AGENT_FAIL_CALCULATOR_ONCE` 关闭该开关。不要对已有服务执行随意kill。
8. 备份恢复请先用虚构测试验收命令验证，不要直接恢复真实用户库。README备份/恢复命令会涉及覆盖，恢复前停止全部worker并留存副本。

## 修改与新增文件清单

以下是最终工作区清单，不代表已提交。原34个文件全部保留，另有5个日志隐私修复文件、1个可重复真实模型测试和本报告。

### 修改 24 个文件

- `README.md`
- `docs/local-evaluation.md`
- `frontend/src/App.css`
- `frontend/src/App.jsx`
- `requirements.txt`
- `src/agent/document_agent.py`
- `src/agent/graph.py`
- `src/agent/history_node.py`
- `src/agent/memory_node.py`
- `src/agent/schedule.py`
- `src/agent/skills.py`
- `src/agent/tool_executor.py`
- `src/config.py`
- `src/memory/store.py`
- `src/server/api.py`
- `src/server/auth.py`
- `src/server/documents.py`
- `src/server/history.py`
- `src/server/schedule_tasks.py`
- `src/server/session.py`
- `src/tools/calculator.py`
- `src/tools/registry.py`
- `tests/attachment_evaluation.py`
- `tests/auth_browser_evaluation.py`

### 新增 17 个文件

- `demo_files/network-plan.md`
- `docs/final-acceptance.md`
- `frontend/src/AccountPanel.jsx`
- `src/server/account_management.py`
- `src/server/backup.py`
- `src/server/coordination.py`
- `src/server/file_parsers.py`
- `src/server/request_log.py`
- `src/tools/project_schedule.py`
- `tests/account_management_evaluation.py`
- `tests/advanced_evaluation.py`
- `tests/concurrency_backup_evaluation.py`
- `tests/multiworker_evaluation.py`
- `tests/network_evaluation.py`
- `tests/summary_ollama_evaluation.py`
- `tests/test_file_parsers.py`
- `tests/test_project_schedule.py`
