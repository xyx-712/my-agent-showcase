"""Evidence gated semantic QA using the existing validated document answer chain."""
import os
import re

from src.retrieval.service import IndexService


def general_question(request):
    # Full-document operations must never be reduced to nearest-neighbour evidence.
    return not re.search(r"摘要|总结|概括|汇总|缩写|缩减|压缩|精简|改写|全文|全部|所有|对比|比较|版本|冲突|变更|工期|阶段|批准|计划", request)


def lexical_evidence_terms(question, text):
    """Conservative exact-term fallback over already authorized vector candidates.

    Keep raw cosine untouched. Require two distinct, non-overlapping meaningful
    query terms in the same canonical source. This only selects evidence for the
    existing answerability validator, never proves the answer by itself.
    """
    query = re.sub(r"^\s*(?:根据|依据|按照)(?:已)?上传(?:的)?(?:文件|文档|资料)[，,：:\s]*", "", question).casefold()
    generic = set("几多少谁哪怎什么是否的了在是有给按以和及可吗呢问")
    stop = {"每年", "文件", "文档", "资料", "内容", "根据", "上传", "公司", "问题", "有关", "相关", "the", "and", "for", "what", "who", "how", "does", "from", "document", "file"}
    spans = []
    for match in re.finditer(r"[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z0-9_-]{2,}", query):
        value = match.group()
        if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", value):
            spans.append((match.start(), match.end(), value))
        else:
            spans.extend((match.start()+i, match.start()+i+2, value[i:i+2]) for i in range(len(value)-1))
    selected = []; used = set(); end = -1; source = text.casefold()
    for start, finish, term in spans:
        if start < end or term in used or term in stop or any(c in generic for c in term):
            continue
        present = (re.search(r"(?<![a-z0-9_])"+re.escape(term)+r"(?![a-z0-9_])", source) is not None
                   if term.isascii() else term in source)
        if present:
            selected.append(term); used.add(term); end = finish
    return selected if len(selected) >= 2 else []


def answer(user, request, document_ids, model, service=None):
    from src.agent.skills import answer_documents
    from src.server.documents import get_document
    threshold = float(os.environ.get('MY_AGENT_RAG_MIN_SIMILARITY', '0.65'))
    k = int(os.environ.get('MY_AGENT_RAG_TOP_K', '4'))
    if not 0 <= threshold <= 1 or not 1 <= k <= 12:
        raise ValueError('RAG相关性配置无效')
    service = service or IndexService()
    hits = service.search(user, request, document_ids, k)
    accepted = [h for h in hits if h['similarity'] >= threshold]
    lexical = {h['chunk_id']: lexical_evidence_terms(request, h.get('text', '')) for h in hits}
    accepted = [h for h in hits if h['similarity'] >= threshold or lexical.get(h['chunk_id'])]
    selected_ids = {h['chunk_id'] for h in accepted}
    audit = [{'document_id': h['document_id'], 'chunk_id': h['chunk_id'],
              'generation': h['generation'], 'similarity': h['similarity'],
              'accepted': h['chunk_id'] in selected_ids,
              'accepted_by': ('semantic' if h['similarity'] >= threshold else 'lexical') if h['chunk_id'] in selected_ids else None,
              'lexical_terms': lexical.get(h['chunk_id'], []), 'retrieval_channels': h.get('retrieval_channels', ['vector'])} for h in hits]
    sources = [{**h['source'], 'text': h['text']} for h in accepted]
    if not sources:
        return '资料中没有找到足够依据；请确认文件索引可用或补充相关资料。', [], audit
    text, citations = answer_documents(model, sources, request, evidence_only=True)
    # Recheck live ownership and index generation after the model call, including deletion races.
    from src.retrieval.service import statuses
    current = statuses(user)
    for hit in accepted:
        get_document(user, hit['document_id'])
        row = current.get(hit['document_id'], {})
        if row.get('status') != 'READY' or row.get('generation') != hit['generation']:
            raise ValueError('回答期间资料索引已变化，请重新提问')
    return text, citations, audit
