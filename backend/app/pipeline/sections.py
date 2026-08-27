"""V0.2.5-a：EPUB 章节 section 分类（确定性内容/位置启发式）。

只负责 METADATA / EPIGRAPH / BODY / TRAILER 分类。
默认 BODY（保守）：只有高置信标记命中才触发限制。
标记词表是《边城》等中文 EPUB 验证的**项目级规则，不是通用语义规则**——
换小说时需重新评估（与 hygiene._RELATIONAL_GENERIC_WORDS 同哲学，见 P016 Do Not Reopen）。
本模块不依赖 app 内其他模块（避免与 epub_reader 循环导入）。
"""
import re
from enum import Enum


class SectionType(str, Enum):
    """章节类型：非正文（METADATA/EPIGRAPH/TRAILER）在 ER 中受注册门控。"""
    METADATA = "metadata"     # 版权/封面/目录
    EPIGRAPH = "epigraph"     # 题记/新题记/序/前言（PREFACE 并入）
    BODY = "body"             # 正文
    TRAILER = "trailer"       # 推广/广告/后记标记


# 标题关键词（EPUB item title 可用时；短词如「序」「跋」按包含匹配，属项目级启发式）
_TITLE_MARKERS: dict[str, SectionType] = {
    "版权": SectionType.METADATA,
    "目录": SectionType.METADATA,
    "题记": SectionType.EPIGRAPH,
    "新题记": SectionType.EPIGRAPH,
    "序": SectionType.EPIGRAPH,
    "前言": SectionType.EPIGRAPH,
    "引言": SectionType.EPIGRAPH,
    "跋": SectionType.TRAILER,
    "后记": SectionType.TRAILER,
    "致谢": SectionType.TRAILER,
    "广告": SectionType.TRAILER,
    "推广": SectionType.TRAILER,
}

# 首非空行标记（内容启发式；《边城》验证）
_FIRST_LINE_MARKERS: list[tuple[str, SectionType]] = [
    ("版权信息", SectionType.METADATA),
    ("作者：", SectionType.METADATA),
    ("题记", SectionType.EPIGRAPH),
    ("新题记", SectionType.EPIGRAPH),
    ("关注公众号", SectionType.TRAILER),
    ("微信搜索", SectionType.TRAILER),
    ("mp.weixin", SectionType.TRAILER),
]

# 正文章序号（首行命中即 BODY）
_BODY_DI_N_RE = re.compile(r"^第[一二三四五六七八九十百0-9]+[章节回]")
_BODY_CN_NUM_BARE_RE = re.compile(r"^[一二三四五六七八九十]+$")
_BODY_CN_NUM_SEP_RE = re.compile(r"^[一二三四五六七八九十]+[\s、.．]")

# 位置弱信号阈值（仅兜底）
_METADATA_MAX_LEN = 200
_TRAILER_MAX_LEN = 500


def classify_chapter(title: str, text: str, index: int, total: int) -> SectionType:
    """按优先级分类：标题关键词 → 首非空行标记 → 正文序号 → 位置弱信号 → 默认 BODY。"""
    t = (title or "").strip()
    for kw, sec in _TITLE_MARKERS.items():
        if kw in t:
            return sec
    first_line = _first_nonempty_line(text)
    if first_line:
        for marker, sec in _FIRST_LINE_MARKERS:
            if marker in first_line:
                return sec
        if _BODY_DI_N_RE.match(first_line) or _BODY_CN_NUM_BARE_RE.match(first_line) \
                or _BODY_CN_NUM_SEP_RE.match(first_line):
            return SectionType.BODY
    # 位置弱信号（仅兜底，避免误分类正文）
    if index == 0 and len(text) <= _METADATA_MAX_LEN \
            and ("版权" in text or "作者" in text):
        return SectionType.METADATA
    if index == total - 1 and len(text) <= _TRAILER_MAX_LEN \
            and any(m in text for m in ("公众号", "微信", "mp.weixin")):
        return SectionType.TRAILER
    return SectionType.BODY


def _first_nonempty_line(text: str) -> str | None:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return None
