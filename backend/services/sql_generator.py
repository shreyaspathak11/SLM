"""Text-to-SQL generation with the fine-tuned GGUF model served through llama.cpp."""

import os
from pathlib import Path
import re
import threading
import time

from llama_cpp import Llama
import weave

from backend.config import MODEL_DIR

PROMPT_TEMPLATE = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Write a SQL query to answer this question: {question}

### Input:
{context}

### Response:
"""

EOS_TOKENS = ["<|end_of_text|>", "<|eot_id|>", "</s>"]


def connect_model(model_dir: Path = MODEL_DIR) -> Llama:
    """Load the GGUF model from model_dir, preferring the q4_k_m quantization."""
    gguf_files = sorted(model_dir.glob("*.gguf"))
    if not gguf_files:
        raise FileNotFoundError(f"No .gguf model found in {model_dir}.")

    model_path = next((f for f in gguf_files if "q4_k_m" in f.name.lower()), gguf_files[0])
    return Llama(
        model_path=str(model_path),
        n_ctx=2048,
        n_threads=max(1, (os.cpu_count() or 4) // 2),
        verbose=False,
    )


model = connect_model()
MODEL_NAME = f"llama.cpp ({Path(model.model_path).name})"

# llama.cpp models are not thread-safe, so generations are serialized.
_model_lock = threading.Lock()


def clean_sql(raw_output: str) -> str:
    """Strip EOS tokens, code fences, and trailing text from the model output."""
    text = raw_output.strip()
    for token in EOS_TOKENS:
        text = text.replace(token, "")

    fenced_match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    if fenced_match:
        text = fenced_match.group(1)

    text = text.split("###")[0].strip()
    if ";" in text:
        text = text.split(";")[0].strip() + ";"
    return " ".join(text.split())


@weave.op
def generate_sql(question: str, schema: str) -> tuple[str, float]:
    """Generate a SQLite query for the question and record token usage to Weave."""
    prompt = PROMPT_TEMPLATE.format(question=question.strip(), context=schema.strip())

    start_time = time.perf_counter()
    with _model_lock:
        response = model(prompt, max_tokens=150, temperature=0.0, stop=[*EOS_TOKENS[:2], "###", "\n\n"])
    inference_ms = round((time.perf_counter() - start_time) * 1000, 2)

    raw_text = response["choices"][0]["text"]
    sql = clean_sql(raw_text)
    if not sql:
        raise RuntimeError("Model returned an empty SQL response.")

    # Record LLM call metrics (tokens, model name, output) for Weave Agents dashboard
    try:
        usage_data = response.get("usage", {})
        with weave.start_llm(model=MODEL_NAME, provider_name="llama.cpp") as llm:
            if usage_data:
                llm.usage = weave.Usage(
                    input_tokens=usage_data.get("prompt_tokens", 0),
                    output_tokens=usage_data.get("completion_tokens", 0),
                    total_tokens=usage_data.get("total_tokens", 0),
                )
            llm.output(sql)
    except Exception:
        pass

    return sql, inference_ms


def repair_sql(question: str, schema: str, failed_sql: str, error_msg: str) -> str:
    """Ask the model once more, telling it which query failed and why."""
    repair_question = (
        f"{question} (Note: Previous query '{failed_sql}' failed with SQLite error: {error_msg}. "
        "Use only the exact table and column names provided in Input.)"
    )
    return generate_sql(repair_question, schema)[0]
