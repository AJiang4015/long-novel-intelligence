import json
import logging
import time

import httpx
from pydantic import ValidationError

from app.schemas.llm import ExtractionResult

logger = logging.getLogger("app.llm_client")

EXTRACTION_SYSTEM_PROMPT = """你是小说人物关系抽取器。给定一段小说文本，抽取其中明确出现的人物，以及人物之间明确的关系。
严格要求：
1. 只抽取文本中明确出现的人物与关系，不要臆测。
2. characters: 文本中出现的人物姓名列表（同一人物按文本中的写法输出，不要合并别名）。
3. relationships: 人物之间的关系。source 是当前文本片段中作为关系主体的人物，target 是与其发生关系的人物。
4. type 只能使用以下 7 个枚举值之一：love（爱情）、family（血缘/家族）、friendship（友谊）、enmity（敌对/仇怨）、alliance（结盟/合作）、mentorship（师徒/师生）、other（其他无法归类的明确关系）。禁止自创类型，如 romantic、lover、亲密、爱情、love_relation 等一律归入 love。
5. confidence: 0 到 1 之间的浮点数，表示你对这条关系判断的把握程度。
6. 只输出 JSON 对象，不要输出任何其他文字。格式：
{"characters": [{"name": "..."}], "relationships": [{"source": "...", "target": "...", "type": "love", "confidence": 0.9}]}"""

EXTRACTION_USER_PROMPT = "请抽取以下文本中的人物与关系：\n\n{text}"

ALIAS_JUDGE_SYSTEM_PROMPT = """你是小说人物实体消歧判定器。给定一段小说文本与若干「待判定的人物名及其候选人物」，判断每个待判定名字是否与某个候选人物是同一人。
严格要求：
1. 只依据提供的文本与候选信息判断，不要使用任何外部小说知识。
2. 每个 mention 最多输出一条 resolution；resolves_to 只能是该 mention 的候选之一，或 null（表示不是任何候选）。
3. 禁止创造输入之外的新人物名；不得修改 mention 本身。
4. 只输出 JSON：{"resolutions": [{"mention": "...", "resolves_to": "..."}]}"""

ALIAS_JUDGE_USER_PROMPT = """小说文本：
{text}

待判定人物（含候选）：
{mentions}

请输出判定结果。"""

MERGE_JUDGE_SYSTEM_PROMPT = """你是小说人物实体合并判定器。给定若干对「待判定是否同一人的两个人物」及其桥接证据，判断每对人物是否指向同一人。
严格要求：
1. 只依据提供的两侧人物信息与桥接证据判断，不要使用任何外部小说知识。
2. 每对人物输出一条判定；a/b 必须原样来自输入，禁止修改、禁止创造新名字。
3. merge 必须是布尔值：true 表示同一人，false 表示不同人。
4. confidence 是 0 到 1 之间的浮点数，表示你对判定的把握程度。
5. 只输出 JSON：{"merges": [{"a": "...", "b": "...", "merge": true, "confidence": 0.9}]}"""

MERGE_JUDGE_USER_PROMPT = """待判定人物对：
{pairs}

请输出判定结果。"""


class LLMError(Exception):
    """LLM 抽取失败基类。"""


class LLMRetryableError(LLMError):
    """可重试错误：429 / 5xx。"""


class LLMValidationError(LLMError):
    """不可重试错误：JSON 解析失败或 Pydantic 校验失败。"""


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, http_client: httpx.Client | None = None):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._client = http_client or httpx.Client(timeout=60)

    def _log_error(self, stage: str, response: httpx.Response, detail: str = "") -> None:
        """诊断日志：stage / HTTP status / response body 摘要。绝不记录 Authorization 头或 API key。"""
        body = (getattr(response, "text", "") or "")[:300].replace("\n", " ")
        logger.warning(
            "[llm] stage=%s status=%s detail=%s body=%s",
            stage, response.status_code, detail, body,
        )

    def extract_chunk(self, text: str) -> ExtractionResult:
        """调用 LLM 抽取单块文本的人物与关系，并按可重试/不可重试区分异常。"""
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": EXTRACTION_USER_PROMPT.format(text=text)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.2,
            },
        )
        if response.status_code == 429 or response.status_code >= 500:
            self._log_error("extract", response)
            raise LLMRetryableError(f"http_{response.status_code}")
        if response.status_code >= 400:
            self._log_error("extract", response)
            raise LLMError(f"http_{response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            self._log_error("extract", response, "invalid_response_shape")
            raise LLMValidationError("invalid_response_shape") from exc
        try:
            return ExtractionResult.model_validate_json(content)
        except ValidationError as exc:
            self._log_error("extract", response, "validation_error")
            raise LLMValidationError("validation_error") from exc

    def judge_aliases(self, chunk_text: str, pending: list["PendingMention"]) -> "AliasJudgeResult":
        """批量判定别名。429/5xx 重试 1 次；validation error 不重试（沿用 extract_one 的失败分类模式）。"""
        from app.schemas.llm import AliasJudgeResult
        mentions_json = json.dumps(
            [{"mention": p.mention,
              "candidates": [{"canonical": c.canonical, "matched_names": c.matched_names}
                             for c in p.candidates]}
             for p in pending],
            ensure_ascii=False,
        )
        for attempt in range(2):  # 首次 + 重试 1 次
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": ALIAS_JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": ALIAS_JUDGE_USER_PROMPT.format(text=chunk_text, mentions=mentions_json)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                self._log_error("judge", response)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMRetryableError(f"http_{response.status_code}")
            if response.status_code >= 400:
                self._log_error("judge", response)
                raise LLMError(f"http_{response.status_code}")
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                self._log_error("judge", response, "invalid_response_shape")
                raise LLMValidationError("invalid_response_shape") from exc
            try:
                return AliasJudgeResult.model_validate_json(content)
            except ValidationError as exc:
                self._log_error("judge", response, "validation_error")
                raise LLMValidationError("validation_error") from exc

    def judge_merges(self, pairs: list["MergePair"]) -> "MergeJudgeResult":
        """批量判定 canonical 是否同一人（V0.2.3-b1）。429/5xx 重试 1 次；validation 不重试。"""
        from app.schemas.llm import MergeJudgeResult
        pairs_json = json.dumps(
            [{"a": {"canonical": p.a.canonical, "aliases": p.a.aliases,
                    "first_seen_chunk": p.a.first_seen_chunk,
                    "mention_count": p.a.mention_count, "chapters": p.a.chapters},
              "b": {"canonical": p.b.canonical, "aliases": p.b.aliases,
                    "first_seen_chunk": p.b.first_seen_chunk,
                    "mention_count": p.b.mention_count, "chapters": p.b.chapters},
              "bridge_evidence": [{"chunk_id": e.chunk_id, "chapter_id": e.chapter_id,
                                   "mention": e.mention, "text": e.text}
                                  for e in p.bridge_evidence]}
             for p in pairs],
            ensure_ascii=False,
        )
        for attempt in range(2):  # 首次 + 重试 1 次
            response = self._client.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": self._model,
                    "messages": [
                        {"role": "system", "content": MERGE_JUDGE_SYSTEM_PROMPT},
                        {"role": "user", "content": MERGE_JUDGE_USER_PROMPT.format(pairs=pairs_json)},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                self._log_error("merge_judge", response)
                if attempt == 0:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMRetryableError(f"http_{response.status_code}")
            if response.status_code >= 400:
                self._log_error("merge_judge", response)
                raise LLMError(f"http_{response.status_code}")
            try:
                content = response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError) as exc:
                self._log_error("merge_judge", response, "invalid_response_shape")
                raise LLMValidationError("invalid_response_shape") from exc
            try:
                return MergeJudgeResult.model_validate_json(content)
            except ValidationError as exc:
                self._log_error("merge_judge", response, "validation_error")
                raise LLMValidationError("validation_error") from exc
