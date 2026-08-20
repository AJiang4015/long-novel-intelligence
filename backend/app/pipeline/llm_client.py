import httpx
from pydantic import ValidationError

from app.schemas.llm import ExtractionResult

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

    def extract_chunk(self, text: str) -> ExtractionResult:
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
            raise LLMRetryableError(f"http_{response.status_code}")
        if response.status_code >= 400:
            raise LLMError(f"http_{response.status_code}")
        try:
            content = response.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMValidationError("invalid_response_shape") from exc
        try:
            return ExtractionResult.model_validate_json(content)
        except ValidationError as exc:
            raise LLMValidationError("validation_error") from exc
