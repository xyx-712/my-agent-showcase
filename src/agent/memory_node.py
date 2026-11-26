from src.config import debug_print
from src.memory.extractor import extract_memory

from src.memory.store import (
    memory_store
)


DEBUG_MEMORY = True


def memory_extractor_node(state):
    from src.memory.extractor import extract_operations
    messages=state.get('messages',[])
    user_id=state.get('user_id')
    if not messages or not user_id:
        return {'memory':[],'memory_notes':[],'memory_outcomes':[]}
    current=messages[-1]
    enabled=memory_store.auto_settings(user_id)['automatic_enabled']
    operations=extract_operations(current.content) if enabled and getattr(current,'type','human')=='human' else []
    outcomes=[]
    if operations:
        source_id=state.get('source_message_id')
        kind=('user_restore' if any(o.get('intent')=='restore' for o in operations) else
              'user_correction' if any(o.get('intent') in {'correction','replace'} for o in operations) else 'user_statement') if source_id is not None else 'internal'
        if operations[0]['action']=='delete_all':
            memory_store.clear_user(user_id,source_id=source_id,text=current.content,source_type=kind,automatic=True,generation=state.get('memory_generation'))
            outcomes=[{'key':'*','status':'delete'}]
        else:
            outcomes=memory_store.apply_operations(user_id,operations,source_id=source_id,text=current.content,source_type=kind,automatic=True,generation=state.get('memory_generation'))
    pending=memory_store.pending_keys(user_id)
    return {'memory':[{'key':key,'value':value} for key,value in memory_store.search(user_id)],'memory_outcomes':outcomes,
            'memory_notes':[f'{key}的新信息与已保存信息存在冲突或尚未确认；保留旧记录。可用“更正，我的名字是…”等明确陈述确认。' for key in pending]}
