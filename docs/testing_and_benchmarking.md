# Testing & Head-to-Head Benchmarking Guide

This document explains the testing standards, metric definitions, and verification protocol for the Text-to-SQL system.

---

## 1. Benchmark Suite Design (`backend/stress_test.py`)

The benchmark evaluates 20 queries spanning 5 complexity tiers across **75,858 rows**:

| Tier | Complexity Description | Example Question |
| :--- | :--- | :--- |
| **Tier 1** | Filtering & Single-Table Aggregations | *"How many products have a price greater than 200?"* |
| **Tier 2** | Grouping, Ordering & `HAVING` | *"Which countries have more than 8 suppliers?"* |
| **Tier 3** | 2-Table Relational Joins | *"What is the total quantity of orders placed by users in Europe?"* |
| **Tier 4** | High-Cardinality Joins & Multi-Condition Grouping | *"What is the average review rating for each product category?"* |
| **Tier 5** | Multi-Table Joins (3+ tables) & Grouped Sums | *"What is the total quantity of orders for products from suppliers in USA?"* |

---

## 2. Evaluation Metrics

1. **Valid SQL Execution Rate (%):**
   - Percentage of generated SQL queries that compile and execute cleanly in SQLite without a syntax, column-not-found, or table-not-found error.
2. **Exact Result Match Accuracy (EX %):**
   - Output rows from the generated query are converted into canonical, order-independent tuples and compared directly against the ground-truth SQL result.
   - Requires identical row contents, counts, and aggregate calculations.
3. **SLM Inference Latency (ms):**
   - Time taken by the GGUF model (`llama.cpp`) to generate the full SQL token stream.
4. **Database Execution Time (ms):**
   - Time taken by SQLite to execute the query plan over indexed B-trees on 75,858 rows.

---

## 3. Running the Head-to-Head Stress Test

To run the full 20-query evaluation comparing **Direct Raw 1B** against the **5-Stage Pipeline**:

```powershell
# Ensure virtual environment is active
.\.venv\Scripts\Activate.ps1

# Run the benchmark module
python -m backend.stress_test
```

### Production Acceptance Thresholds

For any code or model update to be accepted:
- **Pipeline Execution Rate:** Must achieve **`20/20 (100.0%)`**.
- **Pipeline Exact Match (EX):** Must achieve **`20/20 (100.0%)`**.
- **Average Database Execution:** Must remain **`< 25.0 ms`**.

