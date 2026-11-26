from src.config import IS_DEMO, PROJECT_DIR
from src.server.session import app_db
from src.server.migrations import migrate_history
from src.server.conversations import storage_session

HISTORY_FILE = PROJECT_DIR / "chat_history.json"


def init_history():
    with app_db() as db:
        db.execute("BEGIN IMMEDIATE")
        # Demo has always stored its own history in SQLite.
        migrate_history(db, HISTORY_FILE if not IS_DEMO else None)
        from src.server.migrations import migrate_history_summaries
        migrate_history_summaries(db)


def save_history(user_id, role, content):
    from src.server.coordination import check_lease
    check_lease()
    with app_db() as db:
        cursor=db.execute("INSERT INTO chat_messages(user_id,role,content,session_id) VALUES (?,?,?,?)",
                          (user_id, role, content,storage_session(user_id)))
        return cursor.lastrowid


def memory_source(user_id, message_id):
    with app_db() as db:
        row=db.execute('SELECT role,content FROM chat_messages WHERE user_id=? AND id=?',(user_id,message_id)).fetchone()
    return {'role':row[0],'content':row[1]} if row else None


def get_history(user_id):
    with app_db() as db:
        rows = db.execute("SELECT role,content FROM chat_messages WHERE user_id=? AND session_id=? ORDER BY id",
                          (user_id,storage_session(user_id))).fetchall()
    return [{"role": role, "content": content} for role, content in rows]


def get_recent_history(user_id, limit):
    with app_db() as db:
        rows = db.execute("SELECT id,role,content FROM chat_messages WHERE user_id=? AND session_id=? ORDER BY id DESC LIMIT ?",
                          (user_id,storage_session(user_id),limit)).fetchall()
    return [{"id": identity,"role": role, "content": content} for identity,role, content in reversed(rows)]
