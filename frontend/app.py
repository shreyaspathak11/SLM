"""Streamlit frontend for the SLM Text-to-SQL Enterprise Analytics Assistant."""

import os
from typing import Any

from dotenv import load_dotenv
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")

SAMPLE_QUESTIONS = [
    "What is the total quantity ordered for each product category?",
    "Find the total salary of employees in each department name",
    "What is the average review rating for each product category?",
    "Show the number of users in each region",
    "Which countries have more than 8 suppliers?",
    "What is the total quantity of orders placed by users in Europe?",
]


@st.cache_data(ttl=300)
def fetch_schema_metadata() -> dict[str, Any] | None:
    """Fetch database schema, tables, and foreign keys from the backend or local schema fallback."""
    for base_url in (BACKEND_URL, "http://127.0.0.1:8000", "http://localhost:8000"):
        try:
            response = requests.get(f"{base_url}/schema", timeout=5)
            if response.ok:
                return response.json()
        except requests.RequestException:
            continue

    # Fallback: introspect local database directly if backend HTTP connection fails
    try:
        from backend.services.schema_linker import schema_linker
        fks = [
            {
                "from_table": fk[0],
                "from_column": fk[1],
                "to_table": fk[2],
                "to_column": fk[3],
            }
            for fk in schema_linker.fk_relations
        ]
        return {
            "schema_ddl": schema_linker.full_schema,
            "tables": schema_linker.table_columns,
            "foreign_keys": fks,
        }
    except Exception:
        return None


@st.cache_data(ttl=60)
def fetch_health_metadata() -> dict[str, Any] | None:
    """Fetch database health, engine name, and table row counts."""
    for base_url in (BACKEND_URL, "http://127.0.0.1:8000", "http://localhost:8000"):
        try:
            response = requests.get(f"{base_url}/health", timeout=5)
            if response.ok:
                return response.json()
        except requests.RequestException:
            continue

    # Fallback: introspect local database row counts directly
    try:
        from backend.database.query_executor import get_table_row_counts
        from backend.services.sql_generator import MODEL_NAME
        counts = get_table_row_counts()
        return {
            "status": "ok",
            "model_path": "local",
            "engine": MODEL_NAME,
            "total_rows": sum(counts.values()),
            "tables": counts,
        }
    except Exception:
        return None


def generate_er_diagram(schema_data: dict[str, Any]) -> str:
    """Generate Mermaid erDiagram syntax showing tables, columns, and foreign-key links."""
    tables = schema_data.get("tables", {})
    foreign_keys = schema_data.get("foreign_keys", [])

    lines = ["erDiagram"]
    for fk in foreign_keys:
        to_tbl = fk.get("to_table", "")
        from_tbl = fk.get("from_table", "")
        from_col = fk.get("from_column", "")
        if to_tbl and from_tbl:
            lines.append(f'    {to_tbl} ||--o{{ {from_tbl} : "{from_col}"')

    for t_name, cols in sorted(tables.items()):
        lines.append(f"    {t_name} {{")
        for col_name, col_type in cols.items():
            key_tag = "PK" if col_name == "id" else ("FK" if col_name.endswith("_id") else "")
            lines.append(f"        {col_type} {col_name} {key_tag}".rstrip())
        lines.append("    }")

    return "\n".join(lines)


def render_dynamic_chart(df: pd.DataFrame) -> None:
    """Auto-generate a clean Plotly bar chart when results have 1 categorical and 1 numeric column."""
    if len(df) <= 1 or len(df.columns) != 2:
        return

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
    categorical_cols = [col for col in df.columns if col not in numeric_cols]

    if len(categorical_cols) == 1 and len(numeric_cols) == 1:
        cat_col = categorical_cols[0]
        num_col = numeric_cols[0]
        fig = px.bar(
            df,
            x=cat_col,
            y=num_col,
            color=cat_col,
            text_auto=True,
            title=f"{num_col.replace('_', ' ').title()} by {cat_col.replace('_', ' ').title()}",
        )
        fig.update_layout(showlegend=False, margin=dict(l=20, r=20, t=45, b=20))
        st.plotly_chart(fig, width="stretch")


def render_response_block(item: dict[str, Any]) -> None:
    """Render question answers with optional pipeline inspector and dynamic charts."""
    if "error" in item:
        st.warning(item["error"])
        return

    if item.get("message") and not item.get("results"):
        st.write(item["message"])
        return

    results = item.get("results", [])
    if not results:
        st.info("The query completed successfully, but no matching records were found.")
        return

    # Pipeline Inspector (SQL query, linked tables, repairs applied, execution latency)
    if "sql" in item:
        with st.expander(":material/code: Inspect Generated SQL & 5-Stage Pipeline", expanded=False):
            st.code(item["sql"], language="sql")
            meta_cols = st.columns(4)
            meta_cols[0].metric(label="Inference Latency", value=f"{item.get('inference_ms', 0):.0f} ms")
            meta_cols[1].metric(label="DB Execution", value=f"{item.get('execution_ms', 0):.2f} ms")
            meta_cols[2].metric(label="Rows Returned", value=item.get("row_count", len(results)))
            meta_cols[3].metric(label="Linked Tables", value=", ".join(item.get("linked_tables", [])) or "None")

            repairs = item.get("repairs_applied", [])
            if repairs:
                st.caption(f":material/build: **Repairs applied:** `{'`, `'.join(repairs)}`")
            else:
                st.caption(":material/check_circle: **Clean SLM generation** (zero heuristic repairs needed)")

    df = pd.DataFrame(results)
    st.dataframe(df, width="stretch", hide_index=True)
    render_dynamic_chart(df)


def render_schema_viewer(schema_data: dict[str, Any], health_data: dict[str, Any] | None) -> None:
    """Render the interactive Entity-Relationship diagram, FK connections, and table structures."""
    st.subheader(":material/hub: Database Schema & Entity Relationships")
    st.caption("Visual representation of the 7 relational tables, primary keys, and foreign-key links.")

    tables = schema_data.get("tables", {})
    foreign_keys = schema_data.get("foreign_keys", [])
    row_counts = health_data.get("tables", {}) if health_data else {}
    total_rows = health_data.get("total_rows", 0) if health_data else sum(row_counts.values())

    # Top-level summary metrics
    col1, col2, col3 = st.columns(3)
    col1.metric(label="Total Database Records", value=f"{total_rows:,}" if total_rows else "75,858")
    col2.metric(label="Relational Tables", value=f"{len(tables)} tables")
    col3.metric(label="Foreign-Key Links", value=f"{len(foreign_keys)} relationships")

    # Visual Entity-Relationship Diagram
    with st.container(border=True):
        st.markdown("##### :material/schema: Entity-Relationship (ER) Diagram")
        er_code = generate_er_diagram(schema_data)
        st.mermaid_chart(er_code, width="stretch", alt="Database Entity Relationship Diagram")

    # Foreign Key Connections Table
    with st.container(border=True):
        st.markdown("##### :material/link: Foreign-Key Relationship Directory")
        st.caption("How tables join together across the relational schema.")
        if foreign_keys:
            fk_display_rows = [
                {
                    "Source Table": fk.get("from_table", ""),
                    "Foreign Key Column": f"`{fk.get('from_column', '')}`",
                    "Relationship": "→ references →",
                    "Target Table": fk.get("to_table", ""),
                    "Primary Key Column": f"`{fk.get('to_column', '')}`",
                }
                for fk in foreign_keys
            ]
            st.dataframe(pd.DataFrame(fk_display_rows), width="stretch", hide_index=True)

    # Detailed Table-by-Table Column Inspector
    with st.expander(":material/table_rows: Inspect Table Columns & Row Counts", expanded=False):
        t_names = sorted(tables.keys())
        selected_table = st.segmented_control(
            "Select table to inspect:",
            options=t_names,
            default=t_names[0] if t_names else None,
            label_visibility="visible",
        )
        if selected_table and selected_table in tables:
            rows_for_table = row_counts.get(selected_table)
            count_badge = f" ({rows_for_table:,} rows)" if rows_for_table is not None else ""
            st.markdown(f"**Table:** `{selected_table}`{count_badge}")

            col_records = [
                {
                    "Column Name": col,
                    "Data Type": dtype,
                    "Key Constraint": "Primary Key (PK)" if col == "id" else ("Foreign Key (FK)" if col.endswith("_id") else "Attribute"),
                }
                for col, dtype in tables[selected_table].items()
            ]
            st.dataframe(pd.DataFrame(col_records), width="stretch", hide_index=True)


def main() -> None:
    """Main Streamlit application entrypoint."""
    st.set_page_config(
        page_title="Enterprise Database Analytics",
        page_icon="💬",
        layout="wide",
    )

    st.title("Enterprise Database Analytics Assistant")
    st.caption("Ask natural language questions about your business database or explore relational connections.")

    schema_data = fetch_schema_metadata()
    health_data = fetch_health_metadata()

    with st.sidebar:
        st.subheader("Sample Questions")
        selected_sample = None
        for sample in SAMPLE_QUESTIONS:
            if st.button(sample, width="stretch"):
                selected_sample = sample

        st.divider()
        st.subheader(":material/database: System Telemetry")
        if health_data:
            st.caption(f"**Engine:** `{health_data.get('engine', 'llama.cpp')}`")
            st.caption(f"**Status:** `:green-badge[{health_data.get('status', 'ok')}]`")
            st.caption(f"**Indexed Records:** `{health_data.get('total_rows', 0):,}`")
        else:
            st.caption(":gray-badge[Backend offline or unreachable]")

    tab_chat, tab_schema = st.tabs([":material/chat: Analytics Assistant", ":material/schema: Database Schema & ER Graph"])

    with tab_chat:
        if "messages" not in st.session_state:
            st.session_state.messages = []

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                if message["role"] == "user":
                    st.markdown(message["content"])
                else:
                    render_response_block(message["data"])

        user_question = st.chat_input("Ask a question about the database...")
        active_question = selected_sample or user_question

        if active_question:
            st.session_state.messages.append({"role": "user", "content": active_question})
            with st.chat_message("user"):
                st.markdown(active_question)

            with st.chat_message("assistant"):
                with st.spinner("Analyzing data..."):
                    try:
                        response = requests.post(
                            f"{BACKEND_URL}/chat",
                            json={"question": active_question},
                            timeout=60,
                        )
                        if response.ok:
                            payload = response.json()
                        else:
                            payload = {"error": "Sorry, I faced an issue. Please fix the query and retry."}
                    except requests.RequestException:
                        payload = {"error": "Sorry, I faced an issue. Please fix the query and retry."}

                    render_response_block(payload)
                    st.session_state.messages.append({"role": "assistant", "data": payload})

    with tab_schema:
        if schema_data:
            render_schema_viewer(schema_data, health_data)
        else:
            st.warning("Could not connect to the backend schema endpoint. Please ensure the FastAPI backend is running.")


if __name__ == "__main__":
    main()
