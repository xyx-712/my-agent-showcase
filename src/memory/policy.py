"""Transactional policies over the existing MemoryStore connection, not a new store."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4


def now():return datetime.now(timezone.utc).isoformat()
def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()
MERGE_KEYS={'hobby','likes','skill'}


class MemoryPolicy:
    def __init__(self,store,source_lookup=None):
        self.store=store
        self.source_lookup=source_lookup

    def validate_source(self,user,source_id,text):
        if source_id is None:return
        if type(source_id) is not int or source_id<=0:raise ValueError('记忆来源消息ID无效')
        if self.source_lookup is None:
            from src.server.history import memory_source
            row=memory_source(user,source_id)
        else:row=self.source_lookup(user,source_id)
        if not row or row['role']!='user' or row['content']!=text:
            raise ValueError('记忆来源消息不存在、归属不符或正文不匹配')

    def apply(self,user,operations,source_id=None,text=None,source_type='internal',expected_revision=None,
              automatic=False,generation=None,management_floor=None):
        if not isinstance(user,str) or not user.strip():raise ValueError('记忆写入需要明确身份')
        if source_type not in {'internal','user_statement','user_correction','user_restore','model_candidate','user_management'}:
            raise ValueError('该来源不能写入个人记忆')
        manual=source_type=='user_management'
        if source_type.startswith('user_') and source_id is None and not manual:raise ValueError('用户记忆写入缺少来源消息')
        if manual and (source_id is not None or expected_revision is None or type(management_floor) is not int or management_floor<0):
            raise ValueError('手动管理需要修订版本和服务端来源边界')
        if expected_revision is not None and (type(expected_revision) is not int or expected_revision<0):
            raise ValueError('记忆修订版本无效')
        self.validate_source(user,source_id,text)
        outcomes=[]
        with closing(self.store.get_conn()) as db,db:
            db.row_factory=__import__('sqlite3').Row
            db.execute('BEGIN IMMEDIATE')
            setting=db.execute('SELECT auto_enabled,revision FROM memory_settings WHERE user_id=?',(user,)).fetchone()
            enabled,epoch=(bool(setting[0]),setting[1]) if setting else (True,0)
            if automatic and (not enabled or generation!=epoch and not(generation is None and epoch==0 and source_id is None)):
                return [{'key':op['key'],'status':'automatic_paused' if not enabled else 'stale_generation','revision':0} for op in operations]
            next_epoch=epoch+1 if manual else epoch
            def snapshot(key):
                current=db.execute('SELECT * FROM memories WHERE user_id=? AND key=?',(user,key)).fetchone()
                if current:db.execute('INSERT OR IGNORE INTO memory_revisions VALUES (?,?,?,?,?)',
                    (user,key,current['revision'],json.dumps(dict(current),ensure_ascii=False),now()))
            for index,op in enumerate(operations):
                key=op['key'];value=op.get('value','');intent=op.get('intent','statement');action=op.get('action','save')
                if not isinstance(key,str) or not key or len(key)>100 or not isinstance(value,str) or len(value)>6000:
                    raise ValueError('记忆键或值超限')
                if action not in {'save','delete','delete_key'} or intent not in {'statement','correction','replace','restore','candidate'}:
                    raise ValueError('未知记忆操作')
                raw=db.execute('SELECT * FROM memories WHERE user_id=? AND key=?',(user,key)).fetchone()
                row=dict(raw) if raw else None
                revision=row['revision'] if row else 0
                result={'key':key,'status':'unchanged','revision':revision}
                if expected_revision is not None and expected_revision!=revision:
                    outcomes.append({**result,'status':'stale_revision'});continue
                if manual and (not row or row['status']=='deleted'):
                    outcomes.append({**result,'status':'not_manageable'});continue
                if source_id is not None and row and row.get('source_floor') is not None and source_id<=row['source_floor']:
                    outcomes.append({**result,'status':'stale_source'});continue
                snapshot(key)
                management_id=None
                if manual:
                    management_id=uuid4().hex
                    db.execute('INSERT INTO memory_management_actions VALUES (?,?,?,?,?,?,?,?)',
                        (management_id,user,key,action,value,revision,management_floor,now()))
                if source_id is not None and db.execute('SELECT 1 FROM memory_events WHERE user_id=? AND key=? AND source_message_id=? AND operation_index=?',(user,key,source_id,index)).fetchone():
                    outcomes.append({**result,'status':'duplicate_event'});continue
                if source_id is not None and row and row['last_message_id'] is not None and source_id<row['last_message_id']:
                    outcomes.append({**result,'status':'stale_source'});continue
                if action=='save':
                    values=self.store.split_values(value) if key in MERGE_KEYS else [value.strip()]
                    if not values or not all(values):raise ValueError('记忆值不能为空')
                    blocked=[]
                    for part in values:
                        barriers=db.execute('SELECT * FROM memory_tombstones WHERE user_id=? AND key=? AND value_hash IN (?,?)',(user,key,'*',digest(part))).fetchall()
                        if barriers:
                            allowed=manual or source_id is not None and all(
                                (automatic and b['restored_generation'] is not None and generation is not None and generation>=b['restored_generation']) or
                                (b['restored_message_id'] is not None and source_id>=b['restored_message_id']) or
                                (intent=='restore' and ((b['deleted_message_id'] is not None and source_id>b['deleted_message_id']) or
                                 (b['source_floor'] is not None and source_id>b['source_floor']) or
                                 (b['deleted_message_id'] is None and expected_revision==revision))) for b in barriers)
                            if not allowed:blocked.append(part)
                    if blocked:
                        outcomes.append({**result,'status':'deleted_barrier'});continue
                    active=row and row['status']!='deleted' and bool(row['value'])
                    old=row['value'] if active else ''
                    incoming='、'.join(values) if key in MERGE_KEYS else values[0]
                    if key in MERGE_KEYS and active and intent!='replace':
                        incoming='、'.join(dict.fromkeys([*self.store.split_values(old),*values]))
                    if active and incoming==old and intent not in {'correction','replace','restore'}:
                        if source_id is not None and source_type!='model_candidate':
                            db.execute('UPDATE memories SET last_message_id=? WHERE user_id=? AND key=?',(source_id,user,key))
                        outcomes.append(result);continue
                    conflict=active and incoming!=old and key not in MERGE_KEYS and intent not in {'correction','replace','restore'}
                    candidate=source_type=='model_candidate' or intent=='candidate' or conflict
                    if candidate:
                        added=db.execute('INSERT OR IGNORE INTO memory_candidates(user_id,key,value,source_message_id,source_type,created_at) VALUES (?,?,?,?,?,?)',
                            (user,key,incoming,source_id,source_type,now())).rowcount
                        if not added:
                            added=db.execute("UPDATE memory_candidates SET status='pending',source_message_id=?,source_type=?,created_at=? WHERE user_id=? AND key=? AND value=? AND status='resolved'",
                                (source_id,source_type,now(),user,key,incoming)).rowcount
                        if not added:
                            outcomes.append({**result,'status':'duplicate_candidate'});continue
                        revision+=1
                        if row:
                            db.execute("UPDATE memories SET status=CASE WHEN status='deleted' THEN status ELSE 'pending_confirmation' END,revision=?,updated_at=?,last_message_id=coalesce(?,last_message_id) WHERE user_id=? AND key=?",(revision,now(),source_id if source_type!='model_candidate' else None,user,key))
                        else:
                            # Empty control row supplies a revision, never an active fact.
                            db.execute("INSERT INTO memories(user_id,key,value,created_at,updated_at,status,revision,confirmation_state,source_type,last_message_id) VALUES (?,?,'',?,?,'pending_confirmation',?,'pending',?,?)",
                                (user,key,now(),now(),revision,source_type,source_id if source_type!='model_candidate' else None))
                        event='candidate'
                    else:
                        revision+=1;stamp=now()
                        user_source=source_id is not None and source_type.startswith('user_')
                        confirmation='user_confirmed' if manual or user_source and intent in {'correction','replace','restore'} else 'user_stated' if user_source else 'unknown'
                        db.execute('''INSERT INTO memories(user_id,key,value,source_message_id,created_at,updated_at,status,revision,confirmation_state,source_type,last_message_id)
                            VALUES (?,?,?,?,?,?,'active',?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,
                            source_message_id=excluded.source_message_id,updated_at=excluded.updated_at,status='active',revision=excluded.revision,
                            confirmation_state=excluded.confirmation_state,source_type=excluded.source_type,last_message_id=coalesce(excluded.last_message_id,memories.last_message_id)''',
                            (user,key,incoming,source_id,stamp,stamp,revision,confirmation,source_type,source_id))
                        db.execute("UPDATE memory_candidates SET status='resolved' WHERE user_id=? AND key=? AND status='pending'",(user,key))
                        event='restore' if intent=='restore' else 'save'
                        if manual:
                            previous=self.store.split_values(old) if key in MERGE_KEYS else [old]
                            for part in previous:
                                if part and part not in values:
                                    db.execute('''INSERT INTO memory_tombstones(user_id,key,value_hash,deleted_revision,deleted_at,source_floor)
                                        VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,key,value_hash) DO UPDATE SET
                                        deleted_message_id=NULL,deleted_revision=excluded.deleted_revision,deleted_at=excluded.deleted_at,
                                        source_floor=excluded.source_floor,restored_message_id=NULL,restored_generation=NULL''',
                                        (user,key,digest(part),revision,stamp,management_floor))
                            for part in values:
                                db.execute('UPDATE memory_tombstones SET restored_generation=? WHERE user_id=? AND key=? AND value_hash IN (?,?)',
                                           (next_epoch,user,key,'*',digest(part)))
                        if intent=='restore':
                            for part in values:
                                db.execute('UPDATE memory_tombstones SET restored_message_id=? WHERE user_id=? AND key=? AND value_hash IN (?,?)',
                                           (source_id,user,key,'*',digest(part)))
                else:
                    old=row['value'] if row else ''
                    active=row and row['status']!='deleted' and bool(old)
                    parts=self.store.split_values(old) if key in MERGE_KEYS else [old]
                    removed=self.store.split_values(value) if key in MERGE_KEYS else [value]
                    remaining=[] if action=='delete_key' else [p for p in parts if p not in removed]
                    removed_existing=bool(active and (action=='delete_key' or remaining!=parts))
                    revision+=1;stamp=now()
                    for part in (['*'] if action=='delete_key' else removed):
                        db.execute('''INSERT INTO memory_tombstones(user_id,key,value_hash,deleted_message_id,deleted_revision,deleted_at) VALUES (?,?,?,?,?,?) ON CONFLICT(user_id,key,value_hash) DO UPDATE SET
                            deleted_message_id=excluded.deleted_message_id,deleted_revision=excluded.deleted_revision,deleted_at=excluded.deleted_at,restored_message_id=NULL,restored_generation=NULL,source_floor=NULL''',
                            (user,key,'*' if action=='delete_key' else digest(part),source_id,revision,stamp))
                    new='、'.join(remaining) if key in MERGE_KEYS else (remaining[0] if remaining else '')
                    status='active' if active and new else 'deleted'
                    # A tombstone retains the prior value for audit; get/search never expose it.
                    retained=new if status=='active' else old
                    db.execute('''INSERT INTO memories(user_id,key,value,created_at,updated_at,status,revision,source_type,last_message_id)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,
                        updated_at=excluded.updated_at,status=excluded.status,revision=excluded.revision,last_message_id=coalesce(excluded.last_message_id,memories.last_message_id)''',
                        (user,key,retained,stamp,stamp,status,revision,source_type,source_id))
                    db.execute("UPDATE memory_candidates SET status='rejected' WHERE user_id=? AND key=? AND status='pending'",(user,key))
                    event='delete'
                db.execute('UPDATE memories SET management_action_id=? WHERE user_id=? AND key=?',(management_id,user,key))
                if manual:
                    db.execute('UPDATE memories SET source_floor=?,source_message_id=NULL,source_type=?,confirmation_state=? WHERE user_id=? AND key=?',
                               (max(management_floor,row.get('source_floor') or 0),source_type,'user_confirmed',user,key))
                    if action=='delete_key':db.execute("UPDATE memory_tombstones SET source_floor=? WHERE user_id=? AND key=? AND value_hash='*'",(management_floor,user,key))
                    db.execute('INSERT INTO memory_settings VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at',
                               (user,int(enabled),next_epoch,now()))
                db.execute('INSERT INTO memory_events(user_id,key,action,revision,source_message_id,operation_index,source_type,created_at,management_action_id) VALUES (?,?,?,?,?,?,?,?,?)',
                    (user,key,event,revision,source_id,index,source_type,now(),management_id))
                snapshot(key)
                outcomes.append({'key':key,'status':event,'revision':revision,
                                 **({'removed':removed_existing} if event=='delete' else {})})
        return outcomes
