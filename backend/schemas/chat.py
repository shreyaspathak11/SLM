"""Pydantic schemas for the chat endpoint request and response."""

from typing import Any, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, examples=["Show the number of users in each region"])


class ChatResponse(BaseModel):
    question: str
    message: Optional[str] = None
    sql: str = ""
    linked_tables: list[str] = []
    repairs_applied: list[str] = []
    columns: list[str] = []
    results: list[dict[str, Any]] = []
    row_count: int = 0
    inference_ms: float = 0.0
    execution_ms: float = 0.0
    engine: str = ""
