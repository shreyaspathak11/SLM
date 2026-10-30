"""Pydantic schemas for health and database schema endpoints."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    model_path: str
    engine: str
    total_rows: int
    tables: dict[str, int]


class SchemaResponse(BaseModel):
    schema_ddl: str

