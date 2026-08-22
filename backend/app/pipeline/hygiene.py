"""V0.2.4 mention hygiene：deterministic hard rules。

只负责高置信 COLLECTIVE / INVALID 直接过滤。
GENERIC / DESCRIPTIVE / COMPOSITE 由 LLM extract category 分类，
本模块**不得**返回这些类别（返回 None → resolver 走 LLM category 或 legacy PERSON fallback）。
"""
import re

from app.schemas.llm import MentionCategory

MAX_NAME_LEN = 50  # 与 Character.name 上限一致

# 集合量词模式：两个儿子/兄弟二人/父子三人/两弟兄/三个儿子 …
_COLLECTIVE_PATTERNS = [
    re.compile(r"^[一二两三四五六七八九十百多诸]+个?(儿子|兄弟|儿女|子女|姐妹|弟兄)$"),
    re.compile(r"^兄弟[一二两三四五六七八九十]+人$"),
    re.compile(r"^父子[一二两三四五六七八九十]+人$"),
    re.compile(r"^两弟兄$"),
    re.compile(r"^[一二两三四五六七八九十百多诸]+个?(小孩|孩子|女子|男子|青年|老人|妇人)们?$"),
]

_INVALID_PATTERNS = [
    re.compile(r"^\s*$"),          # 空/纯空白
    re.compile(r"^\d+$"),          # 纯数字
    re.compile(r"^[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?~`]+$"),  # 纯符号
]

# V0.2.4-b RC3：relational generic 精确词表（归入 GENERIC，不新增 Enum）。
# 只限制「建立 canonical 的资格」：有候选可 alias，无候选丢弃，永不新建 canonical。
# 精确词匹配（name in set），不做子串匹配，避免误伤「顺顺的兄弟」等描述性 mention。
# 注意：祖父/父亲/母亲 暂不进入本词表，是基于《边城》当前数据验证（正文真实人物）的
# **项目级决策，不是通用语义规则**——换小说时需重新评估这些词是否该入表。
_RELATIONAL_GENERIC_WORDS = {
    "兄弟", "哥哥", "弟弟", "姐姐", "妹妹", "儿子", "女儿",
    "妻子", "丈夫", "祖母", "外婆", "外公", "叔叔", "婶婶", "侄儿", "侄女",
}


def classify_mention(name: str) -> MentionCategory | None:
    """deterministic hard rules：仅返回 COLLECTIVE / INVALID；否则 None。

    None 表示「hard rules 未命中」——resolver 应使用 LLM category，
    或（category 也为 None 时）按 legacy PERSON fallback 处理。
    """
    if name is None or len(name) > MAX_NAME_LEN:
        return MentionCategory.INVALID
    for pat in _INVALID_PATTERNS:
        if pat.match(name):
            return MentionCategory.INVALID
    for pat in _COLLECTIVE_PATTERNS:
        if pat.match(name):
            return MentionCategory.COLLECTIVE
    # V0.2.4-b RC3：relational generic 精确词 → GENERIC（有候选可 alias，无候选丢弃，永不 canonical）
    if name in _RELATIONAL_GENERIC_WORDS:
        return MentionCategory.GENERIC
    return None


def is_hard_filtered(name: str) -> bool:
    """COLLECTIVE / INVALID 直接过滤。"""
    return classify_mention(name) in (MentionCategory.COLLECTIVE, MentionCategory.INVALID)
