"""Durable index generations; SQLite remains authoritative over derived Chroma data."""
from contextlib import contextmanager
import math
import os
from threading import Event, Thread
import time
from uuid import uuid4

from src.retrieval.embeddings import settings, OllamaVectors
from src.retrieval.store import VectorStore
from src.retrieval.loaders import load_owned_document
from src.retrieval.splitter import split_documents, VERSION


def database():
    from src.server.session import app_db
    return app_db()


def enabled():
    return os.environ.get("MY_AGENT_RAG_ENABLED", "1") == "1"


def init_indexes():
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("""CREATE TABLE IF NOT EXISTS rag_indexes(
            user_id TEXT NOT NULL, document_id TEXT NOT NULL, content_hash TEXT NOT NULL,
            model TEXT NOT NULL, settings_key TEXT NOT NULL, split_version TEXT NOT NULL,
            generation TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('PENDING','INDEXING','READY','FAILED')),
            model_revision TEXT NOT NULL DEFAULT '', dimension INTEGER, chunk_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL, updated_at REAL NOT NULL, failure_reason TEXT NOT NULL DEFAULT '',
            worker_token TEXT NOT NULL DEFAULT '', lease_until REAL NOT NULL DEFAULT 0,
            PRIMARY KEY(user_id,document_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS rag_cleanup(
            user_id TEXT,document_id TEXT,settings_key TEXT,model_revision TEXT,generation TEXT PRIMARY KEY,
            attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,failure_reason TEXT NOT NULL DEFAULT '')""")
        db.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES (6)")


def rowdict(db, user, identity):
    db.row_factory = __import__('sqlite3').Row
    row = db.execute("SELECT * FROM rag_indexes WHERE user_id=? AND document_id=?", (user, identity)).fetchone()
    return dict(row) if row else None


def queue_cleanup(db, row):
    if row and row['model_revision']:
        db.execute("INSERT OR IGNORE INTO rag_cleanup(user_id,document_id,settings_key,model_revision,generation) VALUES (?,?,?,?,?)",
                   tuple(row[k] for k in ('user_id','document_id','settings_key','model_revision','generation')))


def enqueue(user, identity, force=False):
    from src.server.documents import get_document
    get_document(user, identity)
    cfg = settings()
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        content = db.execute("SELECT digest FROM documents WHERE id=? AND user_id=?", (identity,user)).fetchone()
        if not content:
            raise ValueError("文件已删除")
        old = rowdict(db,user,identity)
        if old and not force and old['settings_key']==cfg.key and old['content_hash']==content[0]:
            return old
        queue_cleanup(db,old)
        now = time.time()
        db.execute("""INSERT INTO rag_indexes(user_id,document_id,content_hash,model,settings_key,split_version,generation,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,'PENDING',?,?) ON CONFLICT(user_id,document_id) DO UPDATE SET
            content_hash=excluded.content_hash, model=excluded.model,settings_key=excluded.settings_key,
            split_version=excluded.split_version,generation=excluded.generation,status='PENDING',model_revision='',
            dimension=NULL,chunk_count=0,updated_at=excluded.updated_at,failure_reason='',worker_token='',lease_until=0""",
            (user,identity,content[0],cfg.model,cfg.key,VERSION,uuid4().hex,now,now))
        return rowdict(db,user,identity)


def statuses(user):
    try:
        key = settings().key
    except ValueError:
        key = None
    with database() as db:
        db.row_factory = __import__('sqlite3').Row
        rows = db.execute("SELECT r.* FROM rag_indexes r JOIN documents d ON d.id=r.document_id AND d.user_id=r.user_id WHERE r.user_id=?",(user,)).fetchall()
    result = {}
    for raw in rows:
        row = dict(raw)
        stale = key != row['settings_key']
        result[row['document_id']] = {"status": "PENDING" if stale else row['status'], "model": row['model'],
            "dimension": row['dimension'], "generation": row['generation'], "chunk_count": row['chunk_count'],
            "failure_reason": "配置变化，等待重建" if stale else row['failure_reason']}
    return result


def remove_document(user, identity):
    from src.server.documents import get_document
    get_document(user,identity)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        from src.server.conversations import scoped,storage_session
        if scoped(user):
            db.execute('DELETE FROM conversation_documents WHERE user_id=? AND session_id=? AND document_id=?',(user,storage_session(user),identity))
            if db.execute('SELECT 1 FROM conversation_documents WHERE user_id=? AND document_id=?',(user,identity)).fetchone():return
        else:db.execute('DELETE FROM conversation_documents WHERE user_id=? AND document_id=?',(user,identity))
        queue_cleanup(db,rowdict(db,user,identity))
        db.execute("DELETE FROM rag_indexes WHERE user_id=? AND document_id=?",(user,identity))
        db.execute("DELETE FROM documents WHERE user_id=? AND id=?",(user,identity))


class IndexService:
    def __init__(self, backend_factory=OllamaVectors, store_factory=VectorStore):
        self.backend_factory, self.store_factory = backend_factory, store_factory

    def synchronize(self):
        with database() as db:
            rows = db.execute("SELECT user_id,id FROM documents").fetchall()
        for owner, identity in rows:
            enqueue(owner, identity)
        # Detect a pulled replacement behind the same model tag without embedding any text.
        with database() as db:
            ready = db.execute("SELECT user_id,document_id,model_revision FROM rag_indexes WHERE status='READY'").fetchall()
        if ready:
            try:
                revision = self.backend_factory(settings()).identity()
            except Exception:
                return  # Pending jobs still get explicit FAILED states in run_once.
            for owner, identity, old_revision in ready:
                if old_revision != revision:
                    enqueue(owner, identity, True)

    def cleanup(self):
        with database() as db:
            db.row_factory = __import__('sqlite3').Row
            rows = db.execute("SELECT * FROM rag_cleanup WHERE retry_at<=? AND attempts<3 LIMIT 10",(time.time(),)).fetchall()
        for raw in rows:
            row = dict(raw)
            try:
                self.store_factory(row['user_id'],row['settings_key'],row['model_revision'],None).delete(row['user_id'],row['document_id'],row['generation'])
                with database() as db:
                    db.execute("DELETE FROM rag_cleanup WHERE generation=?",(row['generation'],))
            except Exception:
                with database() as db:
                    db.execute("UPDATE rag_cleanup SET attempts=attempts+1,retry_at=?,failure_reason='向量清理失败，待重试' WHERE generation=?",
                               (time.time()+30,row['generation']))

    def run_once(self):
        from src.server.coordination import operation
        with operation("rag-index-job"):
            return self._run_once()

    def _run_once(self):
        from src.server.coordination import check_lease
        check_lease()
        with database() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE rag_indexes SET status='PENDING',worker_token='',lease_until=0 WHERE status='INDEXING' AND lease_until<?",(time.time(),))
            db.row_factory = __import__('sqlite3').Row
            row = db.execute("SELECT r.* FROM rag_indexes r JOIN documents d ON d.id=r.document_id AND d.user_id=r.user_id WHERE r.status='PENDING' ORDER BY r.updated_at LIMIT 1").fetchone()
            if row is None:
                return False
            job = dict(row)
            token = uuid4().hex
            db.execute("UPDATE rag_indexes SET status='INDEXING',worker_token=?,lease_until=?,updated_at=? WHERE user_id=? AND document_id=?",
                       (token,time.time()+120,time.time(),job['user_id'],job['document_id']))
        user, identity, generation = job['user_id'],job['document_id'],job['generation']
        revision = ''
        try:
            cfg = settings()
            if cfg.key != job['settings_key']:
                enqueue(user,identity,True)
                return True
            backend = self.backend_factory(cfg)
            revision = backend.identity()
            if job['model_revision'] and job['model_revision'] != revision:
                enqueue(user, identity, True)
                return True
            documents = split_documents(load_owned_document(user,identity),cfg.chunk_size,cfg.chunk_overlap)
            with database() as db:
                db.execute("UPDATE rag_indexes SET model_revision=? WHERE user_id=? AND document_id=? AND generation=? AND worker_token=?",(revision,user,identity,generation,token))
            store = self.store_factory(user,cfg.key,revision,backend)
            for start in range(0,len(documents),16):
                check_lease()
                with database() as db:
                    updated = db.execute("UPDATE rag_indexes SET lease_until=? WHERE user_id=? AND document_id=? AND generation=? AND worker_token=?",(time.time()+120,user,identity,generation,token)).rowcount
                if not updated:
                    raise ValueError("索引代次已失效")
                store.upsert(documents[start:start+16],user,identity,generation)
                check_lease()
            if not documents or store.count(user,identity,generation) != len(documents) or not backend.dimension:
                raise ValueError("向量索引完整性校验失败")
            if backend.identity() != revision:
                raise ValueError("建索引过程中Embedding模型发生变化")
            check_lease()
            with database() as db:
                db.execute("BEGIN IMMEDIATE")
                updated = db.execute("""UPDATE rag_indexes SET status='READY',dimension=?,chunk_count=?,updated_at=?,worker_token='',lease_until=0
                    WHERE user_id=? AND document_id=? AND generation=? AND worker_token=?
                    AND EXISTS(SELECT 1 FROM documents WHERE id=? AND user_id=? AND digest=?)""",
                    (backend.dimension,len(documents),time.time(),user,identity,generation,token,identity,user,job['content_hash'])).rowcount
            if not updated:
                raise ValueError("文件已删除或索引代次已更新")
        except Exception as error:
            check_lease()
            # Store only a bounded operational reason, not prompts/tokens/request bodies.
            reason = str(error)[:200] if isinstance(error, ValueError) else "Embedding/Chroma不可用或模型未安装；请检查本地服务后重新索引"
            with database() as db:
                db.execute("UPDATE rag_indexes SET status='FAILED',failure_reason=?,updated_at=?,worker_token='',lease_until=0 WHERE user_id=? AND document_id=? AND generation=? AND worker_token=?",(reason,time.time(),user,identity,generation,token))
                if revision:
                    queue_cleanup(db,{**job,'model_revision':revision})
        return True

    def search(self,user,question,document_ids=None,k=4):
        from src.server.documents import documents, get_document
        if not isinstance(question,str) or not 1<=len(question.strip())<=2000 or type(k) is not int or not 1<=k<=20:
            raise ValueError("问题需1–2000字符，top-k需1–20")
        owned = {doc['id']:doc for doc in documents(user)}
        allowed = list(owned) if document_ids is None else list(dict.fromkeys(document_ids))
        for identity in allowed:
            get_document(user,identity)
        if not allowed:
            return []
        cfg = settings()
        backend = self.backend_factory(cfg)
        revision = backend.identity()
        vector = None
        hits = []
        lexical_candidates = []
        scanned = 0
        from src.retrieval.qa import lexical_evidence_terms
        for identity in allowed:
            row = enqueue(user,identity)
            if row['status'] != 'READY':
                continue
            if row['model_revision'] != revision:
                enqueue(user,identity,True)
                continue
            if vector is None:
                vector = backend.embed_query(question)
            if len(vector) != row['dimension']:
                enqueue(user,identity,True)
                continue
            store = self.store_factory(user,cfg.key,revision,backend)
            if store.count(user,identity,row['generation']) != row['chunk_count']:
                enqueue(user,identity,True)
                continue
            canonical = {doc.id:doc for doc in split_documents(load_owned_document(user,identity),cfg.chunk_size,cfg.chunk_overlap)}
            # Scan only canonical authorized READY sources; bounded across the request.
            for source in canonical.values():
                if scanned >= 5000:
                    break
                scanned += 1
                terms = lexical_evidence_terms(question, source.page_content)
                if terms:
                    lexical_candidates.append((len(terms), identity, row['generation'], source))
            for result,distance in store.search(vector,user,identity,row['generation'],k):
                source = canonical.get(result.metadata.get('chunk_id'))
                if source is None or source.page_content != result.page_content or not math.isfinite(distance):
                    continue
                hits.append({"document_id":identity,"chunk_id":source.id,"text":source.page_content,
                             "source":source.metadata,"distance":float(distance),"similarity":max(-1.0,min(1.0,1-float(distance))),"generation":row['generation'],"retrieval_channels":["vector"]})
        with database() as db:
            valid = {(r[0],r[1]) for r in db.execute("SELECT r.document_id,r.generation FROM rag_indexes r JOIN documents d ON d.id=r.document_id AND d.user_id=r.user_id WHERE r.user_id=? AND r.status='READY' AND r.settings_key=?",(user,cfg.key))}
        vector_hits = sorted((hit for hit in hits if (hit['document_id'],hit['generation']) in valid),key=lambda h:h['distance'])[:k]
        merged = {h['chunk_id']:h for h in vector_hits}
        candidates = sorted((item for item in lexical_candidates if (item[1],item[2]) in valid),
                            key=lambda item:(-item[0],item[1],item[3].id))[:8]
        missing = [item for item in candidates if item[3].id not in merged]
        vectors = backend.embed_documents([item[3].page_content for item in missing]) if missing else []
        if len(vectors) != len(missing):
            raise ValueError("Invalid lexical embedding count")
        for (_,identity,generation,source),values in zip(missing,vectors):
            if len(values) != len(vector) or any(not math.isfinite(x) for x in values):
                raise ValueError("Invalid lexical embedding")
            norm = math.sqrt(sum(x*x for x in vector)*sum(x*x for x in values))
            if not norm:
                raise ValueError("Zero lexical embedding")
            similarity = max(-1.0,min(1.0,sum(a*b for a,b in zip(vector,values))/norm))
            merged[source.id] = {"document_id":identity,"chunk_id":source.id,"text":source.page_content,
                "source":source.metadata,"distance":1-similarity,"similarity":similarity,
                "generation":generation,"retrieval_channels":[]}
        for _,_,_,source in candidates:
            merged[source.id]['retrieval_channels'].append('lexical')
        # Check live visibility/generation again after the additional embedding call.
        if backend.identity() != revision:
            raise ValueError("Embedding revision changed during retrieval")
        current = statuses(user)
        result = []
        for hit in merged.values():
            get_document(user,hit['document_id'])
            row = current.get(hit['document_id'],{})
            if row.get('status') == 'READY' and row.get('generation') == hit['generation']:
                result.append(hit)
        return sorted(result,key=lambda h:(h['distance'],h['chunk_id']))


@contextmanager
def index_worker():
    stop = Event()
    def loop():
        service = IndexService()
        next_sync = 0
        while not stop.is_set():
            try:
                from src.server.coordination import operation
                with operation("rag-background"):
                    if time.time() >= next_sync:
                        service.synchronize()
                        next_sync = time.time()+15
                    service.cleanup()
                    progressed = service.run_once()
            except Exception:
                progressed = False
            stop.wait(.2 if progressed else 2)
    thread = None
    if enabled():
        thread = Thread(target=loop,daemon=True,name="rag-indexer")
        thread.start()
    try:
        yield
    finally:
        stop.set()
        if thread:
            thread.join(timeout=2)
