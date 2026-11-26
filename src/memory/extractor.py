import re


def extract_operations(text):
    """Conservative user-only wrapper; legacy extract_memory remains compatible."""
    if not isinstance(text,str):return []
    text=text.strip()
    if text.endswith(('?','？')):return []
    if re.search(r'^我叫(?:什么|啥)|^我是谁|^我的(?:名字|姓名|职业|工作|爱好|兴趣)(?:是|叫)?(?:什么|啥)',text):return []
    if re.search(r'["“”‘’「」『』`]|他说|她说|文档|附件|简历|第三方|引用|例如|示例|假设|如果|假如|扮演|角色|临时|仅本次|这次|今天|这轮',text):return []
    if not re.match(r'我|不对|不喜欢|不爱|不再喜欢|忘记|删除|不要记|别记|更正|纠正|改名|请记住|重新记住|确认',text):return []
    kind='restore' if '重新记住' in text else 'correction' if re.search(r'不对|更正|纠正|改名|改为|改成|换成|确认|我现在叫',text) else 'statement'
    uncertain=bool(re.search(r'可能|也许|大概|不确定|还是|或者|或许',text))
    whole=re.fullmatch(r'(?:请)?(?:忘记|删除|不要记住|别记住)(?:我的)?(名字|姓名|职业|工作|爱好|兴趣|全部记忆)[。！! ]*',text)
    if whole:
        mapping={'名字':'name','姓名':'name','职业':'job','工作':'job','爱好':'hobby','兴趣':'hobby'}
        if whole[1]=='全部记忆':return [{'action':'delete_all','key':'*','intent':'statement'}]
        keys=[mapping[whole[1]]]
        return [{'action':'delete_key','key':key,'intent':kind} for key in dict.fromkeys(keys)]
    normalized=re.sub(r'^(?:请记住|重新记住)[，,:： ]*','',text)
    normalized=normalized.replace('我现在叫','我叫')
    changed=re.search(r'我的(名字|工作|职业|爱好|兴趣)(?:现在)?(?:改为|改成|换成)([^，。！？!?]+)',normalized)
    if changed:
        key={'名字':'name','工作':'job','职业':'job','爱好':'hobby','兴趣':'hobby'}[changed[1]]
        return [{'action':'save','key':key,'value':clean_value(changed[2]),'intent':'candidate' if uncertain else 'replace'}]
    operations=extract_memory(normalized)
    names=list(dict.fromkeys(re.findall(r'(?:我叫|我的名字是|我的名字叫|我改名叫|改名为)([\u4e00-\u9fa5]{2,4})(?=$|[，。！!？?；;\s])',normalized)))
    operations=[op for op in operations if op['key']!='name']
    for name in (names if len(names)>1 and kind=='statement' else names[-1:]):
        operations.insert(0,{'action':'save','key':'name','value':clean_value(name),
                             'intent':'candidate' if len(names)>1 and kind=='statement' else kind})
    explicit_job=re.search(r'我的(?:工作|职业)(?:现在)?是([^。；\n，,]+)',normalized)
    if explicit_job and explicit_job[1] not in {'什么','啥'}:
        operations=[op for op in operations if op['key']!='job']
        operations.append({'action':'save','key':'job','value':clean_value(explicit_job[1])})
    elif any(op['key']=='job' for op in operations):
        for op in operations:
            if op['key']=='job':op['intent']='candidate'
    if uncertain:operations=[{**op,'intent':'candidate'} for op in operations if op['action']=='save']
    return [{**op,'intent':op.get('intent',kind)} for op in operations]


HOBBY_NEGATION = r"(?:现在)?(?:不再喜欢|不再爱|不喜欢|不爱|讨厌)"
HOBBY_DELETE = rf"(?:我|^){HOBBY_NEGATION}|忘记|删除|不要记|别记"
HOBBY_SAVE = r"我(?:现在)?喜欢|我爱好|我的兴趣是|我的爱好是"
HOBBY_CLAUSE_BREAK = re.compile(
    rf"[。！!？?；;\r\n]+|[，,]\s*(?=(?:{HOBBY_DELETE}|{HOBBY_SAVE}|{HOBBY_NEGATION}))"
)
HOBBY_EXPRESSION = re.compile(
    rf"(?:(?P<delete>{HOBBY_DELETE})|(?:{HOBBY_SAVE}))(?P<values>.+)"
)


def extract_hobbies(text):
    operations = []
    for clause in HOBBY_CLAUSE_BREAK.split(text):
        match = HOBBY_EXPRESSION.search(clause.strip())
        if match:
            action = "delete" if match.group("delete") else "save"
            operations.extend(
                {"action": action, "key": "hobby", "value": value}
                for value in split_values(match.group("values"))
            )
    return operations



# =====================================================
# Memory Extractor
# =====================================================


def extract_memory(text):

    if not text:
        return []

    text = text.strip()

    memories = []

    # =================================================
    # 排除查询句
    # =================================================

    question_patterns = [

        "我叫什么",

        "我是谁",

        "我的名字是什么",

        "你知道我的名字吗",

        "你知道我是谁吗",

        "我喜欢什么",

        "我的兴趣是什么",

        "我的爱好是什么",

        "我的工作是什么",

        "我的职业是什么",

    ]

    for q in question_patterns:

        if q in text:
            return []

    # =================================================
    # name
    # =================================================

    name_patterns = [

        r"我叫([\u4e00-\u9fa5]{2,4})",

        r"我的名字是([\u4e00-\u9fa5]{2,4})",

        r"我的名字叫([\u4e00-\u9fa5]{2,4})",

        r"我改名叫([\u4e00-\u9fa5]{2,4})",

        r"改名为([\u4e00-\u9fa5]{2,4})",

    ]

    for pattern in name_patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            value = clean_value(
                match.group(1)
            )

            if value:

                memories.append(
                    {
                        "action": "save",

                        "key": "name",

                        "value": value
                    }
                )

            break

    memories.extend(extract_hobbies(text))

    # =================================================
    # job
    # =================================================

    job_patterns = [

        r"我的工作是(.+)",

        r"我的职业是(.+)",

        r"我是(.+)",

    ]

    for pattern in job_patterns:

        match = re.search(
            pattern,
            text
        )

        if match:

            value = clean_value(
                match.group(1)
            )

            # 防止：
            # 我是张三
            # 被识别成职业

            if value and not is_name_like(value):

                memories.append(
                    {
                        "action": "save",

                        "key": "job",

                        "value": value
                    }
                )

            break

    return memories


# =====================================================
# 拆分多个记忆值
# =====================================================


def split_values(value):

    if not value:
        return []

    # 支持：
    #
    # 足球和苹果
    # 足球、苹果
    # 足球，苹果
    # 足球,苹果
    #
    # 统一拆分成多个独立值

    values = re.split(
        r"\s*(?:和|、|，|,)\s*",
        value
    )

    result = []

    for item in values:

        item = clean_value(item)

        if item:

            result.append(item)

    return result


# =====================================================
# 清理
# =====================================================


def clean_value(value):

    if not value:
        return ""

    value = value.strip()

    # =================================================
    # 删除句尾语气词
    # =================================================

    value = re.sub(
        r"(了|啦|呢|吧|啊|呀|哦|喽)+$",
        "",
        value
    )

    # =================================================
    # 删除标点
    # =================================================

    value = re.sub(
        r"[。！!？?，,、；;：:]",
        "",
        value
    )

    # =================================================
    # 再次删除句尾语气词
    # =================================================

    value = re.sub(
        r"(了|啦|呢|吧|啊|呀|哦|喽)+$",
        "",
        value
    )

    return value.strip()


# =====================================================
# 判断是否像名字
# =====================================================


def is_name_like(value):

    if not value:
        return True

    # 中文姓名一般 2-4 字

    if re.fullmatch(
        r"[\u4e00-\u9fa5]{2,4}",
        value
    ):

        return True

    return False
