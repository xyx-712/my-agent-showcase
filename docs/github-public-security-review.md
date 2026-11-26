# GitHub 公开源码安全检查（2026-11-25）

范围：独立发布副本的原有 186 项显式文件清单、本轮新增文档，以及认证/文件边界相关静态代码。未修改或扫描原仓库；未读取运行数据库、个人附件和原聊天。发布副本不存在 .git，也没有 .env；所以无可审查的本地 Git 历史、索引或远程配置，**原仓库历史是否安全仍未验证**。不能把 .gitignore 当作清除历史的证明。

## 本轮通过的静态检查

- 显式清单未包含 .git、.venv、node_modules、运行数据库/WAL/SHM、checkpoint 数据、模型权重或运行缓存；文件均存在。
- 常见 PEM 私钥、GitHub/provider 令牌格式扫描无命中；这不是任意密码或未知格式密钥均不存在的证明。固定测试口令属于虚构测试数据，不应拿来部署。
- .env.example 作为模板保留，私有 .env 不入清单；业务源码没有在本轮改动。
- 认证静态代码采用 Argon2、服务端身份、令牌摘要与注销，Origin 检查及附件归属保留。单文件上限 5 MiB、数量上限 12；这不等于入口已具备总请求体与全站存储防护。
- Vite 模板原始许可、项目 MIT 与第三方声明保留；未添加用户截图或模型文件。

## 发现及风险分级

必须在公开生产服务前处理：统一入口请求体限制、聊天/上传/访客限速、总体磁盘与身份存储配额；当前认证限速为进程内计数，不是跨 Worker 共享防护。仅本地演示不应宣称公网生产安全。

发布建议：仅从 RELEASE-FILES.txt 复制或打包，切勿直接提交整个发布工作目录；.venv/node_modules 和验收运行数据确实可能留在工作目录但不在候选范围。自定义数据目录也须人工检查，.gitignore 不能覆盖所有部署路径。

历史报告存在机器路径，属于元数据披露风险，不是当前启动依赖。本轮只报告，未篡改历史记录。公开前可由作者确认接受，或另行授权脱敏；列表如下：

- docs/abstract-reference-fix.md
- docs/architecture-stage1.md
- docs/architecture-stage3.md
- docs/architecture-stage4-1.md
- docs/architecture-stage4-2.md
- docs/architecture-stage4-4.md
- docs/architecture-stage4-final.md
- docs/final-acceptance.md
- docs/final-stage7-2.md
- docs/memory-stage5-1.md
- docs/memory-stage5-2.md
- docs/memory-stage5-3.md
- docs/memory-stage5-4.md
- docs/memory-stage5-final.md
- docs/planner-repair-acceptance.md
- docs/rag-closure-acceptance.md
- docs/readme-history-through-stage6.md
- docs/stability-stage6.md

未验证：原始 Git 历史、完整秘密熵扫描、依赖 CVE 审计、渗透测试、真实公网负载/代理行为。不得对原仓库直接执行公开推送后宣称等价于干净源码包。

## 测试证据边界

前轮最新 ZIP 的独立验收为单元测试 144/144、真实功能与安全边界 21/21（其中 RAG 4/4）。这些是既有验收结果，本轮未重跑，不把它们算作本轮新通过。浏览器、Docker、Windows 共享端口双 Worker、OCR、SMTP 的本轮全新验收仍未验证；历史报告通过范围不能替代本轮环境证明。

## 最小发布建议

1. 人工确认历史机器路径和八项许可证剩余义务。
2. 用本轮显式清单生成下一文档修订包，重新检验哈希；旧 ZIP 保持不变，它不含本轮文档。
3. 发布时仅放入清单文件，从新仓库开始的操作需另行授权；不复用原仓库历史作为“干净”保证。
4. 作为本地源码演示可有条件公开；公开托管运行服务需补齐防护与部署验收。
