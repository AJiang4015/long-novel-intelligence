from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict:
    try:
        request.app.state.db.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Neo4j 不可达")
    return {"status": "ok"}
