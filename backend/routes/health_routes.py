"""Health and schema inspection endpoints."""

from fastapi import APIRouter

from backend.controllers.health_controller import get_health, get_schema
from backend.schemas.health import HealthResponse, SchemaResponse

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return get_health()


@router.get("/schema", response_model=SchemaResponse)
def schema() -> SchemaResponse:
    return get_schema()

