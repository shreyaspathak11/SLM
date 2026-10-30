"""FastAPI service implementing the 5-stage Text-to-SQL production pipeline:
1. Schema Linking -> 2. FK Relationship Expansion -> 3. SLM SQL Generation -> 4. SQL Validation -> 5. Safe Execution.
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.database import (
    DATABASE_PATH,
    execute_readonly_query,
    get_database_schema,
    get_table_row_counts,
)
from backend.database_setup import create_database
from backend.llm_inference import SQLGenerator
from backend.schema_linker import SchemaLinker
from backend.sql_validator import SQLValidator


def ensure_enterprise_database() -> None:
    """Create or upgrade analytics.db if the 7-table enterprise schema is not present."""
    if not DATABASE_PATH.exists():
        create_database(DATABASE_PATH)
        return

    counts = get_table_row_counts(DATABASE_PATH)
    if len(counts) < 7 or sum(counts.values()) < 70000:
        create_database(DATABASE_PATH)


ensure_enterprise_database()

app = FastAPI(
    title="SLM Text-to-SQL Analytics API",
    description="5-Stage Schema-Conditioned Text-to-SQL service powered by a QLoRA fine-tuned GGUF model.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

schema_linker = SchemaLinker(DATABASE_PATH)
sql_validator = SQLValidator(schema_linker.table_columns, DATABASE_PATH)
sql_generator = SQLGenerator()


class QueryRequest(BaseModel):
    """Incoming natural language analytics request."""

    question: str = Field(..., min_length=3, description="Natural language question about the database.")


class QueryResponse(BaseModel):
    """Structured response containing generated SQL, results, linked tables, and latency telemetry."""

    question: str
    sql: str
    linked_tables: list[str]
    repairs_applied: list[str]
    columns: list[str]
    results: list[dict[str, Any]]
    row_count: int
    inference_ms: float
    execution_ms: float
    engine: str


@app.get("/health")
def health_check() -> dict[str, Any]:
    """Return service health, table row counts, and active GGUF model metadata."""
    table_counts = get_table_row_counts()
    return {
        "status": "ok",
        "model_path": str(sql_generator.model_path),
        "engine": sql_generator.engine_name,
        "total_rows": sum(table_counts.values()),
        "tables": table_counts,
    }


@app.get("/schema")
def read_schema() -> dict[str, str]:
    """Return the full CREATE TABLE DDL schema extracted from SQLite."""
    try:
        return {"schema": get_database_schema()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/query", response_model=QueryResponse)
def run_natural_language_query(request: QueryRequest) -> QueryResponse:
    """Execute the 5-stage Text-to-SQL pipeline on a natural language question."""
    try:
        # Stage 1 & 2: Schema Linking & Foreign-Key Relationship Expansion
        linked_schema, linked_tables = schema_linker.link_schema(request.question)

        # Stage 3: Constrained SLM SQL Generation
        raw_sql, inference_ms = sql_generator.generate_sql(request.question, linked_schema)

        # Stage 4: Pre-Execution SQL Validation & Bounded Self-Correction
        validated_sql, repairs = sql_validator.validate_and_repair(
            question=request.question,
            sql_query=raw_sql,
            schema=linked_schema,
            llm_repair_fn=sql_generator.repair_sql,
        )

        # Stage 5: Safe Read-Only Execution & Result Validation
        execution_data = execute_readonly_query(validated_sql)

        return QueryResponse(
            question=request.question,
            sql=validated_sql,
            linked_tables=linked_tables,
            repairs_applied=repairs,
            columns=execution_data["columns"],
            results=execution_data["results"],
            row_count=execution_data["row_count"],
            inference_ms=inference_ms,
            execution_ms=execution_data["execution_ms"],
            engine=sql_generator.engine_name,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Query execution failed: {exc}") from exc
