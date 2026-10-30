"""Health controller: service status, table sizes, and database DDL."""

from backend.database.query_executor import get_table_row_counts
from backend.schemas.health import HealthResponse, SchemaResponse
from backend.services.schema_linker import schema_linker
from backend.services.sql_generator import MODEL_NAME, model


def get_health() -> HealthResponse:
    table_counts = get_table_row_counts()
    return HealthResponse(
        status="ok",
        model_path=model.model_path,
        engine=MODEL_NAME,
        total_rows=sum(table_counts.values()),
        tables=table_counts,
    )


def get_schema() -> SchemaResponse:
    return SchemaResponse(schema_ddl=schema_linker.full_schema)

