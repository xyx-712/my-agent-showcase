from src.config import debug_print
import sqlite3
import re
from src.config import MEMORY_DB


class MemoryStore:

    def __init__(self):

        self.db = MEMORY_DB

        self.db.parent.mkdir(
            exist_ok=True
        )

        self.init_table()

    # =====================================
    # connection
    # =====================================

    def get_conn(self):
        from src.server.coordination import check_lease
        check_lease()

        return sqlite3.connect(
            str(self.db),
            timeout=30,
            check_same_thread=False
        )

    # =====================================
    # init
    # =====================================

    def init_table(self):
        from contextlib import closing
        from src.server.migrations import migrate_memories
        from src.server.coordination import operation
        with operation('memory-schema', exclusive=False):
            from src.server.backup import require_complete_restore
            require_complete_restore()
            with closing(self.get_conn()) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                migrate_memories(conn)

    # =====================================
    # split values
    # 统一处理多值记忆
    # =====================================

    def split_values(self, value):

        if not value:
            return []

        value = str(value).strip()

        if not value:
            return []

        # 支持：
        #
        # 足球、苹果
        # 足球和苹果
        # 足球，苹果
        # 足球,苹果
        #
        # 同时兼容历史数据库中的旧格式

        values = re.split(
            r"\s*(?:、|，|,|和)\s*",
            value
        )

        result = []

        for item in values:

            item = item.strip()

            if item and item not in result:

                result.append(item)

        return result

    # =====================================
    # normalize value
    # 统一保存格式
    # =====================================

    def normalize_values(self, value):

        values = self.split_values(value)

        return "、".join(values)

    # =====================================
    # save
    # =====================================

    def save(self, user_id, key, value, **metadata):
        if not key or not value:return []
        return self.apply_operations(user_id, [{'action':'save','key':key,'value':value,
            'intent':metadata.pop('intent','statement')}], **metadata)

    # =====================================
    # get
    # =====================================

    def get(
        self,
        user_id,
        key
    ):

        conn = self.get_conn()

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT value

            FROM memories

            WHERE
                user_id = ?

                AND

                key = ?
                AND status IN ('active','pending_confirmation') AND value<>''

            LIMIT 1
            """,
            (
                user_id,
                key
            )
        )

        row = cursor.fetchone()

        conn.close()

        if row:

            return row[0]

        return None

    # =====================================
    # search
    # =====================================

    def search(
        self,
        user_id
    ):

        conn = self.get_conn()

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                key,
                value

            FROM memories

            WHERE
                user_id = ?

                AND status IN ('active','pending_confirmation') AND value<>''
            ORDER BY id ASC
            """,
            (
                user_id,
            )
        )

        rows = cursor.fetchall()

        conn.close()

        return rows

    # =====================================
    # delete key
    # 删除整个记忆
    # =====================================

    def delete(self, user_id, key, **metadata):
        result=self.apply_operations(user_id,[{'action':'delete_key','key':key}], **metadata)
        return int(any(item.get('removed') for item in result))

    # =====================================
    # remove value
    # 删除单个记忆
    # =====================================

    def remove_value(self, user_id, key, value, **metadata):
        if not value:return False
        result=self.apply_operations(user_id,[{'action':'delete','key':key,'value':value}], **metadata)
        return any(item.get('removed') for item in result)

    # =====================================
    # clear user
    # =====================================

    def clear_user(self, user_id, **metadata):
        from contextlib import closing
        with closing(self.get_conn()) as conn:
            keys=[row[0] for row in conn.execute('SELECT key FROM memories WHERE user_id=? UNION SELECT key FROM memory_candidates WHERE user_id=?',(user_id,user_id))]
        results=self.apply_operations(user_id,[{'action':'delete_key','key':key} for key in keys], **metadata) if keys else []
        return sum(bool(item.get('removed')) for item in results)

    def apply_operations(self, user_id, operations, **metadata):
        from src.memory.policy import MemoryPolicy
        from src.server.coordination import operation
        with operation('memory-write:'+str(user_id),exclusive=False):
            return MemoryPolicy(self).apply(user_id, operations, **metadata)

    def inspect(self, user_id, key):
        from contextlib import closing
        with closing(self.get_conn()) as conn:
            conn.row_factory=sqlite3.Row
            row=conn.execute('SELECT * FROM memories WHERE user_id=? AND key=?',(user_id,key)).fetchone()
            return dict(row) if row else None

    def pending_keys(self, user_id):
        from contextlib import closing
        with closing(self.get_conn()) as conn:
            return [row[0] for row in conn.execute("SELECT DISTINCT key FROM memory_candidates WHERE user_id=? AND status='pending' ORDER BY key LIMIT 20",(user_id,))]

    def auto_settings(self,user_id):
        from src.memory.management import settings
        return settings(self,user_id)


# =========================================
# global memory store
# =========================================

memory_store = MemoryStore()
