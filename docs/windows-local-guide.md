# 🪟 Windows 从零手动运行

## 1. 准备

安装 Python 3.11（勾选 PATH）、Node.js 24 LTS（含 npm）、Ollama Windows。已验收本机版本为 Python3.11.4、Node24.18.0、npm11.16.0；不是所有其他版本均已测试。

解压干净源码候选到自己的目录，在资源管理器地址栏输入 `powershell` 回车。以下命令均从项目根目录执行，必须能看到 README.md、requirements.txt、frontend 和 src。不要进入旧仓库或复用他人的数据库。

```powershell
py -3.11 --version
node --version
npm --version
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
npm --prefix frontend ci
```

不必激活虚拟环境，不必修改 PowerShell 执行策略。安装需要网络；失败时保留错误信息，不要随意升级所有依赖。

## 2. 启动 Ollama

从开始菜单启动 Ollama，再检查：

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

需要 qwen2.5:7b 与 embeddinggemma（标签可能为 embeddinggemma:latest）。如果模型缺少，需要用户自行下载：

```powershell
ollama pull qwen2.5:7b
ollama pull embeddinggemma
```

这些下载命令不必每次开机执行。如果服务未运行，可单独打开一个终端执行 `ollama serve` 并保留；11434已占用通常意味着服务已经运行，不要重复启动。

## 3. 后端终端

在项目根目录打开 PowerShell：

```powershell
$env:MY_AGENT_MODE='local'
$env:MY_AGENT_MODEL='qwen2.5:7b'
$env:MY_AGENT_OLLAMA_URL='http://127.0.0.1:11434'
$env:MY_AGENT_EMBEDDING_MODEL='embeddinggemma'
$env:MY_AGENT_EMBEDDING_URL='http://127.0.0.1:11434'
Remove-Item Env:MY_AGENT_CHROMA_URL -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m uvicorn src.server.api:app --host 127.0.0.1 --port 8000 --workers 1
```

最后一行保持运行，不要关闭窗口。若自己的 `.env` 配置了共享 Chroma，请检查并按该服务配置启动；上面移除的是当前终端环境变量，不会覆盖 `.env`。全新候选没有真实 `.env`，默认使用嵌入式 Chroma。`.env.example` 只是模板，无需复制即可按上述环境启动。

Local 模式的 memory.db、local_sessions.db 在项目 data/，checkpoint 在启动目录 agent_checkpoints.db，协调库及向量目录按应用路径派生。必须从根目录启动。它们不是源码，不要上传 GitHub。Local 的三个路径不是通过 Demo 环境变量覆盖；本教程使用新解压目录自然隔离。

## 4. 前端终端

另开 PowerShell，进入同一个项目根目录：

```powershell
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

浏览器访问 http://127.0.0.1:5173。不要随意换前端端口：Origin白名单和Vite代理按当前配置工作。新终端健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

`/health` 不经 Vite 代理，直接访问8000。保持前后端窗口开启。通常是两个终端；仅当 Ollama 未在后台运行时需要第三个终端。

## 5. 手工验收

- 进入访客或注册虚构账号，退出后重新登录。若“访客会话已变化”，显式进入新访客，注册时取消保留访客资料再试。不要删除数据库解决。
- 普通聊天：“你好，请介绍你自己”；再问“刚才我问了什么”。刷新确认历史保留。
- 工具：“先计算100+200，再将结果乘以3”，应为900；“现在几点，再计算2+3”，应有时间与5。
- Memory：“我叫林舟”，再说“我的名字改为林澈”；打开记忆管理核对内容和版本。新建会话后询问姓名，历史独立而长期记忆共享。
- 创建 UTF-8 `leave.txt`，正文“员工每年有10天年假，由部门经理审批。”；创建 `backup.txt`，正文“数据库恢复必须由管理员执行并核对数据完整性。”
- 页面上传，等待解析及索引可检索；选择文件问答，问“年假多少天由谁审批？谁有权恢复数据，需要检查什么？”；应有四要点及两个来源，点击查看原文。
- 问“年假折现每一天多少钱”，资料没写应说明不足；删除leave后再次询问年假，不应继续生成该文件的新引用。历史回答文本不是自动擦除的数据库原文。
- file_reader是内部显式授权工具；不要用聊天要求读取任意本机路径来演示。其节点调用本轮单独验证，不冒充浏览器功能。

## 6. 关闭与下次开机

前端、后端各自窗口按 Ctrl+C，等待命令提示符返回。模型调用尚未返回时可能需要等待，不能把浏览器超时视作执行已经结束。Ollama由桌面托盘退出或在serve终端Ctrl+C；不要结束不属于本项目的进程。

下次开机只需要启动Ollama、打开项目根目录、分别执行第3和4节；不用重复安装依赖、下载模型。浏览器始终使用同一host（127.0.0.1与localhost的Cookie不通用）。

## 7. 常见问题

|现象|处理|
|---|---|
|8000/5173被占用|查找自己此前窗口并Ctrl+C，不盲目结束别人的服务，不随意换代理端口|
|Failed to fetch|检查后端、8000健康、前端5173地址和启动终端日志|
|模型404或连接失败|检查ollama list、11434服务、聊天和embedding两个模型各自配置|
|索引失败|查看文件状态与错误；确认embedding服务正常，再使用重新索引；不要重建旧数据库|
|扫描PDF无文字|需要Tesseract及PDF渲染工具；当前机器真实OCR未验收|
|邮件未收到|需要配置SMTP，真实发送未验收；不要把凭据写进模板或提交Git|
|超时仍等待|同步推理只能协作式结束，实际返回后才允许终结并重试|
|WinError10054|记录发生时间、页面是否失败及后端日志；不自动认定数据丢失|

Dockerfile存在，但本轮Docker daemon未运行，未验证容器安装。双Worker有限测试不等于生产并发验证。Local演示先用单Worker；Demo需要HTTPS无端口Origin与Secure Cookie，不通过关闭校验来启动。

## 8. 可重复检查

```powershell
npm --prefix frontend run lint
npm --prefix frontend run build
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

完整单元测试需要安装requirements，测试结果以当次输出为准。不要把替身模型测试当作真实模型或浏览器验收。
