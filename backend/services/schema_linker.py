"""Schema linking: picks the tables a question needs and connects them through foreign keys.

Introspects the SQLite catalog (tables, columns, foreign keys, low-cardinality text values)
once at startup, then matches question tokens against it and expands the match with the
shortest foreign-key paths between the selected tables.
"""

from collections import deque
import re

from backend.database.connection import connection


class SchemaLinker:
    """Links natural language questions to the relevant tables and their FK paths."""

    def __init__(self) -> None:
        self.table_ddls: dict[str, str] = {}
        self.table_columns: dict[str, dict[str, str]] = {}
        self.fk_graph: dict[str, set[str]] = {}
        self.fk_relations: list[tuple[str, str, str, str]] = []
        self.value_to_table_col: dict[str, list[tuple[str, str]]] = {}
        self._introspect_catalog()
        self.full_schema = "\n".join(self.table_ddls.values())

    def _introspect_catalog(self) -> None:
        """Load table DDLs, column types, foreign keys, and distinct categorical values."""
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND sql IS NOT NULL
            ORDER BY name;
            """
        )
        for row in cursor.fetchall():
            self.table_ddls[row["name"]] = " ".join(row["sql"].split()).rstrip(";") + ";"
            self.fk_graph.setdefault(row["name"], set())

        for table in self.table_ddls:
            cursor.execute(f"PRAGMA table_info({table});")
            cols = {r["name"]: r["type"].upper() for r in cursor.fetchall()}
            self.table_columns[table] = cols

            cursor.execute(f"PRAGMA foreign_key_list({table});")
            for fk in cursor.fetchall():
                self.fk_relations.append((table, fk["from"], fk["table"], fk["to"]))
                if fk["table"] in self.table_ddls:
                    self.fk_graph[table].add(fk["table"])
                    self.fk_graph.setdefault(fk["table"], set()).add(table)

            for col_name, col_type in cols.items():
                if "TEXT" in col_type and col_name != "name" and not col_name.endswith("_date"):
                    cursor.execute(f"SELECT DISTINCT {col_name} FROM {table} LIMIT 25;")
                    distinct_vals = [str(r[0]).lower() for r in cursor.fetchall() if r[0] is not None]
                    if 1 <= len(distinct_vals) <= 20:
                        for val in distinct_vals:
                            self.value_to_table_col.setdefault(val, []).append((table, col_name))

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        """Extract lowercase alphanumeric tokens plus their singular forms."""
        raw_tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
        stems = set(raw_tokens)
        for token in raw_tokens:
            if token.endswith("ies") and len(token) > 4:
                stems.add(token[:-3] + "y")
            elif token.endswith("es") and len(token) > 4:
                stems.add(token[:-2])
            elif token.endswith("s") and len(token) > 3:
                stems.add(token[:-1])
        return stems

    def link_schema(self, question: str) -> tuple[str, list[str]]:
        """Return (pruned DDL, table names) needed to answer the question."""
        q_lower = question.lower()
        q_tokens = self._tokenize(question)

        # 1. Explicit table name matches (primary anchor tables)
        matched_tables = {t for t in self.table_ddls if self._tokenize(t) & q_tokens}
        covered_columns = {col.lower() for t in matched_tables for col in self.table_columns[t]}

        # 2. Non-FK attribute column matches: only pull in additional tables for uncovered attributes
        for table, cols in self.table_columns.items():
            if table in matched_tables:
                continue
            for col in cols:
                col_low = col.lower()
                if col_low in {"id", "name"} or col_low.endswith("_id") or col_low in covered_columns:
                    continue
                col_tokens = self._tokenize(col)
                if col_tokens and col_tokens <= q_tokens:
                    matched_tables.add(table)
                    covered_columns.update(c.lower() for c in self.table_columns[table])

        # 3. Whole-word categorical value matches (prevents 'pro' matching inside 'products')
        for val, locations in self.value_to_table_col.items():
            if re.search(rf"\b{re.escape(val)}\b", q_lower) and not any(t in matched_tables for t, _ in locations):
                matched_tables.update(t for t, _ in locations)

        if not matched_tables:
            return self.full_schema, list(self.table_ddls)

        # 4. Connect disjoint matched tables via the shortest FK paths
        expanded_tables = self._expand_foreign_key_paths(matched_tables)
        ordered_tables = [t for t in self.table_ddls if t in expanded_tables]
        return "\n".join(self.table_ddls[t] for t in ordered_tables), ordered_tables

    def _expand_foreign_key_paths(self, seed_tables: set[str]) -> set[str]:
        """Add the bridge tables that connect every seed table to the first one."""
        seeds = sorted(seed_tables)
        expanded = set(seeds)
        for target in seeds[1:]:
            expanded.update(self._shortest_fk_path(seeds[0], target))
        return expanded

    def _shortest_fk_path(self, start: str, goal: str) -> list[str]:
        """Breadth-first search over the foreign key graph."""
        queue: deque[list[str]] = deque([[start]])
        visited = {start}
        while queue:
            path = queue.popleft()
            for neighbor in self.fk_graph.get(path[-1], set()):
                if neighbor == goal:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []


schema_linker = SchemaLinker()

