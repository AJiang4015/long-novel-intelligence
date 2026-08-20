from fastapi import APIRouter, HTTPException, Request

from app.schemas.api import CharacterCandidate, GraphResponse

router = APIRouter(prefix="/api", tags=["characters"])


@router.get("/novels/{novel_id}/characters", response_model=list[CharacterCandidate])
def search_characters(request: Request, novel_id: str, q: str = "") -> list[CharacterCandidate]:
    db = request.app.state.db
    if db.get_novel(novel_id) is None:
        raise HTTPException(status_code=404, detail="小说不存在")
    return db.search_characters(novel_id, q, limit=10)


@router.get("/characters/{character_id}/graph", response_model=GraphResponse)
def get_character_graph(character_id: str, request: Request) -> GraphResponse:
    db = request.app.state.db
    # novel_id + character_id 双层隔离：novel_id 由人物节点自身属性解析
    center = db.get_character_by_id_global(character_id)
    if center is None:
        raise HTTPException(status_code=404, detail="人物不存在")
    graph = db.get_subgraph(center["novel_id"], character_id)
    return GraphResponse(**graph)
