# 🤖 My-Agent 智能 Agent 系统

> 一个基于 **Python + FastAPI + React** 构建的模块化智能 Agent 应用。

My-Agent 是一个具备 **任务规划、工具调用、执行管理、上下文记忆** 能力的智能 Agent 系统。

用户可以通过 Web 前端与 Agent 交互，系统会自动完成：

- 🧠 任务理解
- 📋 自动规划
- 🛠️ 工具选择
- ⚡ 任务执行
- 💾 历史记录保存
- 📤 返回执行结果


---

# 🏗️ 系统架构


```text
用户
 |
 v
React 前端
 |
 v
FastAPI 后端服务
 |
 v
Agent Graph
 |
 +---- Planner
 |       任务规划
 |
 +---- Tool Router
 |       工具选择
 |
 +---- Tool Executor
 |       工具执行
 |
 +---- Memory System
         记忆管理
 |
 v
Tools 工具系统
```


---

# 🛠️ 技术栈


| 模块 | 技术 |
| --- | --- |
| 🎨 前端 | React / Vite / JavaScript |
| 🚀 后端 | Python / FastAPI |
| 🤖 Agent | Agent Graph / Planner / Tool Router / Tool Executor |
| 💾 存储 | SQLite / JSON History Storage |


---

# 📂 项目结构


```text
my-agent/

├── frontend/                 # React 前端
│
│   ├── src/
│   ├── App.jsx
│   ├── main.jsx
│   └── package.json
│

├── src/                      # 后端核心代码
│
│   ├── agent/                # Agent 工作流
│   │
│   │   ├── history_node.py
│   │   ├── memory_load.py
│   │   └── tool_schema.py
│   │
│   ├── memory/               # Memory 系统
│   │
│   │   ├── database.py
│   │   ├── memory.py
│   │   └── profile_memory.py
│   │
│   ├── tools/                # Tool 系统
│   │
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── schema.py
│   │   └── tool_schema.py
│   │
│   └── server/               # API 服务
│       └── api.py
│

├── tests/                    # 测试代码
│
├── data/                     # 数据存储
│
├── README.md
│
└── .env
```


---

# 🚀 安装运行


## 1. 克隆项目


```bash
git clone https://github.com/xyx-712/my-agent.git

cd my-agent
```


## 2. 启动后端


安装依赖：

```bash
pip install -r requirements.txt
```


启动服务：

```bash
uvicorn src.server.api:app --reload
```


后端地址：

```
http://localhost:8000
```


---

## 3. 启动前端


进入前端目录：

```bash
cd frontend
```


安装依赖：

```bash
npm install
```


启动：

```bash
npm run dev
```


前端地址：

```
http://localhost:5173
```


---

# ✨ 核心功能


## 🤖 1. Agent 工作流


支持：

- ✅ 任务分析
- ✅ 自动规划
- ✅ 工具选择
- ✅ 工具执行


---

## 🛠️ 2. Tool 工具系统


支持扩展新的工具：

- 🔌 工具注册
- 📑 Tool Schema 管理
- 🔀 自动路由调用


---

## 🧠 3. Memory 记忆系统


支持：

- 👤 用户历史记录
- 💬 对话上下文保存
- 💾 SQLite 数据持久化


---

## 🔌 4. 前后端通信


基于 FastAPI API：

- 接收用户请求
- 调用 Agent
- 返回执行结果


---

# 📈 当前版本


## v0.9


新增：

- 🌐 React 前端交互界面
- 🧠 Memory 系统
- 🛠️ Tool 系统
- ⚡ Agent API
- 🏗️ 项目架构优化


---

# 🔮 后续计划


- 🔧 增加更多工具插件
- 🧠 接入大语言模型
- 📚 增强长期记忆能力
- 🤝 支持 Multi-Agent 协作
- 📊 增加任务可视化


---

# 👨‍💻 作者


个人 AI Agent 项目


用于学习和探索：

- Agent 架构设计
- 工具调用系统
- Memory 管理
- 前后端工程化开发