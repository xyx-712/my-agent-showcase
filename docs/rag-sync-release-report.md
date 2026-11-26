# RAG 修复同步与发布包验收（2026-11-24）

## 版本确认与同步范围

来源 my-agent-zip-acceptance-20261124，目标 my-agent-release-20261124，均无 .git，均有各自 .venv。同步前核对发布qa.py与原最终ZIP一致，避免覆盖其他修改；两个副本MIT和第三方声明一致。只同步src/retrieval/qa.py与新增tests/test_rag_lexical.py，不复制其他源码、安装环境或数据库。

同步后与上个包的逐文件校验记录比较，唯一原有文件变化是qa.py；发布文档随后按本轮要求单独追加，保留既有内容。requirements、.env.example、LICENSE、THIRD-PARTY-NOTICES、Vite原始许可未改。

## 发布副本实际验收

- pip check通过；发布副本环境独立，导入不依赖原仓库。
- 新词法、原RAG问答、Embedding、文档来源、RAG Planner、多会话合计29项通过，8.635秒。
- 真实qwen2.5:7b、embeddinggemma与Chroma，使用新虚构访客上传同一原失败文本，索引READY后执行4场景：

| 场景 | 相似度 | 候选路径 | 最终结果 |
| --- | --- | --- | --- |
| 原失败问题 | 0.6372072697 | 词法：年假、申请 | 回答15天与主管，引用文件及原文核对通过 |
| 正常明确提问 | 0.8475810885 | 语义 | 正确引用 |
| 无关火星问题 | 0.1699898243 | 不接受 | 拒答、无引用 |
| 年假折算现金但原文无答案 | 0.5559935570 | 词法候选 | 回答阶段拒答、无引用 |

语义门槛仍为0.65，相似度没有改高。accepted只表示证据候选，不代表足以回答。真实结果保存在本机.demo-runtime/rag-sync/real-result.json，不进入ZIP。

## 修改文件

src/retrieval/qa.py；新增tests/test_rag_lexical.py；README.md；RELEASE-PREPARATION.json；新增本文；RELEASE-FILES.txt与RELEASE-SHA256SUMS.txt。不修改无关业务逻辑或依赖，不覆盖原仓库、旧ZIP和失败记录。

## 包与限制

使用新名称my-agent-source-20261124-rag-fix-r1.zip，保留MIT与第三方声明；只按显式清单打包，排除.git、虚拟环境、node_modules、dist、数据库/WAL、用户数据、模型和运行目录。校验包内清单、CRC和逐文件SHA-256。

词法分支是有限启发式，只复核当前向量top-k，不能保证完整召回或所有自然语言问法正确。没有重跑完整测试套件、浏览器、Docker、双Worker、OCR/SMTP或公网；8项依赖许可证仍待审核。尚未把这个新ZIP再次解压到全新环境验收，不能将本轮目标副本回归说成新ZIP全环境验收通过。

未提交、推送、部署或删除既有数据库。
