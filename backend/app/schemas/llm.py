from enum import Enum

from pydantic import BaseModel, Field, model_validator


class RelationshipType(str, Enum):
    love = "love"
    family = "family"
    friendship = "friendship"
    enmity = "enmity"
    alliance = "alliance"
    mentorship = "mentorship"
    other = "other"


class Character(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class Relationship(BaseModel):
    source: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=50)
    type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractionResult(BaseModel):
    characters: list[Character]
    relationships: list[Relationship]

    @model_validator(mode="after")
    def drop_self_loops(self):
        """业务校验：source != target，self-loop 直接丢弃。"""
        self.relationships = [r for r in self.relationships if r.source != r.target]
        return self


class AliasCandidate(BaseModel):
    canonical: str = Field(min_length=1, max_length=50)
    matched_names: list[str] = Field(default_factory=list)


class PendingMention(BaseModel):
    mention: str = Field(min_length=1, max_length=50)
    candidates: list[AliasCandidate] = Field(default_factory=list)


class AliasResolution(BaseModel):
    mention: str = Field(min_length=1, max_length=50)
    resolves_to: str | None = Field(default=None, min_length=1, max_length=50)


class AliasJudgeResult(BaseModel):
    resolutions: list[AliasResolution] = Field(default_factory=list)

    @model_validator(mode="after")
    def dedupe_mentions(self):
        seen: set[str] = set()
        kept: list[AliasResolution] = []
        for r in self.resolutions:
            if r.mention not in seen:
                seen.add(r.mention)
                kept.append(r)
        self.resolutions = kept
        return self


# ---- V0.2.3-b1 canonical merge 契约（独立于 alias judge）----


class MergePairSide(BaseModel):
    canonical: str = Field(min_length=1, max_length=50)
    aliases: list[str] = Field(default_factory=list)
    first_seen_chunk: int = Field(ge=0)
    mention_count: int = Field(ge=0)
    chapters: list[int] = Field(default_factory=list)


class BridgeEvidence(BaseModel):
    chunk_id: int = Field(ge=0)
    chapter_id: int = Field(ge=0)
    mention: str = Field(min_length=1, max_length=50)
    text: str = Field(default="")


class MergePair(BaseModel):
    a: MergePairSide
    b: MergePairSide
    bridge_evidence: list[BridgeEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def a_neq_b(self):
        if self.a.canonical == self.b.canonical:
            raise ValueError("merge pair 两侧 canonical 不得相同")
        return self


class MergeDecision(BaseModel):
    a: str = Field(min_length=1, max_length=50)
    b: str = Field(min_length=1, max_length=50)
    merge: bool
    confidence: float = Field(ge=0.0, le=1.0)


class MergeJudgeResult(BaseModel):
    merges: list[MergeDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def dedupe_pairs(self):
        seen: set[frozenset] = set()
        kept: list[MergeDecision] = []
        for m in self.merges:
            key = frozenset((m.a, m.b))
            if key not in seen:
                seen.add(key)
                kept.append(m)
        self.merges = kept
        return self
