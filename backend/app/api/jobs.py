from fastapi import APIRouter, HTTPException, Request

from app.schemas.api import JobResponse

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request) -> JobResponse:
    state = request.app.state.job_store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="job 不存在")
    return JobResponse.from_state(state)
