"""Authenticated callers supply owner IDs; all data stays in existing memory.db."""
from contextlib import closing
import json
import sqlite3
from fastapi import HTTPException


def settings(store,user):
    with closing(store.get_conn()) as db:
        row=db.execute('SELECT auto_enabled,revision FROM memory_settings WHERE user_id=?',(user,)).fetchone()
    return {'automatic_enabled':bool(row[0]) if row else True,'revision':row[1] if row else 0}


def set_settings(store,user,enabled,revision):
    from src.memory.policy import now
    from src.server.coordination import operation
    with operation('memory-settings:'+user,exclusive=False),closing(store.get_conn()) as db,db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT auto_enabled,revision FROM memory_settings WHERE user_id=?',(user,)).fetchone()
        actual=row[1] if row else 0
        if revision!=actual:raise HTTPException(409,'自动记忆设置已更新，请刷新后重试')
        db.execute('INSERT INTO memory_settings VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET auto_enabled=excluded.auto_enabled,revision=excluded.revision,updated_at=excluded.updated_at',
                   (user,int(enabled),actual+1,now()))
    return settings(store,user)


def owned(store,user,identity):
    with closing(store.get_conn()) as db:
        db.row_factory=sqlite3.Row
        row=db.execute('SELECT * FROM memories WHERE user_id=? AND id=?',(user,identity)).fetchone()
    if not row:raise HTTPException(404,'记忆不存在')
    return dict(row)


def listing(store,user,include_deleted=False):
    with closing(store.get_conn()) as db:
        db.row_factory=sqlite3.Row
        rows=db.execute("SELECT * FROM memories WHERE user_id=? AND (? OR status<>'deleted') ORDER BY id LIMIT 201",(user,int(include_deleted))).fetchall()
    return {'items':[dict(r) for r in rows[:200]],'has_more':len(rows)>200}


def detail(store,user,identity):
    with closing(store.get_conn()) as db:
        # One read snapshot keeps the item and its revision list consistent.
        db.execute('BEGIN')
        db.row_factory=sqlite3.Row
        current=db.execute('SELECT * FROM memories WHERE user_id=? AND id=?',(user,identity)).fetchone()
        if not current:raise HTTPException(404,'记忆不存在')
        row=dict(current)
        versions=[json.loads(r[0]) for r in db.execute('SELECT snapshot FROM memory_revisions WHERE user_id=? AND key=? ORDER BY revision DESC LIMIT 50',(user,row['key']))]
        candidates=[dict(r) for r in db.execute("SELECT * FROM memory_candidates WHERE user_id=? AND key=? AND status='pending' ORDER BY id DESC LIMIT 20",(user,row['key']))]
        action=db.execute('SELECT * FROM memory_management_actions WHERE user_id=? AND id=?',(user,row['management_action_id'])).fetchone() if row['management_action_id'] else None
    source=None
    if action:source={'type':'management','action':dict(action)}
    elif row['source_message_id'] is not None:
        from src.server.session import app_db
        with app_db() as db:
            msg=db.execute('SELECT id,role,content,created_at FROM chat_messages WHERE user_id=? AND id=?',(user,row['source_message_id'])).fetchone()
        if msg:source={'type':'message','id':msg[0],'role':msg[1],'content':msg[2],'created_at':msg[3]}
    return {'item':row,'source':source,'versions':versions,'candidates':candidates}


def mutate(store,user,identity,revision,value=None,delete=False):
    row=owned(store,user,identity)
    from src.server.session import app_db
    with app_db() as db:
        floor=db.execute('SELECT coalesce(max(id),0) FROM chat_messages WHERE user_id=?',(user,)).fetchone()[0]
    result=store.apply_operations(user,[{'key':row['key'],'action':'delete_key' if delete else 'save',
        'value':value or '', 'intent':'statement' if delete else 'replace'}],source_type='user_management',
        expected_revision=revision,management_floor=floor)
    if not result or result[0]['status'] in {'stale_revision','not_manageable'}:
        raise HTTPException(409,'记忆已被更新或删除，请刷新并核对最新版本')
    return {'item':owned(store,user,identity),'settings':settings(store,user)}
