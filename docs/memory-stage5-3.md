# 第五阶段第三小阶段：长期记忆管理

日期：2026-11-24。范围：原 MemoryStore 上增加管理 API、React 面板与自动记忆开关。没有新增依赖、第二套记忆数据库或 Agent，没有修改 context.py、Planner、Tools、RAG、聊天历史结构，没有提交或推送 Git；未开始下一小阶段。

## API

所有接口从现有 HttpOnly Cookie 解析身份，访客和账号都支持；不接受请求体 user_id。未知或其他身份的记忆均404；认证缺失/过期401。修改接口继承 Origin 白名单、application/json 校验和现有身份协调锁；严格 Pydantic 请求体拒绝额外字段和类型转换。

| 方法与路径 | 请求 / 行为 |
| --- | --- |
| GET /memories | 返回 items、has_more；可用 include_deleted=true，默认隐藏软删除；最多200条 |
| GET /memories/{id} | item、source、versions、candidates；原消息来源同样按身份查询 |
| PATCH /memories/{id} | {"value":"王五","revision":1}；非空，最多6000字符，版本不匹配409 |
| DELETE /memories/{id} | JSON {"revision":2}；软删除，重复旧版本或已删除记录409 |
| GET /memories/settings | automatic_enabled、revision；未设置时默认开启、版本0 |
| PATCH /memories/settings | {"automatic_enabled":false,"revision":0}；设置版本比较，冲突409 |

详情最多返回最新50个修订和20个待确认候选。列表不是新的分页系统，更多记录会显示明确提示。接口不提供任意创建键、改归属或绕过墓碑恢复的入口。编辑现有待确认条目可明确确认其值；已删除条目不可直接编辑。

## 存储、修订和来源

继续使用原 memory.db、原 memories 表和 MemoryPolicy 事务策略。增量迁移记录本库版本2，新增：

- memory_settings：按身份保存自动开关、版本、更新时间；版本同时作为自动提取代次屏障。
- memory_management_actions：服务端生成随机操作 ID，保存管理动作、值、预期版本、时间和原聊天顺序边界。
- memory_revisions：按身份/键/修订号保存不可覆盖的 JSON 快照；当前有效值仍从 memories 读取。
- memories / memory_events 增加 management_action_id；memories / 墓碑增加 source_floor；墓碑增加 restored_generation。

手动管理使用 user_management 来源、user_confirmed 确认状态，source_message_id 留空，不能伪造一条聊天消息。source_floor 只是管理时该身份最新原聊天 ID 的顺序边界，不是来源。详情单独展示管理操作或真实原消息。旧记录、未知时间及来源保持原样；只快照升级时实际存在的当前版本，不能恢复之前未保存的正文版本。

编辑在 BEGIN IMMEDIATE 中比较 expected_revision、保留旧快照、写入新值及新修订、动作和事件。旧值不能继续通过 get/search 读作当前事实。手动移除的旧值同样建立墓碑，避免旧提取重新合并进来。并发 Worker 的旧版本请求409，不能最后写入者静默覆盖。

删除保留当前行和审计，标记 deleted；有效记忆读取立即排除。全键墓碑、来源顺序边界及自动提取代次共同防止旧 checkpoint 和延迟写入复活。主图仍从实时 memory.db 读取，不信任旧 state.memory。UI 切换身份/关闭面板取消请求并丢弃旧响应；过期时沿用原登录提示与聊天草稿保护。

## 自动开关

记忆节点先读取开关，暂停时不执行规则提取；事务写入再校验开关及代次。请求由服务端捕获 memory_generation，手动编辑/删除或开关切换会推进代次，延迟提取不能用旧代次写回。已有记忆读取不受暂停影响，手动管理可继续。恢复后只处理新消息，不扫描暂停期间历史。

这是保守的身份级屏障：并发管理可能使同身份其他尚未落库的旧代次提取被丢弃，不自动重放。管理与聊天沿用原同身份请求互斥，冲突可能在协调层先返回409；完成中的请求不会被强制中断。对已经送给模型的上下文没有撤回能力。

## 实际验收

全部核心验收使用虚构信息、独立临时 SQLite 和浏览器配置，不读取个人 PDF，不在个人库执行迁移演练。

| 检查 | 实测结果 |
| --- | --- |
| 修改前基线 | 原72/72单元通过 |
| 最终单元 | 83/83通过，6.568秒；新增11项管理策略/迁移/屏障用例 |
| memory_management_evaluation | API归属、严格请求、Origin、CAS、修订/来源、暂停时聊天/计算/显式和Planner RAG、恢复开关、删除/回放、刷新、过期、完整备份恢复通过 |
| memory_management_workers_evaluation | 两个真实API进程：同版本并发编辑与删除均一个200、一个409；无覆盖，开关跨进程生效，旧记忆并发回归通过 |
| memory_management_browser_evaluation | 实际Edge：注册、查看来源、编辑/修订、冲突保留草稿、删除、暂停/恢复、刷新、旧身份延迟响应丢弃、过期保留聊天草稿通过 |
| 布局 | 实际截图检查1280×900、390×844，通过，无横向溢出；截图在忽略目录 .demo-runtime/memory-management-ui |
| 既有核心回归 | metadata、context、auth、account_management、model_prompt、planner、chat_routing、attachment、document_preparation、abstract、network、advanced、rag_planner、rag_fault、concurrency_backup 全部通过 |
| 真实模型 | Qwen2.5:7b两轮聊天7.160秒；embeddinggemma + Qwen2.5:7b跨文档/无依据/PDF页码/DOCX段落表格回归26.437秒通过 |
| 前端 | lint无警告，生产构建通过；原auth浏览器及真实模型自动RAG浏览器流程也通过；没有新增前端依赖 |
| 环境与依赖 | Windows、Python3.11.4、Node24.18.0、npm11.16.0；pip check无依赖冲突 |

真实模型回归中出现过 answerable 与证据矛盾的输出，现有证据校验与两次上限重试处理成功；不宣称模型每次都正确。相关性门槛保持0.65，中文变体的召回限制仍保留。

验收期间修正了两个测试前置条件：两个 TestClient 同时启动使嵌入式 Chroma 按原规则拒绝多 Worker，改为一个生命周期下的多客户端；访客没有“退出账号”按钮，浏览器脚本先注册虚构账号再验收退出。一次双Worker业务断言通过后，受限环境无法回收子进程造成清理超时；仅关闭本次测试进程树后，在允许回收测试子进程的环境重新完整跑通。没有放宽 Chroma、身份或引用验证。

最终检查也补齐了纯单元设置测试的协调库临时路径：早期该测试的记忆库已隔离，但协调租约曾使用默认协调库；没有写入个人记忆或聊天正文，没有擅自清理已有数据。最终83项复跑已显式隔离本轮设置测试的协调库。

## 复现

按 README 开机步骤启动 Ollama、8000后端和5173前端。登录/访客 → 自由聊天“我叫李四” → 侧栏“长期记忆” → 选择姓名 → 改为王五并保存 → 查看修订 → 暂停自动记忆 → 聊天“我喜欢苹果” → 重新载入确认没有新增爱好 → 恢复开关 → 聊天“我喜欢篮球” → 核对新记忆 → 勾选删除范围并删除姓名 → 刷新核对。

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_*.py" -q
.\.venv\Scripts\python.exe -X utf8 -m tests.memory_management_evaluation
.\.venv\Scripts\python.exe -X utf8 -m tests.memory_management_workers_evaluation
npm --prefix frontend run lint
npm --prefix frontend run build
.\.venv\Scripts\python.exe -X utf8 -m tests.memory_management_browser_evaluation
```

浏览器脚本复用现有 Edge/CDP 测试依赖和独立配置；不连接用户正在使用的浏览器。双进程测试需要允许回收自己启动的测试进程。

更新前停止全部旧写进程并使用现有 `python -m src.server.backup backup <新目录>` 备份；恢复仍需停全部Worker并使用原 `restore --confirm-restore` 命令。原SQLite backup覆盖新增管理设置、修订、操作和墓碑，已实际恢复校验。恢复删除前的旧备份仍回到旧状态，不能保留备份之后的删除。

## 本小阶段文件

新增：src/memory/management.py、src/server/memories.py、frontend/src/MemoryPanel.jsx、frontend/src/MemoryPanel.css、tests/test_memory_management.py、tests/memory_management_evaluation.py、tests/memory_management_workers_evaluation.py、tests/memory_management_browser_evaluation.py、本文。

修改：src/server/migrations.py、src/server/api.py、src/memory/store.py、src/memory/policy.py、src/agent/memory_node.py、src/agent/state.py、frontend/src/App.jsx、frontend/vite.config.js、tests/memory_workers_evaluation.py、README.md、docs/local-evaluation.md。仓库中其他阶段遗留的未提交文件保持原状，不列成本阶段新增成果。

## 边界

- 不提供物理擦除、删除原聊天/备份、跨旧备份删除同步或UI恢复按钮。来源详情及修订仍可由本人查看删除前内容。
- 不新增LLM记忆提取，继续前阶段保守规则；不保证任意自然语言都能识别稳定事实。
- 无分页/全量导出、批量操作和管理历史搜索；没有提前开发下一阶段。
- 双Worker是本机有限并发验收，不是压力/高可用保证；旧版本写进程和直接绕过策略SQL不受保护，部署必须统一版本。
- 本轮未复跑共享Chroma Server部署、长期压力、其他浏览器和公网入口。OCR/真实SMTP不在本阶段验证范围。
