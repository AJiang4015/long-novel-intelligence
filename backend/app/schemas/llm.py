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
