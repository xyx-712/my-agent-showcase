"""Locate explicit abstract sections without changing original source positions."""
import re


def wants_abstract(request):
    return bool(re.search(r"摘要|\babstract\b", request, re.I))


HEADING = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\d+[.、\s]+)?(?:摘\s*要|abstract)(?:\s*[:：]\s*|\s+|$)(.*)$", re.I)
END = re.compile(r"^\s*(?:#{1,6}\s*|\d+[.、\s]+)?(?:关键词|关键字|keywords?|引言|绪论|introduction|正文|参考文献)\b|^\s*#{1,6}\s+|^\s*\d+[.、]\s*\S", re.I)


def candidates(docs):
    result = []
    for doc in docs:
        current = None
        for chunk in doc["chunks"]:
            for offset, line in enumerate(chunk["text"].splitlines()):
                heading = HEADING.match(line)
                if heading:
                    current = {"label": f'{doc["name"]} · ' + (f'第{chunk["page"]}页 · ' if chunk.get("page") else '')
                               + f'L{chunk["start"] + offset}', "sources": [], "has_body": bool(heading[1].strip())}
                    result.append(current)
                elif current and END.match(line):
                    current = None
                if current and line.strip():
                    if not heading:
                        current["has_body"] = True
                    position = chunk["start"] + offset
                    previous = current["sources"][-1] if current["sources"] else None
                    if previous and previous.get("page") == chunk.get("page") and previous["index"] == chunk["index"] and previous["end"] + 1 == position:
                        previous["text"] += "\n" + line
                        previous["end"] = position
                    else:
                        current["sources"].append({**chunk, "file_id": doc["id"], "name": doc["name"],
                                                    "start": position, "end": position, "text": line})
    return [item for item in result if item["has_body"]]
