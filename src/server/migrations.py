"""Versioned, transactional upgrades. Existing identity IDs remain stable."""
import json


def thread_columns(db,table):
    """Keep the old primary key as thread_id, add the actual authenticated owner."""
    columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
    if 'thread_id' not in columns:
        db.execute(f'ALTER TABLE {table} RENAME COLUMN user_id TO thread_id')
        db.execute(f"ALTER TABLE {table} ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
        db.execute(f'UPDATE {table} SET user_id=thread_id')
    if 'session_id' not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")


def migrate_conversations(db):
    db.execute('''CREATE TABLE IF NOT EXISTS conversations(
        id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT NOT NULL,
        is_default INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,
        thread_id TEXT NOT NULL UNIQUE,storage_session TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,UNIQUE(user_id,storage_session))''')
    db.execute('CREATE UNIQUE INDEX IF NOT EXISTS conversations_default ON conversations(user_id) WHERE is_default=1')
    if 'session_id' not in {r[1] for r in db.execute('PRAGMA table_info(chat_messages)')}:
        db.execute("ALTER TABLE chat_messages ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
    db.execute('CREATE INDEX IF NOT EXISTS chat_messages_session ON chat_messages(user_id,session_id,id)')
    if 'session_id' not in {r[1] for r in db.execute('PRAGMA table_info(agent_tasks)')}:
        db.execute("ALTER TABLE agent_tasks ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
    for table in ('schedule_tasks','chat_requests'):thread_columns(db,table)
    db.execute('''CREATE TABLE IF NOT EXISTS conversation_documents(
        user_id TEXT NOT NULL,session_id TEXT NOT NULL,document_id TEXT NOT NULL,
        PRIMARY KEY(user_id,session_id,document_id))''')
    if not db.execute('SELECT 1 FROM schema_migrations WHERE version=8').fetchone():
        db.execute("INSERT OR IGNORE INTO conversation_documents SELECT user_id,'',id FROM documents")
        db.execute('INSERT INTO schema_migrations VALUES (8)')


def migrate_memories(db):
    """Incremental migration inside the existing memory.db transaction.

    Legacy provenance and timestamps remain unknown, rather than invented.
    """
    db.execute('CREATE TABLE IF NOT EXISTS memory_schema_migrations(version INTEGER PRIMARY KEY)')
    db.execute('''CREATE TABLE IF NOT EXISTS memories(
        id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,key TEXT NOT NULL,
        value TEXT NOT NULL,UNIQUE(user_id,key))''')
    columns={row[1] for row in db.execute('PRAGMA table_info(memories)')}
    additions={'source_message_id':'INTEGER','created_at':'TEXT','updated_at':'TEXT',
        'status':"TEXT NOT NULL DEFAULT 'active'",'revision':'INTEGER NOT NULL DEFAULT 1',
        'confirmation_state':"TEXT NOT NULL DEFAULT 'unknown'",'source_type':"TEXT NOT NULL DEFAULT 'legacy'",
        'last_message_id':'INTEGER'}
    for name,definition in additions.items():
        if name not in columns:db.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_events(
        id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,key TEXT NOT NULL,action TEXT NOT NULL,
        revision INTEGER NOT NULL,source_message_id INTEGER,operation_index INTEGER NOT NULL,
        source_type TEXT NOT NULL,created_at TEXT NOT NULL,
        UNIQUE(user_id,key,source_message_id,operation_index))''')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_candidates(
        id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,
        source_message_id INTEGER,source_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,UNIQUE(user_id,key,value))''')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_tombstones(
        user_id TEXT NOT NULL,key TEXT NOT NULL,value_hash TEXT NOT NULL,
        deleted_message_id INTEGER,deleted_revision INTEGER NOT NULL,deleted_at TEXT NOT NULL,restored_message_id INTEGER,
        PRIMARY KEY(user_id,key,value_hash))''')
    if 'restored_message_id' not in {row[1] for row in db.execute('PRAGMA table_info(memory_tombstones)')}:
        db.execute('ALTER TABLE memory_tombstones ADD COLUMN restored_message_id INTEGER')
    db.execute('INSERT OR IGNORE INTO memory_schema_migrations VALUES (1)')
    for name,definition in {'management_action_id':'TEXT','source_floor':'INTEGER'}.items():
        if name not in {r[1] for r in db.execute('PRAGMA table_info(memories)')}:
            db.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
    for name in ('source_floor','restored_generation'):
        if name not in {r[1] for r in db.execute('PRAGMA table_info(memory_tombstones)')}:
            db.execute(f'ALTER TABLE memory_tombstones ADD COLUMN {name} INTEGER')
    if 'management_action_id' not in {r[1] for r in db.execute('PRAGMA table_info(memory_events)')}:
        db.execute('ALTER TABLE memory_events ADD COLUMN management_action_id TEXT')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_settings(user_id TEXT PRIMARY KEY,
        auto_enabled INTEGER NOT NULL DEFAULT 1,revision INTEGER NOT NULL DEFAULT 0,updated_at TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_management_actions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,
        key TEXT NOT NULL,action TEXT NOT NULL,value TEXT NOT NULL,expected_revision INTEGER NOT NULL,
        source_floor INTEGER NOT NULL,created_at TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS memory_revisions(user_id TEXT NOT NULL,key TEXT NOT NULL,
        revision INTEGER NOT NULL,snapshot TEXT NOT NULL,recorded_at TEXT NOT NULL,
        PRIMARY KEY(user_id,key,revision))''')
    # Record only the available current revision; never invent missing old versions.
    from datetime import datetime,timezone
    columns=[r[1] for r in db.execute('PRAGMA table_info(memories)')]
    for raw in db.execute('SELECT * FROM memories').fetchall():
        row=dict(zip(columns,raw))
        db.execute('INSERT OR IGNORE INTO memory_revisions VALUES (?,?,?,?,?)',
            (row['user_id'],row['key'],row['revision'],json.dumps(row,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
    db.execute('INSERT OR IGNORE INTO memory_schema_migrations VALUES (2)')


def migrate_sessions(db):
    db.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
    if db.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
        return
    db.execute("""CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL UNIQUE,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)""")
    db.execute("ALTER TABLE sessions RENAME TO sessions_v0")
    db.execute("""CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL)""")
    db.execute("INSERT INTO sessions SELECT * FROM sessions_v0")
    db.execute("DROP TABLE sessions_v0")
    db.execute("CREATE INDEX sessions_user ON sessions(user_id)")
    db.execute("""CREATE TABLE accounts (
        user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL, created_at INTEGER NOT NULL)""")
    db.execute("INSERT INTO schema_migrations VALUES (1)")


def migrate_history(db, path):
    db.execute("""CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, role TEXT NOT NULL,
        content TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    db.execute("CREATE INDEX IF NOT EXISTS chat_messages_user ON chat_messages(user_id,id)")
    if 'session_id' not in {r[1] for r in db.execute('PRAGMA table_info(chat_messages)')}:
        db.execute("ALTER TABLE chat_messages ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
    if db.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
        return
    data = json.loads(path.read_text(encoding="utf-8-sig")) if path is not None and path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError("旧聊天历史格式错误，迁移已回滚")
    for identity, messages in data.items():
        if not isinstance(identity, str) or not isinstance(messages, list):
            raise ValueError("旧聊天历史身份格式错误")
        for message in messages:
            if (not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}
                    or not isinstance(message.get("content"), str)):
                raise ValueError("旧聊天历史消息格式错误")
            db.execute("INSERT INTO chat_messages(user_id,role,content) VALUES (?,?,?)",
                       (identity, message["role"], message["content"]))
    db.execute("INSERT INTO schema_migrations VALUES (2)")


def migrate_history_summaries(db):
    """Derived history only; original chat rows and personal memories are untouched."""
    db.execute('''CREATE TABLE IF NOT EXISTS history_summaries(
        user_id TEXT PRIMARY KEY,status TEXT NOT NULL DEFAULT 'EMPTY',revision INTEGER NOT NULL DEFAULT 0,
        start_id INTEGER NOT NULL DEFAULT 0,end_id INTEGER NOT NULL DEFAULT 0,
        items TEXT NOT NULL DEFAULT '[]',created_at TEXT,updated_at TEXT,
        floor_id INTEGER NOT NULL DEFAULT 0,memory_revision INTEGER NOT NULL DEFAULT 0,
        worker_token TEXT NOT NULL DEFAULT '',lease_until REAL NOT NULL DEFAULT 0,
        batch_end INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,
        retry_at REAL NOT NULL DEFAULT 0,failure_reason TEXT NOT NULL DEFAULT '')''')
    db.execute('''CREATE TABLE IF NOT EXISTS history_summary_revisions(
        user_id TEXT NOT NULL,revision INTEGER NOT NULL,start_id INTEGER NOT NULL,end_id INTEGER NOT NULL,
        items TEXT NOT NULL,created_at TEXT NOT NULL,memory_revision INTEGER NOT NULL,
        PRIMARY KEY(user_id,revision))''')
    db.execute('INSERT OR IGNORE INTO schema_migrations VALUES (7)')
    for table in ('history_summaries','history_summary_revisions'):thread_columns(db,table)
