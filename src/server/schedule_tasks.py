"""Multi-task storage with legacy active-task compatibility."""
import json
from uuid import uuid4
from fastapi import HTTPException
from src.server.session import app_db
from src.server.conversations import thread,storage_session


def init_schedule_tasks():
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("CREATE TABLE IF NOT EXISTS schedule_tasks(user_id TEXT PRIMARY KEY,state TEXT NOT NULL)")
        from src.server.migrations import thread_columns
        thread_columns(db,'schedule_tasks')
        db.execute("""CREATE TABLE IF NOT EXISTS agent_tasks(
            user_id TEXT NOT NULL,id TEXT NOT NULL,state TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id,id))""")
        if 'session_id' not in {r[1] for r in db.execute('PRAGMA table_info(agent_tasks)')}:
            db.execute("ALTER TABLE agent_tasks ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        db.execute("""INSERT OR IGNORE INTO agent_tasks(user_id,id,state)
            SELECT user_id,json_extract(state,'$.id'),state FROM schedule_tasks
            WHERE session_id='' AND json_valid(state) AND json_extract(state,'$.id') IS NOT NULL""")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (3)")


def load_task(user_id):
    with app_db() as db:
        row = db.execute("SELECT state FROM schedule_tasks WHERE thread_id=?", (thread(user_id),)).fetchone()
    return json.loads(row[0]) if row else None


def save_task(user_id, task):
    from src.server.coordination import check_lease
    check_lease()
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        payload = json.dumps(task, ensure_ascii=False)
        if task.get("id"):
            existing=db.execute('SELECT session_id FROM agent_tasks WHERE user_id=? AND id=?',(user_id,task['id'])).fetchone()
            if existing and existing[0]!=storage_session(user_id):raise HTTPException(404,'任务不属于当前聊天会话')
            db.execute("""INSERT INTO agent_tasks(user_id,id,state,session_id) VALUES (?,?,?,?)
                ON CONFLICT(user_id,id) DO UPDATE SET state=excluded.state,
                revision=agent_tasks.revision+1,updated_at=CURRENT_TIMESTAMP""",
                (user_id, task["id"], payload,storage_session(user_id)))
        db.execute("""INSERT INTO schedule_tasks(thread_id,state,user_id,session_id) VALUES (?,?,?,?)
            ON CONFLICT(thread_id) DO UPDATE SET state=excluded.state""", (thread(user_id), payload,user_id,storage_session(user_id)))


def list_tasks(user_id):
    with app_db() as db:
        rows = db.execute("SELECT id,state,revision,updated_at FROM agent_tasks WHERE user_id=? AND session_id=? ORDER BY updated_at DESC,rowid DESC",
                          (user_id,storage_session(user_id))).fetchall()
    return [{"id": identity, "name": json.loads(state).get("name", json.loads(state).get("request", "未命名任务"))[:60],
             "status": json.loads(state).get("status", "waiting"),
             "pending": json.loads(state).get("pending"), "revision": revision, "updated_at": updated}
            for identity, state, revision, updated in rows]


def select_task(user_id, identity):
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state FROM agent_tasks WHERE user_id=? AND id=? AND session_id=?", (user_id, identity,storage_session(user_id))).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        task = json.loads(row[0])
        task["use_saved_scope"] = True
        db.execute("""INSERT INTO schedule_tasks(thread_id,state,user_id,session_id) VALUES (?,?,?,?)
            ON CONFLICT(thread_id) DO UPDATE SET state=excluded.state""", (thread(user_id), json.dumps(task, ensure_ascii=False),user_id,storage_session(user_id)))
    return task


def new_task(user_id, name):
    task = {"kind": "attachments", "id": uuid4().hex, "request": name, "delay": 0,
            "status": "waiting", "pending": "request", "file_ids": [], "name": name}
    save_task(user_id, task)
    return task
