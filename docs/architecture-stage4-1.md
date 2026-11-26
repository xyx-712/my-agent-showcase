# 第四阶段第一小阶段：文档兼容与依赖准备

日期：2026-11-24。仅新增文档适配、DOCX和派生切分，不接入向量库/Embedding，不改Planner、LangGraph、长期记忆、document_agent、API路由或数据库结构。前三阶段未提交修改全部保留。

## 依赖解析与安装

先在原requirements所有精确版本约束下执行pip --dry-run，再检查解析报告后安装。初次无额外约束的解析选择classic1.1.0，要求提升LangSmith，未安装该方案。第二次固定classic1.0.7和原langsmith0.12.4后解析通过，再安装锁定版本。

新增直接依赖：langchain-community0.4.2、langchain-text-splitters1.2.0、python-docx1.2.0。

必要传递依赖一并锁定：langchain-classic1.0.7、aiohttp3.14.5、httpx-sse0.4.3、lxml6.1.3、numpy2.4.6、pydantic-settings2.16.3、SQLAlchemy2.1.9、aiohappyeyeballs2.7.1、aiosignal1.4.0、attrs26.1.0、frozenlist1.8.0、multidict7.2.1、propcache0.5.4、yarl1.25.1。classic仅为community所需包，没有引入新Agent。

保留原版本：langchain-core1.6.3、langchain-ollama1.1.0、LangGraph1.2.11、Pydantic2.13.5、pypdf7.1.1、LangSmith0.12.4。安装后pip check通过，community TextLoader/PyPDFLoader、RecursiveCharacterTextSplitter及python-docx实际导入通过。community导入有包自身的弃用提示，本轮保留用户指定依赖，后续迁移需另行确认。

解析报告位于被Git忽略的.demo-runtime/rag-deps-resolution.json和rag-deps-pinned.json。初次普通权限联网失败后改用许可的网络执行，没有持续重复失败。

确认chromadb与langchain-chroma未安装，无Embedding实例或模型下载。

## 实现与位置语义

- SourceLoader继承LangChain BaseLoader，将原解析器结果统一为Document，完整复制来源元数据，不重新解析旧附件。load_document仅接收名称和文件字节并先走parse_document；load_owned_document先校验服务端身份和文件归属。没有开放磁盘路径、URL或新API。
- TXT/Markdown保留既有行号，PDF保留既有1起始页码及OCR标记，XLSX保留工作表/区域与公式缓存说明。
- DOCX使用python-docx按正文元素顺序读取：段落1 → 表格1的行列 → 段落2。段落编号包含空段落占位，表格行列为1起始。Word无稳定分页，page=None。长段落/单元格按1800字符分为规范片段，并保留其在原段落或单元格文本中的offset_start/end。
- DOCX沿用5MiB、每身份12文件/180000字符、每文件60000字符、子进程60秒；额外限制ZIP2000项、展开总量30MiB、单项10MiB、压缩比1000；正文块10000、表格行10000/列200/总单元格50000，宏拒绝。错误/空/损坏文件不会存入可检索记录。
- 派生切分默认800/100，size范围1–6000且overlap小于size，最多5000片段。保留parent_id、parent_char_start/end、切分版本及配置；DOCX增加source_char_start/end，其他文本增加子片段行号。
- 每个派生正文都验证等于parent_text[start:end]。位置为Python Unicode字符、左闭右开，映射到保存的规范父文本，不承诺原文件字节偏移。旧原文的格式归一化和位置口径保持不变。
- parent_id包含文件身份、文件名及完整规范片段的哈希；chunk_id再包含切分版本/配置/位置。相同输入重跑ID相同，切分或内容变化ID改变。仅返回派生Document，不写SQLite、不改任务快照。
- 前端仅扩展.docx选择、类型提示和段落/表格引用显示，无新页面或新工作流。

## 本阶段文件清单

修改：requirements.txt、src/server/documents.py、src/server/file_parsers.py、frontend/src/App.jsx、tests/auth_browser_evaluation.py、README.md、docs/local-evaluation.md。

新增：src/retrieval/__init__.py、src/retrieval/loaders.py、src/retrieval/splitter.py、tests/test_retrieval_documents.py、tests/document_preparation_evaluation.py、本记录。

## 验收结果

基线：原单元21/21，1.626秒。

改造后：

- 单元27/27，最终5.178秒；TXT、PDF、MD、XLSX、DOCX段落/表格顺序、空/损坏/超限/宏/压缩膨胀/嵌套表格拒绝、切分参数/稳定ID/重复文本/长段落位置映射通过。
- document_preparation_evaluation通过：DOCX上传/列表/原文/总结/段落与表格引用/删除；跨身份404；错误文件不留半成品；同字节重试复用ID；文件数配额；切分前后原始片段和任务状态完全一致。
- local_evaluation、abstract_evaluation、planner_evaluation、auth_evaluation、chat_routing_evaluation、concurrency_backup_evaluation通过，保留原摘要、两阶段与多步骤工具、提示注入和独立进程任务恢复。
- 前端lint、生产构建通过（134ms）。Edge实际通过DOCX选取、上传、段落/表格位置查看与删除，再通过原注册/聊天/退出/登录/刷新/延迟响应回归。
- pip check通过；未发现Chroma依赖，未调用Embedding。

开发中两项测试问题已修复：重新生成DOCX会改变ZIP时间戳，不能用新生成字节测试“相同文件重试”，现固定同一字节夹具；API测试提前导入单元夹具曾让session捕获默认应用库，现移到临时库配置后，并断言APP_DB位于临时目录。早期该测试生成了独立虚构访客记录，未访问个人附件，也未擅自删除默认库记录；后续API验收使用临时库。本记录不将早期测试表述为完全未触及默认库。

## 如何使用和复现

停止后端，安装锁定依赖后按README原命令启动，前端仍用原Vite命令。选择.docx上传即可，支持普通段落与普通表格；点击原文可查看段落和表格行列，问“总结所有文件”可使用原问答流程。

```powershell
cd <LOCAL_PROJECT_PATH>
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.document_preparation_evaluation
```

## 当前边界

没有向量索引、Embeddings、语义检索或新知识库任务；没有安装Chroma或下载模型。统一接口目前是原安全解析器的LangChain适配，不切换到community的另一套默认解析策略。

DOCX仅处理正文段落及普通表格；嵌套表格明确拒绝，页眉页脚、图片、文本框、修订和批注未验收，合并单元格按逻辑网格引用。没有真实OCR/SMTP或本轮真实Ollama验收；原文问答与摘要测试使用替身，不宣称任意Word语义理解已通过。

未迁移旧片段或旧任务，不提交/推送Git。完成后停止，等待确认第二小阶段。
