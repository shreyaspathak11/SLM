"""Chat controller: turns a user question into SQL, runs it, and returns the answer."""

import re

import weave

from backend.database.query_executor import run_query
from backend.schemas.chat import ChatResponse
from backend.services.schema_linker import schema_linker
from backend.services.sql_generator import MODEL_NAME, generate_sql, repair_sql
from backend.services.sql_validator import sql_validator

CONVERSATIONAL_WORDS = {
    "hi",
    "hello",
    "hey",
    "hola",
    "howdy",
    "greetings",
    "good morning",
    "good evening",
    "good afternoon",
    "help",
    "who are you",
    "what can you do",
    "thanks",
    "thank you",
}


def is_conversational_query(text: str) -> bool:
    """Check if the text is a greeting, conversational, or non-analytical question."""
    cleaned = re.sub(r"[^\w\s]", "", text.strip().lower())
    if len(cleaned) < 3 or cleaned in CONVERSATIONAL_WORDS:
        return True
    if re.match(r"^(hi|hello|hey|help)\b", cleaned) and len(cleaned.split()) <= 2:
        return True
    return False


@weave.op
def answer_question(question: str) -> ChatResponse:
    """Link schema -> generate SQL -> validate/repair -> execute, instrumented for Weave Agents."""
    q_stripped = question.strip()

    with weave.start_conversation(agent_name="Text2SQL-Agent", model=MODEL_NAME):
        with weave.start_turn(user_message=q_stripped):
            if is_conversational_query(q_stripped):
                return ChatResponse(
                    question=question,
                    message=(
                        "Hello! I am your database analytics assistant. Please let me know what you are looking for "
                        "in the database across our tables: Departments, Employees, Suppliers, Users, Products, Orders, "
                        "or Reviews (e.g., 'What is the total quantity of orders by product category?' or 'Show average salary of employees in Europe')."
                    ),
                    engine=MODEL_NAME,
                )

            with weave.start_tool(name="schema_linker"):
                linked_schema, linked_tables = schema_linker.link_schema(question)

            raw_sql, inference_ms = generate_sql(question, linked_schema)

            with weave.start_tool(name="sql_validator"):
                sql, repairs = sql_validator.validate(
                    question,
                    raw_sql,
                    llm_repair=lambda failed_sql, error: repair_sql(question, linked_schema, failed_sql, error),
                )

            with weave.start_tool(name="sqlite_executor"):
                result = run_query(sql)

            return ChatResponse(
                question=question,
                sql=sql,
                linked_tables=linked_tables,
                repairs_applied=repairs,
                inference_ms=inference_ms,
                engine=MODEL_NAME,
                **result,
            )
