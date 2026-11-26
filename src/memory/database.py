import sqlite3

from pathlib import Path



DB_PATH = Path(
    "agent_memory.db"
)



conn = sqlite3.connect(
    DB_PATH,
    check_same_thread=False
)





def init_db():

    cursor = conn.cursor()


    # 聊天历史

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT,

            role TEXT,

            content TEXT,

            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

        )
        """
    )


    # 长期记忆

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS memories(

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            user_id TEXT,

            key TEXT,

            value TEXT

        )
        """
    )


    conn.commit()





init_db()





# =========================
# 保存聊天
# =========================

def save_message(
    user_id,
    role,
    content
):

    cursor = conn.cursor()


    cursor.execute(
        """
        INSERT INTO messages
        (
            user_id,
            role,
            content
        )

        VALUES(?,?,?)

        """,

        (
            user_id,
            role,
            content
        )
    )


    conn.commit()







# =========================
# 获取聊天历史
# =========================

def get_messages(
    user_id,
    limit=20
):

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT role,content

        FROM messages

        WHERE user_id=?

        ORDER BY id DESC

        LIMIT ?

        """,

        (
            user_id,
            limit
        )
    )


    rows = cursor.fetchall()


    return list(
        reversed(rows)
    )






# =========================
# 保存记忆
# =========================

def save_memory(
    user_id,
    key,
    value
):

    cursor = conn.cursor()


    cursor.execute(
        """
        INSERT INTO memories
        (
            user_id,
            key,
            value
        )

        VALUES(?,?,?)

        """,

        (
            user_id,
            key,
            value
        )
    )


    conn.commit()







# =========================
# 获取记忆
# =========================

def get_memory(
    user_id
):

    cursor = conn.cursor()


    cursor.execute(
        """
        SELECT key,value

        FROM memories

        WHERE user_id=?

        """,

        (
            user_id
        )
    )


    rows = cursor.fetchall()


    return [

        {
            "key": row[0],
            "value": row[1]
        }

        for row in rows

    ]