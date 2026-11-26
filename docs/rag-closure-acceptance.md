# ✅ 第四阶段第三小阶段收尾验收

日期：2026-11-24；Windows，本机 embeddinggemma（768维）、Qwen2.5:7b、嵌入式 Chroma 单 Worker。测试全部使用独立临时 SQLite、向量目录、浏览器配置和虚构资料，没有读取个人文件，没有提交推送 Git。

## 四项验收

| 项目 | 实测结果 |
| --- | --- |
| 跨文档联合回答 | annual.txt 提供十五天额度，approval.txt 提供提前三天向主管申请；同一问题命中两份文件，分数约0.8003/0.8576，回答涵盖双方事实，两份引用分别归属正确文件。测试强制断言引用集合等于两份文件，不接受单文件冒称联合。 |
| PDF位置 | 虚构两页PDF，答案仅在第二页；实际回答引用第2页，未引用第一页介绍。 |
| DOCX位置 | 正文段落1提供12–13点供餐，表格1/行1/列1提供二十元价格；最终两问分别引用段落和表格，page均为空，引用正文与保存原文逐字匹配。 |
| 同主题无依据 | 问“未休年假折算多少元现金”，原文仅额度/申请流程；相近资料分数0.6524，可通过门槛但不含答案。最终明确没有可核对依据，citations为空。证明相关性门槛不能代替答案充分性判断。 |

真实后端完整脚本最终25.729秒，退出码0。浏览器使用同一生产构建、真实上传与真实模型，PDF页码（页面测试为第1页）、DOCX段落与表格均能经现有引用按钮打开原文面板，面板包含对应位置和原文。现有组件是打开文件并显示来源片段，**不是自动滚动/高亮特定子片段**，本轮未添加此类界面能力。

## 阈值评估

沿用4份中文制度文档与8问，增加2个同义正样本（“休年假要提前几日报批”“恢复数据库由谁负责”）、3个无关负样本（火星氩气、量子纠缠装置、巴黎铁塔），另单独验证上述同主题困难负例。top-k保持4，没有为通过验收改变默认阈值。

| 门槛 | 正样本保留正确来源 | 无关负样本通过数 |
| --- | --- | --- |
| 0.50 | 10/10 | 0/3 |
| 0.55 | 9/10 | 0/3 |
| 0.60 | 6/10 | 0/3 |
| **0.65（默认）** | **5/10** | **0/3** |
| 0.70 | 4/10 | 0/3 |
| 0.75 | 1/10 | 0/3 |

这里是“门槛过滤后正确来源召回”，不是答案准确率或完整拒答率；低于门槛可能剩下其他片段，不能直接将其视为整问拒答。原8问不设门槛Top-1仍为8/8。当前0.65有明显过度保守风险；低门槛在这个小负例集上没有误检，仍不足以证明更安全。同主题负例已经说明高分也可无答案。**暂保留0.65，不推荐凭这组小样本直接调低；后续应增加行业困难负例与人工标注再校准。**

## 定位到的问题与修复

1. 模型把缺失答案写成assumption，或把“文档未记载金额”附在仅说明额度的引文上。RAG专用结构增加answerable；要求只有直接证据支持的fact可作答案，没有答案时两个证据列表为空。原摘要/全文结构默认保持。
2. 首次按answerable=false清空结果，会将模型矛盾输出中的正确表格事实一起丢弃；诊断记录显示“无法回答”与“每份二十元”同时出现。最终改为**拒绝矛盾字段并使用原最多两次校验尝试**，不静默修正布尔值，不放宽原文验证。真实表格问答与专门单元回归最终通过。
3. 中途浏览器测试在表格问答处等待引用超时；当时后端拒答，页面没有引用可点，并非上传失败。修正后一轮真实浏览器通过。另一次受限运行的Edge连接关闭，随后使用独立浏览器运行权限验收，未操作用户浏览器配置。

失败日志与最终诊断保留在忽略目录 `.demo-runtime/rag-closure*.txt`、`rag-browser*.txt`，不可把中途输出中的PASS文字当作整体成功，最终以进程退出码和断言为准。最终脚本对DOCX两项位置强制断言。

## 回归与复现

- 单元：34/34，最终5.363秒；包含空证据拒答、资料代次变化、全文任务分流、矛盾字段有限重试。
- 离线脚本通过：auth_evaluation、document_preparation_evaluation、abstract_evaluation、network_evaluation、chat_routing_evaluation、planner_evaluation、local_evaluation、advanced_evaluation、concurrency_backup_evaluation、vector_index_evaluation、model_prompt_evaluation、account_management_evaluation、attachment_evaluation。
- 覆盖普通聊天、算式与依赖计算、摘要缩写及摘要恢复、批准版本/工期、身份归属、删除后不可检索、向量失败重试、三进程重启、备份恢复与索引重建。变更后另外复跑摘要和模型提示测试通过。
- 前端lint、生产构建、git diff --check通过；没有修改前端生产组件。
- 真实RAG Edge完整流程最终通过；原auth_browser_evaluation亦通过注册、上传、聊天、退出再登录、刷新和账号切换后延迟响应隔离。

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.rag_closure_evaluation
.\.venv\Scripts\python.exe -X utf8 -m tests.rag_browser_evaluation
```

两个新增脚本使用真实本地模型；浏览器脚本需要本机Edge和已安装的websockets，需先构建前端。Ollama须运行且安装embeddinggemma、qwen2.5:7b。测试关闭生产后台并直接在临时库建索引；浏览器测试显式开启临时后台，从上传等待READY。

本轮文件：新增tests/rag_closure_evaluation.py、tests/rag_browser_evaluation.py及本文；修改src/agent/skills.py、src/retrieval/qa.py、tests/test_rag_qa.py、tests/auth_browser_evaluation.py（可注入模型，结束释放测试向量资源）、README.md、docs/local-evaluation.md。其余工作区改动来自前阶段，全部保留。

限制：小规模中文评测不能推及任意文档；模型answerable和事实蕴含仍可能出错，后端逐字引文验证不等于逻辑证明。DOCX不提供页码，原文面板不做子片段自动高亮。全文任务分流仍是保守词表。没有新增Planner集成、多Worker向量、OCR或真实邮件验收。
