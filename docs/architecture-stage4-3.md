# RAG 语义问答后端（2026-11-24）

新增 retrieval/qa.py；修改 document_agent.py、.env.example、tests/vector_index_evaluation.py；新增 tests/test_rag_qa.py。未修改 documents 核心结构、长期记忆、Planner、上传系统或前端，未提交推送。

一般 document_qa 在启用 MY_AGENT_RAG_ENABLED 时：原服务验证身份与文档范围 → 查询版本匹配的 READY 索引 → 余弦门槛过滤 → 复用 answer_documents 的 ChatPromptTemplate 和结构化引用校验 → 再校验文件仍存在、归属及索引代次 → 返回答案与引用。任务保存 retrieval_audit，包含命中文档/片段/代次、分数和是否接受，不保存模型思维。

摘要、总结、缩写、版本、变更、工期等需求保留原全文流程，不用 Top-K 替换。当前识别使用保守词表，复杂措辞可能误分流，需要后续评测；本轮不做完整 Planner 集成。旧任务已有 sources 时继续旧流程，避免破坏恢复。

MY_AGENT_RAG_MIN_SIMILARITY 默认0.65，MY_AGENT_RAG_TOP_K默认4（1–12）。分数是1减余弦距离，不是答案置信度。无合格片段直接拒答，不调用生成模型；有片段但缺具体答案由原结构化模型返回空证据拒答。引用只能来自提供片段，逐字原文匹配；文件名/位置由服务端来源生成。该验证不能证明模型每个自然语言结论均被引文逻辑蕴含，仍需人工核对。Embedding/Chroma故障进入可继续状态，不退回无证据生成。

测试：单元32/32（4.983秒）、前端lint/构建通过。真实Chroma替身Embedding脚本通过幂等、权限隔离、删除、故障、模型失效与三进程重启测试。真实embeddinggemma中文4文件8问Top-1为8/8；真实Qwen问答正确回答十五天及主管并引用leave.txt L1，火星问题无依据拒答；最终完整脚本10.488秒通过。初次真实脚本业务断言通过但Windows临时库清理失败，增加垃圾回收及短暂等待后复跑退出码0，没有隐藏清理错误。

复现：按README单Worker启动Ollama、后端和前端，上传虚构制度文件，等待可检索，询问“休假需要找谁申请？”。更确定的隔离测试：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -m tests.vector_index_evaluation --real --qa
```

待验证：真实多文件联合结论、PDF/DOCX向量问答页码端到端、缺少某个具体答案的同主题问题、复杂提示注入和浏览器完整RAG流程；已有底层位置/归属测试不能替代这些验收。0.65下8问中部分正确Top-1低于门槛，因此存在保守拒答，不宣称8问全部能够生成回答。当前不是通用质量保证，尚需扩展跨文档及困难负例评测。嵌入式Chroma仅单Worker。
