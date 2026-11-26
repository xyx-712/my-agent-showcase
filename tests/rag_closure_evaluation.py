"""Real local RAG acceptance, fictional sources, isolated SQLite and Chroma."""
import io
import json
import os
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient
from docx import Document
from pypdf import PdfReader, PdfWriter
from tests.vector_index_evaluation import setup, close_test_chroma
from tests.abstract_evaluation import pdf


def run():
    os.environ['MY_AGENT_RAG_ENABLED'] = '0'
    os.environ['MY_AGENT_EMBEDDING_MODEL'] = 'embeddinggemma'
    os.environ.pop('MY_AGENT_CHROMA_DIR', None)
    os.environ.pop('MY_AGENT_CHROMA_URL', None)
    started = time.perf_counter()
    report = {}
    with tempfile.TemporaryDirectory() as directory:
        app, agent, session, Service = setup(directory)
        from src.retrieval.service import enqueue
        from src.retrieval.qa import answer
        from src.server.documents import get_document
        from src.agent.model_provider import get_chat_model
        from langchain_core.callbacks import BaseCallbackHandler
        class Recorder(BaseCallbackHandler):
            def on_llm_end(self, response, **kwargs):
                print('MODEL_OUTPUT', response.generations[0][0].text, flush=True)
        model = get_chat_model().model_copy(update={'callbacks':[Recorder()]})
        service = Service()
        try:
            with TestClient(app, headers={'Origin':'http://127.0.0.1:5173'}) as client:
                client.post('/session', json={}).raise_for_status()
                def upload(name, content):
                    identity = client.post('/documents', files={'file':(name, content)}).raise_for_status().json()['id']
                    with session.app_db() as db:
                        owner = db.execute('SELECT user_id FROM documents WHERE id=?',(identity,)).fetchone()[0]
                    enqueue(owner, identity)
                    assert service.run_once()
                    return owner, identity
                owner, a = upload('annual.txt', '青禾公司员工年假申请规定：员工年假额度为每年十五天。'.encode())
                _, b = upload('approval.txt', '青禾公司员工年假申请流程：休假需提前三天向直属主管提出申请，由直属主管审批。'.encode())
                question = '青禾员工年假额度为几天，需提前几天向谁申请？'
                hits = service.search(owner, question, [a,b],4)
                report['cross_document_scores'] = [{'file':h['source']['name'],'score':h['similarity']} for h in hits]
                text, citations, audit = answer(owner,question,[a,b],model,service)
                report['cross_document_answer'] = {'text':text,'files':[c['file_id'] for c in citations], 'audit':audit}
                assert {c['file_id'] for c in citations} == {a,b}, report
                assert ('十五' in text or '15' in text) and ('三' in text or '3' in text) and '主管' in text
                # Same-topic question; number/payment policy deliberately absent.
                text, citations, audit = answer(owner,'青禾公司员工年假未休完可以折算多少元现金？',[a,b],model,service)
                report['same_topic_absent'] = {'text':text,'citations':citations,'audit':audit}
                assert not citations, report['same_topic_absent']
                writer = PdfWriter()
                for lines in (['Unrelated introduction.'],['Library opening hours: Monday to Friday, 9 AM to 6 PM.']):
                    writer.add_page(PdfReader(io.BytesIO(pdf(lines))).pages[0])
                stream=io.BytesIO();writer.write(stream)
                _, p = upload('hours.pdf', stream.getvalue())
                text, citations, _ = answer(owner,'What are the library opening hours?', [p],model,service)
                assert citations and all(c['page']==2 for c in citations), (text,citations)
                report['pdf']={'text':text,'citations':citations}
                doc=Document();doc.add_paragraph('青禾食堂的午餐供应时间是每天十二点到十三点。')
                table=doc.add_table(rows=1,cols=1);table.cell(0,0).text='青禾食堂的午餐价格为每份二十元。'
                stream=io.BytesIO();doc.save(stream)
                _, d = upload('canteen.docx',stream.getvalue())
                report['docx']=[]
                for question,field in [('青禾食堂午餐供应时间是什么？','paragraph'),('青禾食堂的午餐价格为每份多少元？','table')]:
                    print('DOCX_RETRIEVAL', question, [(h['text'],h['similarity']) for h in service.search(owner,question,[d],4)],flush=True)
                    text,citations,_=answer(owner,question,[d],model,service)
                    valid = bool(citations) and any(field in c for c in citations)
                    assert all(c['page'] is None for c in citations)
                    original=get_document(owner,d)
                    assert all(any(c['text'] in parent['text'] for parent in original['chunks']) for c in citations)
                    report['docx'].append({'text':text,'citations':citations,'location_pass':valid})
                fixture=json.loads((Path(__file__).parent/'fixtures/rag_chinese.json').read_text(encoding='utf-8'))
                ids={}
                for document in fixture['documents']:
                    _, ids[document['id']] = upload(document['name'], document['text'].encode())
                questions=[(q['question'],ids[q['expected']]) for q in fixture['queries']]
                questions += [('休年假要提前几日报批？',ids['leave']),('恢复数据库由谁负责？',ids['backup'])]
                negatives=['火星大气中氩气的比例是多少？','量子纠缠的实验装置如何搭建？','巴黎铁塔有多高？']
                positives=[service.search(owner,q,list(ids.values()),4) for q,_ in questions]
                negative_hits=[service.search(owner,q,list(ids.values()),4) for q in negatives]
                report['thresholds']=[]
                for threshold in (.5,.55,.6,.65,.7,.75):
                    recalled=sum(any(h['document_id']==expected and h['similarity']>=threshold for h in hits) for hits,(_,expected) in zip(positives,questions))
                    false_accept=sum(any(h['similarity']>=threshold for h in hits) for hits in negative_hits)
                    report['thresholds'].append({'threshold':threshold,'positive_recall':f'{recalled}/{len(questions)}','negative_accept':f'{false_accept}/{len(negatives)}'})
                report['scores']=[{'question':q,'expected':expected,'hits':[{'file':h['source']['name'],'score':h['similarity']} for h in hits]} for (q,expected),hits in zip(questions,positives)]
            report['elapsed_seconds']=round(time.perf_counter()-started,3)
            print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
            assert all(item['location_pass'] for item in report['docx']), 'DOCX answer/location acceptance incomplete; see report'
            print('PASS real cross-document, absent answer, PDF page, DOCX paragraph/table and threshold evaluation')
        finally:
            agent.conn.close()
            close_test_chroma()


if __name__=='__main__': run()
