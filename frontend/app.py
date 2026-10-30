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
        st.plotly_chart(fig, use_container_width=True)


def render_response_block(item: dict[str, Any]) -> None:
    """Render question answers cleanly without exposing technical internals."""
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

    df = pd.DataFrame(results)
    st.dataframe(df, use_container_width=True, hide_index=True)
    render_dynamic_chart(df)


def main() -> None:
    """Main Streamlit application entrypoint."""
    st.set_page_config(
        page_title="Enterprise Database Analytics",
        page_icon="💬",
        layout="wide",
    )

    st.title("Enterprise Database Analytics Assistant")
    st.caption("Ask natural language questions about your business database.")

    with st.sidebar:
        st.subheader("Sample Questions")
        selected_sample = None
        for sample in SAMPLE_QUESTIONS:
            if st.button(sample, use_container_width=True):
                selected_sample = sample

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


if __name__ == "__main__":
    main()
