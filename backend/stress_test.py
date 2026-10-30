"""Head-to-head stress-test comparing Direct Raw SLM vs. 5-Stage Production Pipeline across 20 queries."""

from typing import Any

from backend.database.query_executor import get_table_row_counts, run_query
from backend.services.schema_linker import schema_linker
from backend.services.sql_generator import MODEL_NAME, generate_sql, repair_sql
from backend.services.sql_validator import sql_validator

BENCHMARK_SUITE: list[dict[str, str]] = [
    {
        "tier": "Tier 1: Filtering & Aggregation",
        "question": "What is the average salary of employees in the Europe region?",
        "ground_truth_sql": "SELECT AVG(salary) FROM Employees WHERE region = 'Europe';",
    },
    {
        "tier": "Tier 1: Filtering & Aggregation",
        "question": "How many products have a price greater than 200?",
        "ground_truth_sql": "SELECT COUNT(*) FROM Products WHERE price > 200;",
    },
    {
        "tier": "Tier 2: Grouping & Ordering",
        "question": "Show the number of users in each region",
        "ground_truth_sql": "SELECT region, COUNT(*) FROM Users GROUP BY region;",
    },
    {
        "tier": "Tier 2: Grouping & Ordering",
        "question": "What is the average product price for each category?",
        "ground_truth_sql": "SELECT category, AVG(price) FROM Products GROUP BY category;",
    },
    {
        "tier": "Tier 2: Grouping & Having",
        "question": "Which countries have more than 8 suppliers?",
        "ground_truth_sql": "SELECT country FROM Suppliers GROUP BY country HAVING COUNT(*) > 8;",
    },
    {
        "tier": "Tier 3: Multi-Table Join (50K Orders + 5K Users)",
        "question": "What is the total quantity of orders placed by users in Europe?",
        "ground_truth_sql": (
            "SELECT SUM(T1.quantity) FROM Orders AS T1 "
            "JOIN Users AS T2 ON T1.user_id = T2.id WHERE T2.region = 'Europe';"
        ),
    },
    {
        "tier": "Tier 3: Multi-Table Join (Employees + Departments)",
        "question": "Find the total salary of employees in each department name",
        "ground_truth_sql": (
            "SELECT T2.name, SUM(T1.salary) FROM Employees AS T1 "
            "JOIN Departments AS T2 ON T1.department_id = T2.id GROUP BY T2.name;"
        ),
    },
    {
        "tier": "Tier 3: Multi-Table Join (Products + Suppliers)",
        "question": "How many products are supplied by suppliers from Germany?",
        "ground_truth_sql": (
            "SELECT COUNT(*) FROM Products AS T1 "
            "JOIN Suppliers AS T2 ON T1.supplier_id = T2.id WHERE T2.country = 'Germany';"
        ),
    },
    {
        "tier": "Tier 4: Large Join Aggregation (20K Reviews + 500 Products)",
        "question": "What is the average review rating for each product category?",
        "ground_truth_sql": (
            "SELECT T2.category, AVG(T1.rating) FROM Reviews AS T1 "
            "JOIN Products AS T2 ON T1.product_id = T2.id GROUP BY T2.category;"
        ),
    },
    {
        "tier": "Tier 4: High-Cardinality Join (50K Orders + 500 Products)",
        "question": "What is the total quantity ordered for each product category?",
        "ground_truth_sql": (
            "SELECT T2.category, SUM(T1.quantity) FROM Orders AS T1 "
            "JOIN Products AS T2 ON T1.product_id = T2.id GROUP BY T2.category;"
        ),
    },
    {
        "tier": "Tier 4: Multi-Condition Aggregation",
        "question": "What is the maximum salary of employees with the Sales Manager role?",
        "ground_truth_sql": "SELECT MAX(salary) FROM Employees WHERE role = 'Sales Manager';",
    },
    {
        "tier": "Tier 4: High-Volume Filtered Aggregation (50K Orders)",
        "question": "What is the total quantity of orders with status Completed?",
        "ground_truth_sql": "SELECT SUM(quantity) FROM Orders WHERE status = 'Completed';",
    },
    {
        "tier": "Tier 4: Grouping & Aggregate Having",
        "question": "Which categories have an average price greater than 250 in Products?",
        "ground_truth_sql": "SELECT category FROM Products GROUP BY category HAVING AVG(price) > 250;",
    },
    {
        "tier": "Tier 4: Minimum Aggregation by Group",
        "question": "What is the minimum lead_time_days of suppliers in each country?",
        "ground_truth_sql": "SELECT country, MIN(lead_time_days) FROM Suppliers GROUP BY country;",
    },
    {
        "tier": "Tier 5: Join + Categorical Filter (20K Reviews + 5K Users)",
        "question": "How many reviews were submitted by users in the Enterprise tier?",
        "ground_truth_sql": (
            "SELECT COUNT(*) FROM Reviews AS T1 "
            "JOIN Users AS T2 ON T1.user_id = T2.id WHERE T2.tier = 'Enterprise';"
        ),
    },
    {
        "tier": "Tier 5: Join + Grouped Summation (50K Orders + 5K Users)",
        "question": "What is the total quantity of orders for each user tier?",
        "ground_truth_sql": (
            "SELECT T2.tier, SUM(T1.quantity) FROM Orders AS T1 "
            "JOIN Users AS T2 ON T1.user_id = T2.id GROUP BY T2.tier;"
        ),
    },
    {
        "tier": "Tier 5: Join + Grouped Count (50K Orders + 250 Employees)",
        "question": "Show the number of orders handled by each employee role",
        "ground_truth_sql": (
            "SELECT T2.role, COUNT(*) FROM Orders AS T1 "
            "JOIN Employees AS T2 ON T1.employee_id = T2.id GROUP BY T2.role;"
        ),
    },
    {
        "tier": "Tier 5: Join + Filtered Average (Products + Suppliers)",
        "question": "What is the average price of products from suppliers in Japan?",
        "ground_truth_sql": (
            "SELECT AVG(T1.price) FROM Products AS T1 "
            "JOIN Suppliers AS T2 ON T1.supplier_id = T2.id WHERE T2.country = 'Japan';"
        ),
    },
    {
        "tier": "Tier 5: Join + Office Location Filter (Employees + Departments)",
        "question": "How many employees work in departments with head_office in New York?",
        "ground_truth_sql": (
            "SELECT COUNT(*) FROM Employees AS T1 "
            "JOIN Departments AS T2 ON T1.department_id = T2.id WHERE T2.head_office = 'New York';"
        ),
    },
    {
        "tier": "Tier 5: 3-Table Join (50K Orders + 500 Products + 100 Suppliers)",
        "question": "What is the total quantity of orders for products from suppliers in USA?",
        "ground_truth_sql": (
            "SELECT SUM(T1.quantity) FROM Orders AS T1 "
            "JOIN Products AS T2 ON T1.product_id = T2.id "
            "JOIN Suppliers AS T3 ON T2.supplier_id = T3.id WHERE T3.country = 'USA';"
        ),
    },
]


def normalize_rows(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Convert result dictionaries into canonical order-independent tuples for comparison."""
    normalized = []
    for row in rows:
        vals = sorted(
            (str(round(v, 2) if isinstance(v, float) else v) for v in row.values())
        )
        normalized.append(tuple(vals))
    return sorted(normalized)


def run_stress_test() -> None:
    """Compare Direct Raw SLM vs. 5-Stage Pipeline across all 20 benchmark queries."""
    counts = get_table_row_counts()

    print("=" * 96)
    print(f"HEAD-TO-HEAD BENCHMARK (20 QUERIES) | Engine: {MODEL_NAME}")
    print(f"Database Volume                     | {sum(counts.values()):,} rows across {len(counts)} tables")
    print("=" * 96)

    # Metrics for Direct Raw Model
    direct_exec_ok = 0
    direct_exact_ok = 0
    direct_latency_sum = 0.0

    # Metrics for 5-Stage Pipeline
    pipe_exec_ok = 0
    pipe_exact_ok = 0
    pipe_latency_sum = 0.0
    pipe_db_ms_sum = 0.0

    for idx, case in enumerate(BENCHMARK_SUITE, start=1):
        question = case["question"]
        gt_data = run_query(case["ground_truth_sql"])
        gt_norm = normalize_rows(gt_data["results"])

        print(f"\n[{idx:02d}/20] {case['tier']}")
        print(f"  Question         : {question}")

        # --- A. Direct Model (Full 7-Table Schema, No Linker, No Validator) ---
        direct_status = "FAILED"
        try:
            direct_sql, d_ms = generate_sql(question, schema_linker.full_schema)
            direct_latency_sum += d_ms
            d_pred = run_query(direct_sql)
            direct_exec_ok += 1
            if normalize_rows(d_pred["results"]) == gt_norm:
                direct_exact_ok += 1
                direct_status = f"PASS ({d_ms:.0f}ms)"
            else:
                direct_status = f"WRONG RESULT ({d_ms:.0f}ms)"
        except Exception as exc:
            direct_status = f"CRASH: {exc}"

        # --- B. 5-Stage Production Pipeline ---
        pipe_status = "FAILED"
        try:
            linked_schema, linked_tables = schema_linker.link_schema(question)
            raw_sql, p_ms = generate_sql(question, linked_schema)
            pipe_latency_sum += p_ms

            final_sql, repairs = sql_validator.validate(
                question,
                raw_sql,
                llm_repair=lambda failed, err: repair_sql(question, linked_schema, failed, err),
            )
            p_pred = run_query(final_sql)
            pipe_exec_ok += 1
            pipe_db_ms_sum += p_pred["execution_ms"]

            if normalize_rows(p_pred["results"]) == gt_norm:
                pipe_exact_ok += 1
                pipe_status = f"PASS ({p_ms:.0f}ms)"
            else:
                pipe_status = f"WRONG RESULT ({p_ms:.0f}ms)"

            print(f"  [Direct Raw 1B]  : {direct_status} | SQL: {direct_sql}")
            print(f"  [5-Stage Pipe]   : {pipe_status} | Tables: {linked_tables} | Repairs: {repairs}")
            print(f"                     Final SQL: {final_sql}")
        except Exception as exc:
            print(f"  [Direct Raw 1B]  : {direct_status}")
            print(f"  [5-Stage Pipe]   : CRASH ({exc})")

    total = len(BENCHMARK_SUITE)
    d_exec_pct = (direct_exec_ok / total) * 100
    d_ex_pct = (direct_exact_ok / total) * 100
    d_avg_ms = direct_latency_sum / total

    p_exec_pct = (pipe_exec_ok / total) * 100
    p_ex_pct = (pipe_exact_ok / total) * 100
    p_avg_ms = pipe_latency_sum / total

    print("\n" + "=" * 96)
    print("FINAL HEAD-TO-HEAD COMPARISON (20 QUERIES ON 75,858 ROWS)")
    print("-" * 96)
    print(f"{'Metric':<34} | {'Direct Raw 1B Model':<22} | {'5-Stage Pipeline (1B)':<22} | {'Improvement'}")
    print("-" * 96)
    print(
        f"{'Valid SQL Execution Rate':<34} | "
        f"{f'{direct_exec_ok}/{total} ({d_exec_pct:.1f}%)':<22} | "
        f"{f'{pipe_exec_ok}/{total} ({p_exec_pct:.1f}%)':<22} | "
        f"+{p_exec_pct - d_exec_pct:.1f}%"
    )
    print(
        f"{'Exact Result Match Accuracy (EX)':<34} | "
        f"{f'{direct_exact_ok}/{total} ({d_ex_pct:.1f}%)':<22} | "
        f"{f'{pipe_exact_ok}/{total} ({p_ex_pct:.1f}%)':<22} | "
        f"+{p_ex_pct - d_ex_pct:.1f}% ({pipe_exact_ok / max(direct_exact_ok, 1):.1f}x)"
    )
    print(
        f"{'Avg SLM Inference Latency':<34} | "
        f"{f'{d_avg_ms:.1f} ms':<22} | "
        f"{f'{p_avg_ms:.1f} ms':<22} | "
        f"{d_avg_ms / max(p_avg_ms, 1):.2f}x Faster"
    )
    print(
        f"{'Avg 75K-Row SQLite Execution':<34} | "
        f"{'N/A':<22} | "
        f"{f'{pipe_db_ms_sum / max(pipe_exec_ok, 1):.2f} ms':<22} | "
        f"Indexed B-Tree"
    )
    print("=" * 96)


if __name__ == "__main__":
    run_stress_test()
