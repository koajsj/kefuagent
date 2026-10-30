"""Small explicit lexical expansions, not a semantic retrieval model."""

import re

HAN = re.compile(r"[㐀-鿿]")
SYNONYMS = (
    ("邮箱", "电子邮件"),
    ("修改", "更改", "变更"),
    ("账户", "账号"),
    ("客服", "人工服务", "技术支持"),
    ("服务时间", "工作时间", "几点下班", "几点上班"),
    ("价格", "费用", "收费"),
    ("取消", "撤销"),
    ("期限", "多久", "多长时间"),
)
_WORDS = {word: group for group in SYNONYMS for word in group}
_PATTERN = re.compile("|".join(re.escape(word) for word in sorted(_WORDS, key=len, reverse=True)))
_STOP = re.compile(r"请问|如何|怎么|能否|是否|可以|我想|想要|请|吗|呢|的|了|能")


def query_groups(query):
    groups = []

    def expand(match):
        group = _WORDS[match.group()]
        if group not in groups:
            groups.append(group)
        return " "

    rest = _PATTERN.sub(expand, query)
    rest = _STOP.sub(" ", rest)
    for word in re.findall(r"[㐀-鿿]+|[a-zA-Z0-9_]+", rest):
        if HAN.search(word):
            groups.extend((word[i : i + 2],) for i in range(len(word) - 1))
        else:
            groups.append((word.lower(),))
    return list(dict.fromkeys(groups))[:48]


def bigrams(word):
    return [word[i : i + 2] for i in range(len(word) - 1)] if HAN.search(word) else []


def query_expression(groups):
    terms = {term for group in groups for word in group for term in bigrams(word)}
    return " | ".join(sorted(terms))


def coverage(content, groups):
    lowered = content.lower()
    return (
        sum(any(word.lower() in lowered for word in group) for group in groups) / len(groups)
        if groups
        else 0
    )
