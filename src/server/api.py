from contextlib import asynccontextmanager
import sqlite3
from threading import Lock
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse
from uuid import uuid4
from src.server.coordination import operation, worker_lifetime
from src.server import request_log

from src.agent import graph as general_agent
from src.agent.document_agent import document_turn
from src.server.documents import init_documents, documents, store_document, get_document, MAX_BYTES
from src.config import IS_DEMO, PROJECT_DIR, PUBLIC_ORIGIN
from src.server.history import get_history, get_recent_history, init_history, save_history
from src.server.schedule_tasks import init_schedule_tasks
from src.server.session import ensure_session, init_sessions, require_user, session_user, identity_info
from src.server import auth, account_management as account_ops
from src.tools.project_schedule import WorkCalendar
from src.server.conversations import thread as chat_thread


if IS_DEMO:
    allowed_origins = {PUBLIC_ORIGIN}
else:
    allowed_origins = {"http://localhost:5173", "http://127.0.0.1:5173"}


@asynccontextmanager
async def lifespan(app):
    with operation("startup", exclusive=False):
        from src.server.backup import require_complete_restore
        require_complete_restore()
        init_sessions()
        init_history()
        init_schedule_tasks()
        init_documents()
        account_ops.init_account_management()
        request_log.init_requests()
        from src.retrieval.service import init_indexes
        init_indexes()
        from src.server.migrations import migrate_conversations
        from src.server.session import app_db
        with app_db() as db:
            db.execute('BEGIN IMMEDIATE')
            migrate_conversations(db)
    from src.retrieval.service import index_worker
    with worker_lifetime(), index_worker():
        yield


app = FastAPI(
    title="My Agent API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if IS_DEMO else "/docs",
    redoc_url=None if IS_DEMO else "/redoc",
    openapi_url=None if IS_DEMO else "/openapi.json",
)

# Serialize turns for a given identity in the single-worker deployment.
chat_locks = tuple(Lock() for _ in range(64))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.middleware("http")
async def coordinated_request(request: Request, call_next):
    if request.url.path == "/health":
        return await call_next(request)
    try:
        identity = session_user(request) or ("anonymous:" + uuid4().hex)
        with operation(identity, exclusive=request.method in {"POST", "PUT", "PATCH", "DELETE"}):
            if not identity.startswith('anonymous:') and request.url.path.startswith(('/chat','/history','/documents','/task','/retrieval')):
                from src.server.conversations import bind
                with bind(identity,request.headers.get('x-chat-session')):
                    return await call_next(request)
            return await call_next(request)
    except HTTPException as error:
        return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers={"Cache-Control": "no-store"})
    except sqlite3.Error:
        return JSONResponse({'detail': '数据库暂不可用，请核对原请求状态，勿重复提交。'}, status_code=503,
                            headers={'Cache-Control': 'no-store'})


def require_same_origin_json(request: Request):
    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if media_type.lower() != "application/json":
        raise HTTPException(status_code=415, detail="Expected application/json")


from src.server.memories import routes as memory_routes
app.include_router(memory_routes(require_same_origin_json))


class ConversationCreation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    name:str=Field(default='新聊天',min_length=1,max_length=60)


@app.get('/conversations')
def conversation_list(user_id:str=Depends(require_user)):
    from src.server.conversations import listing
    return {'sessions':listing(user_id)}


@app.post('/conversations',dependencies=[Depends(require_same_origin_json)])
def conversation_create(req:ConversationCreation,user_id:str=Depends(require_user)):
    from src.server.conversations import create
    if not req.name.strip():raise HTTPException(422,'会话名称不能为空')
    return create(user_id,req.name.strip())


@app.delete('/conversations/{identity}',dependencies=[Depends(require_same_origin_json)])
def conversation_delete(identity:str,user_id:str=Depends(require_user)):
    from src.server.conversations import mark
    return mark(user_id,identity,True)


@app.post('/conversations/{identity}/restore',dependencies=[Depends(require_same_origin_json)])
def conversation_restore(identity:str,req:auth.EmptyRequest,user_id:str=Depends(require_user)):
    from src.server.conversations import mark
    return mark(user_id,identity,False)


def recent_messages(user_id):
    messages = []
    from src.agent.context import budget
    for item in get_recent_history(user_id, 2*budget().turns+2):
        role = {"user": HumanMessage, "assistant": AIMessage}.get(item["role"])
        if role is None:
            continue
        messages.append(role(content=item['content'],id=str(item['id'])))
    return messages


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    mode: Literal["auto", "chat", "documents"] = "auto"
    calendar: WorkCalendar | None = None
    task_id: str | None = Field(default=None, min_length=1, max_length=80)
    request_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9-]{8,80}$")
    session_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')


class TaskSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80)


@app.get("/auth/me")
def current_identity(request: Request):
    return identity_info(session_user(request))


@app.post("/auth/register", dependencies=[Depends(require_same_origin_json)])
def register(req: auth.Registration, request: Request, response: Response):
    return auth.register(req, request, response)


@app.post("/auth/login", dependencies=[Depends(require_same_origin_json)])
def login(req: auth.Credentials, request: Request, response: Response):
    return auth.login(req, request, response)


@app.post("/auth/logout", dependencies=[Depends(require_same_origin_json)])
def logout(req: auth.EmptyRequest, request: Request, response: Response):
    return auth.logout(request, response)


@app.post("/auth/password/change", dependencies=[Depends(require_same_origin_json)])
def password_change(req: account_ops.PasswordChange, request: Request, response: Response, user_id: str = Depends(require_user)):
    return account_ops.change_password(user_id, req, request, response)


@app.get("/auth/sessions")
def account_sessions(request: Request, user_id: str = Depends(require_user)):
    return {"sessions": account_ops.sessions(user_id, request)}


@app.post("/auth/sessions/revoke", dependencies=[Depends(require_same_origin_json)])
def revoke_session(req: TaskSelection, user_id: str = Depends(require_user)):
    return account_ops.revoke(user_id, req.id)


@app.post("/auth/logout-all", dependencies=[Depends(require_same_origin_json)])
def logout_all(req: auth.EmptyRequest, request: Request, response: Response, user_id: str = Depends(require_user)):
    account_ops.revoke(user_id)
    return auth.logout(request, response)


@app.post("/auth/email/request", dependencies=[Depends(require_same_origin_json)])
def email_request(req: account_ops.EmailBinding, request: Request, user_id: str = Depends(require_user)):
    return account_ops.request_email(user_id, req, request)


@app.post("/auth/email/verify", dependencies=[Depends(require_same_origin_json)])
def email_verify(req: account_ops.TokenRequest, request: Request, user_id: str = Depends(require_user)):
    auth.throttle(request)
    return account_ops.verify_email(user_id, req.token)


@app.post("/auth/password/forgot", dependencies=[Depends(require_same_origin_json)])
def password_forgot(req: account_ops.EmailRequest, request: Request, background_tasks: BackgroundTasks):
    return account_ops.forgot(req, request, background_tasks)


@app.post("/auth/password/reset", dependencies=[Depends(require_same_origin_json)])
def password_reset(req: account_ops.ResetRequest, request: Request):
    return account_ops.reset(req, request)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/session", dependencies=[Depends(require_same_origin_json)])
def session(request: Request, response: Response):
    ensure_session(request, response)
    return {"ready": True}


@app.post("/chat", dependencies=[Depends(require_same_origin_json)])
def chat(req: ChatRequest, request:Request, user_id: str = Depends(require_user)):
    if req.session_id:
        if request.headers.get('x-chat-session') not in (None,req.session_id):raise HTTPException(409,'聊天会话参数不一致')
        from src.server.conversations import bind
        with bind(user_id,req.session_id):return chat_in_session(req,user_id)
    return chat_in_session(req,user_id)


def chat_in_session(req,user_id):
    limit = 2000 if IS_DEMO else 6000
    if len(req.message.strip()) > limit:
        raise HTTPException(422, f"Messages are limited to {limit} characters")
    return request_log.run(user_id, req.request_id,
        req.model_dump_json(exclude={"request_id", "session_id"}), lambda: execute_chat(req, user_id))


def execute_chat(req, user_id):
    message = req.message.strip()
    limit = 2000 if IS_DEMO else 6000
    if len(message) > limit:
        raise HTTPException(status_code=422, detail=f"Messages are limited to {limit} characters")
    if not message:
        return {"answer": "请输入消息。", "tool": "", "tool_result": "", "memory": []}

    with chat_locks[hash(user_id) % len(chat_locks)]:
        from src.agent.execution import check_budget
        check_budget()
        from src.agent.context import prepare_messages
        messages = prepare_messages(recent_messages(user_id) + [HumanMessage(content=message)])
        source_message_id=save_history(user_id, "user", message)
        from src.agent.history_summary import update as update_summary
        cutoff=next((int(m.id) for m in messages if m.id),source_message_id)
        history_summary=update_summary(user_id,general_agent.llm,cutoff,source_message_id,message,
                                       force=message=='重试历史摘要')
        from src.agent.execution import check_budget
        check_budget()
        from src.retrieval.service import enabled
        schedule = document_turn(messages, general_agent.llm, user_id, req.mode, req.calendar.model_dump() if req.calendar else None, req.task_id, defer_new=enabled())
        if schedule is not None:
            answer = schedule["answer"]
            check_budget()
            save_history(user_id, "assistant", answer)
            calls = schedule["calls"]
            return {
                "answer": answer, "tool": calls[-1] if calls else "", "tool_result": "",
                "memory": [], "tool_calls": calls, "citations": schedule.get("citations", []),
                "task": schedule.get("task", {}),
            }

        from src.memory.store import memory_store
        memory_generation=memory_store.auto_settings(user_id)['revision']
        from src.server.conversations import current as current_conversation
        result = general_agent.graph.invoke(
            {"messages": messages, "user_id": user_id, "task_id":req.task_id,
             'chat_session_id':current_conversation.get()['id'] if current_conversation.get() else None,
             "calendar":req.calendar.model_dump() if req.calendar else None, "mode":req.mode,
             "source_message_id":source_message_id,'memory_generation':memory_generation,
             'history_summary':history_summary},
            {"configurable": {"thread_id": chat_thread(user_id)}},
        )
        answer = result.get("response")
        if not answer:
            answer = next(
                (
                    msg.content
                    for msg in reversed(result.get("messages", []))
                    if getattr(msg, "type", None) == "ai"
                ),
                None,
            )
        answer = answer or "抱歉，没有生成回复。"
        check_budget()
        save_history(user_id, "assistant", answer)

    return {
        "answer": answer,
        "tool": result.get("tool_name", ""),
        "tool_result": result.get("tool_result", ""),
        "memory": result.get("memory") or [],
        "citations": result.get('citations', []), "task":result.get('task', {}),
        "tool_calls":result.get('document_calls', []),
    }


@app.get("/history")
def history(request: Request, user_id: str = Depends(require_user)):
    if "user_id" in request.query_params:
        raise HTTPException(status_code=422, detail="Unexpected user_id parameter")
    from src.server.schedule_tasks import load_task
    messages = get_history(user_id)
    task = load_task(user_id) or {}
    for item in reversed(messages):
        if item["role"] == "assistant" and item["content"] == task.get("answer"):
            item["citations"] = task.get("citations", [])
            break
    return {"messages": messages}


def require_upload_origin(request: Request):
    if request.headers.get("origin") not in allowed_origins:
        raise HTTPException(403, "Origin not allowed")


@app.get("/documents")
def list_documents(user_id: str = Depends(require_user)):
    from src.retrieval.service import statuses
    indexed = statuses(user_id)
    return {"files": [{**{k: v for k, v in d.items() if k != "chunks"},
                       "index": indexed.get(d["id"], {"status": "PENDING", "failure_reason": ""})} for d in documents(user_id)]}


@app.post("/documents", dependencies=[Depends(require_upload_origin)])
def upload_document(file: UploadFile = File(...), user_id: str = Depends(require_user)):
    try:
        content = file.file.read(MAX_BYTES + 1)
        identity = store_document(user_id, file.filename, content)
        from src.retrieval.service import enqueue
        try:
            enqueue(user_id, identity)
        except ValueError:
            pass  # Invalid optional indexing configuration must not lose a valid upload.
        return {"id": identity, "status": "ready"}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    finally:
        file.file.close()


@app.get("/documents/{identity}")
def document_source(identity: str, user_id: str = Depends(require_user)):
    return get_document(user_id, identity)


@app.delete("/documents/{identity}", dependencies=[Depends(require_upload_origin)])
def delete_document(identity: str, user_id: str = Depends(require_user)):
    from src.retrieval.service import remove_document
    remove_document(user_id, identity)
    return {"deleted": True}


@app.post("/documents/{identity}/reindex", dependencies=[Depends(require_same_origin_json)])
def reindex_document(identity: str, req: auth.EmptyRequest, user_id: str = Depends(require_user)):
    from src.retrieval.service import enqueue
    try:
        row = enqueue(user_id, identity, force=True)
        return {"status": row["status"], "generation": row["generation"]}
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


class VectorSearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=2000)
    document_ids: list[str] | None = Field(default=None, max_length=12)
    top_k: int = Field(default=4, ge=1, le=20, strict=True)


@app.post("/retrieval/search", dependencies=[Depends(require_same_origin_json)])
def vector_search(req: VectorSearch, user_id: str = Depends(require_user)):
    from src.retrieval.service import IndexService
    try:
        return {"hits": IndexService().search(user_id, req.query, req.document_ids, req.top_k)}
    except HTTPException:
        raise
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    except Exception:
        raise HTTPException(503, "Embedding或Chroma暂不可用，请检查本地服务")



@app.get("/task")
def task_status(user_id: str = Depends(require_user)):
    from src.server.schedule_tasks import load_task
    task = load_task(user_id) or {}
    result = {key: task.get(key) for key in ("id", "status", "pending", "skill", "completed", "request", "file_ids", "calendar")}
    value = task.get("result")
    result["result_summary"] = {"sources": sum(bool(h.get('accepted')) for h in task['retrieval_audit']) if 'retrieval_audit' in task else len(task.get("sources", [])),
                                "remaining": value.get("remaining") if isinstance(value, dict) else value}
    return result


class TaskCreation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "新任务"


@app.get("/tasks")
def tasks(user_id: str = Depends(require_user)):
    from src.server.schedule_tasks import list_tasks
    return {"tasks": list_tasks(user_id)}


@app.post("/tasks/select", dependencies=[Depends(require_same_origin_json)])
def switch_task(req: TaskSelection, user_id: str = Depends(require_user)):
    from src.server.schedule_tasks import select_task
    with chat_locks[hash(user_id) % len(chat_locks)]:
        return select_task(user_id, req.id)


@app.post("/tasks/new", dependencies=[Depends(require_same_origin_json)])
def create_task(req: TaskCreation, user_id: str = Depends(require_user)):
    from src.server.schedule_tasks import new_task
    if not 1 <= len(req.name) <= 160:
        raise HTTPException(422, "任务名称需 1–160 字符")
    with chat_locks[hash(user_id) % len(chat_locks)]:
        return new_task(user_id, req.name)


@app.post("/tasks/pause", dependencies=[Depends(require_same_origin_json)])
def pause_task(req: auth.EmptyRequest, user_id: str = Depends(require_user)):
    from src.server.schedule_tasks import load_task, save_task
    with chat_locks[hash(user_id) % len(chat_locks)]:
        task = load_task(user_id)
        if not task:
            raise HTTPException(404, "任务不存在")
        task.update({"status": "paused", "pending": "continue"})
        save_task(user_id, task)
        return {"paused": True}


# Register the production UI after the API so it cannot shadow API routes.
frontend_dist = PROJECT_DIR / "frontend" / "dist"
if IS_DEMO and (frontend_dist / "index.html").is_file():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
