"""SQL validation and rule-based repair of common small-model mistakes before execution."""

import re
from typing import Callable

from backend.database.query_executor import explain_query
from backend.services.schema_linker import SchemaLinker, schema_linker

IDENT = r"[A-Za-z_][A-Za-z0-9_]*"
SELECT_CLAUSE = re.compile(r"^\s*SELECT\s+(.*?)\s+FROM\b", re.IGNORECASE | re.DOTALL)
SINGLE_AGGREGATE = re.compile(r"^(?:COUNT|SUM|AVG|MIN|MAX)\s*\([^)]+\)$", re.IGNORECASE)
TABLE_REF = re.compile(rf"\b(?:FROM|JOIN)\s+({IDENT})(?:\s+(?:AS\s+)?({IDENT}))?", re.IGNORECASE)
JOIN_CLAUSE = re.compile(
    rf"\s+JOIN\s+({IDENT})(?:\s+(?:AS\s+)?({IDENT}))?\s+ON\s+([A-Za-z0-9_.]+)\s*([=<>!]+)\s*([A-Za-z0-9_.]+)",
    re.IGNORECASE,
)
SQL_KEYWORDS = {"ON", "WHERE", "GROUP", "ORDER", "LIMIT", "HAVING", "JOIN", "INNER", "LEFT"}
NUMERIC_TYPES = ("INT", "REAL", "NUM", "FLOAT")
GROUPING_WORDS = ("each", "per", "by ", "every", "which ", "top ", "most ")


class SQLValidator:
    """Checks generated SQL against the catalog and fixes known SLM error patterns."""

    def __init__(self, linker: SchemaLinker) -> None:
        self.linker = linker
        self.table_columns = linker.table_columns
        self.fk_relations = linker.fk_relations
        self.value_to_table_col = linker.value_to_table_col

    def validate(
        self,
        question: str,
        sql: str,
        llm_repair: Callable[[str, str], str] | None = None,
    ) -> tuple[str, list[str]]:
        """Return (repaired SQL, applied repairs). llm_repair(failed_sql, error) is used as a last resort."""
        sql = sql.strip().rstrip(";")
        first_token = sql.split()[0].upper() if sql else ""
        if first_token not in {"SELECT", "WITH"} or ";" in sql:
            raise PermissionError("Only single read-only SELECT statements are permitted.")

        _, linked_tables = self.linker.link_schema(question)
        allowed_tables = {t.lower() for t in linked_tables}

        sql, repairs = self._apply_repairs(question, sql, allowed_tables)

        error = explain_query(sql)
        if error:
            sql_fixed, err_repairs = self._fix_explain_error(sql, error)
            if err_repairs and not explain_query(sql_fixed):
                sql = sql_fixed
                repairs.extend(err_repairs)
                error = None

        if error and llm_repair:
            repaired_sql = llm_repair(sql, error).rstrip(";")
            sql_from_llm, step_repairs = self._apply_repairs(question, repaired_sql, allowed_tables)
            repairs.append(f"llm_self_correction ({error})")
            repairs.extend(step_repairs)

            err_after_llm = explain_query(sql_from_llm)
            if not err_after_llm:
                sql = sql_from_llm
            else:
                sql_fixed, err_repairs = self._fix_explain_error(sql_from_llm, err_after_llm)
                if not explain_query(sql_fixed):
                    sql = sql_fixed
                    repairs.extend(err_repairs)
                else:
                    sql = sql_from_llm

        return sql + ";", repairs

    def _apply_repairs(self, question: str, sql: str, allowed_tables: set[str]) -> tuple[str, list[str]]:
        repairs: list[str] = []
        q_lower = question.lower()

        sql, step_repairs = self._strip_unknown_joins(sql, allowed_tables)
        repairs.extend(step_repairs)

        for step in (
            self._fix_join_on_clauses,
            self._fix_alias_columns,
            self._fix_unaliased_columns,
            self._inject_missing_fk_join,
            self._strip_unmentioned_filters,
            self._fix_value_filter_columns,
            self._where_to_having_avg,
            self._count_to_sum,
            self._remove_spurious_group_by,
            self._project_group_column,
        ):
            sql, step_repairs = step(sql, q_lower)
            repairs.extend(step_repairs)
        return sql, repairs

    def _columns(self, table: str) -> set[str]:
        return {c.lower() for c in self.table_columns.get(table, {})}

    @staticmethod
    def _table_singular(table: str) -> str:
        """Return the singular form of a table name."""
        t = table.lower()
        if t.endswith("ies") and len(t) > 4:
            return t[:-3] + "y"
        if t.endswith("es") and len(t) > 4:
            return t[:-2]
        if t.endswith("s") and len(t) > 3:
            return t[:-1]
        return t

    def _resolve_column(self, table: str, col: str) -> str | None:
        """Resolve column names including common SLM hallucinations like product_name->name or product_id->id."""
        cols = self._columns(table)
        col_low = col.lower()
        if col_low in cols:
            return col_low

        singular = self._table_singular(table)
        if col_low in {f"{singular}_name", f"{table.lower()}_name"} and "name" in cols:
            return "name"

        if col_low in {f"{singular}_id", f"{table.lower()}_id"} and "id" in cols:
            return "id"

        return None

    @staticmethod
    def _aliases(sql: str) -> dict[str, str]:
        """Map each alias (or bare table name) in FROM/JOIN clauses to its table."""
        alias_map: dict[str, str] = {}
        for table, alias in TABLE_REF.findall(sql):
            alias_map[alias if alias and alias.upper() not in SQL_KEYWORDS else table] = table
        return alias_map

    def _strip_unknown_joins(self, sql: str, allowed_tables: set[str]) -> tuple[str, list[str]]:
        """Remove JOINs to non-existent tables, unlinked tables, or duplicate self-joins."""
        repairs: list[str] = []
        from_match = re.search(rf"\bFROM\s+({IDENT})", sql, re.IGNORECASE)
        seen_tables = {from_match.group(1).lower()} if from_match else set()

        def check_join(match: re.Match) -> str:
            join_table = match.group(1).lower()
            if join_table in allowed_tables and join_table not in seen_tables:
                seen_tables.add(join_table)
                return match.group(0)
            repairs.append(f"removed_join:{match.group(1)}")
            return ""

        return JOIN_CLAUSE.sub(check_join, sql), repairs

    def _fix_join_on_clauses(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Ensure JOIN ... ON predicates use the catalog foreign key between the joined tables."""
        repairs: list[str] = []
        alias_map = self._aliases(sql)
        if len(alias_map) < 2:
            return sql, repairs

        def fix_on(match: re.Match) -> str:
            join_table, join_alias, lhs, op, rhs = match.groups()
            j_alias = join_alias if join_alias and join_alias.upper() not in SQL_KEYWORDS else join_table
            j_table = alias_map.get(j_alias, join_table)

            candidates = []
            for other_alias, other_table in alias_map.items():
                if other_alias == j_alias:
                    continue
                for fk_from_t, fk_from_c, fk_to_t, fk_to_c in self.fk_relations:
                    if fk_from_t == other_table and fk_to_t == j_table:
                        candidates.append((other_alias, fk_from_c, j_alias, fk_to_c))
                    elif fk_from_t == j_table and fk_to_t == other_table:
                        candidates.append((j_alias, fk_from_c, other_alias, fk_to_c))

            if not candidates:
                return match.group(0)

            chosen = next(
                (c for c in candidates if lhs.lower().startswith(c[0].lower() + ".") or rhs.lower().startswith(c[0].lower() + ".")),
                candidates[0],
            )
            expected_left = f"{chosen[0]}.{chosen[1]}"
            expected_right = f"{chosen[2]}.{chosen[3]}"
            if {lhs.lower(), rhs.lower()} == {expected_left.lower(), expected_right.lower()} and op == "=":
                return match.group(0)

            repairs.append(f"fk_on_fix:{expected_left}={expected_right}")
            alias_part = f" AS {join_alias}" if join_alias and join_alias.upper() not in SQL_KEYWORDS else ""
            return f" JOIN {join_table}{alias_part} ON {expected_left} = {expected_right}"

        return JOIN_CLAUSE.sub(fix_on, sql), repairs

    def _fix_alias_columns(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Fix alias.column references where the column is hallucinated or belongs to another joined table."""
        repairs: list[str] = []
        alias_map = self._aliases(sql)
        is_single_unaliased = len(alias_map) == 1 and next(iter(alias_map.items()))[0] == next(iter(alias_map.values()))

        def replace_ref(match: re.Match) -> str:
            alias, col = match.groups()
            if alias in alias_map:
                curr_table = alias_map[alias]
                resolved = self._resolve_column(curr_table, col)
                if resolved:
                    if resolved != col.lower():
                        repairs.append(f"alias_fix:{alias}.{col}->{alias}.{resolved}")
                        return f"{alias}.{resolved}"
                    return match.group(0)

            owners = []
            for a, t in alias_map.items():
                resolved = self._resolve_column(t, col)
                if resolved:
                    owners.append((a, resolved))

            if len(owners) != 1:
                return match.group(0)

            owner_alias, resolved_col = owners[0]
            if is_single_unaliased:
                repairs.append(f"alias_fix:{alias}.{col}->{resolved_col}")
                return resolved_col
            repairs.append(f"alias_fix:{alias}.{col}->{owner_alias}.{resolved_col}")
            return f"{owner_alias}.{resolved_col}"

        if not alias_map:
            return sql, repairs
        return re.sub(rf"\b({IDENT})\.({IDENT})\b", replace_ref, sql), repairs

    def _fix_unaliased_columns(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Fix bare column hallucinations like product_name -> name or product_id -> id."""
        repairs: list[str] = []
        alias_map = self._aliases(sql)
        if not alias_map:
            return sql, repairs

        def replace_bare(match: re.Match) -> str:
            prefix, word = match.group(1), match.group(2)
            if word.upper() in SQL_KEYWORDS:
                return match.group(0)
            if any(word.lower() in self._columns(t) for t in self.table_columns):
                return match.group(0)

            candidates = []
            for alias, table in alias_map.items():
                resolved = self._resolve_column(table, word)
                if resolved and resolved != word.lower():
                    target = f"{alias}.{resolved}" if len(alias_map) > 1 or alias != table else resolved
                    candidates.append(target)

            if len(candidates) == 1:
                target_ref = candidates[0]
                repairs.append(f"col_resolve:{word}->{target_ref}")
                return f"{prefix}{target_ref}"

            return match.group(0)

        pattern = re.compile(rf"(^|[^.'\"\w])\b({IDENT})\b")
        return pattern.sub(replace_bare, sql), repairs

    def _fix_explain_error(self, sql: str, error: str) -> tuple[str, list[str]]:
        """Targeted repair when SQLite EXPLAIN QUERY PLAN fails on a missing column."""
        repairs: list[str] = []
        match = re.search(r"no such column:\s*(?:([A-Za-z0-9_]+)\.)?([A-Za-z0-9_]+)", error, re.IGNORECASE)
        if not match:
            return sql, repairs

        col_alias, col_name = match.groups()
        old_ref = f"{col_alias}.{col_name}" if col_alias else col_name

        if col_name.lower().endswith("_name"):
            target = f"{col_alias}.name" if col_alias else "name"
            sql = re.sub(rf"\b{re.escape(old_ref)}\b", target, sql)
            repairs.append(f"explain_fix:{old_ref}->{target}")
            return sql, repairs

        if col_name.lower().endswith("_id"):
            target = f"{col_alias}.id" if col_alias else "id"
            sql = re.sub(rf"\b{re.escape(old_ref)}\b", target, sql)
            repairs.append(f"explain_fix:{old_ref}->{target}")
            return sql, repairs

        select_match = SELECT_CLAUSE.match(sql)
        if select_match:
            select_body = select_match.group(1)
            items = [item.strip() for item in select_body.split(",") if item.strip()]
            remaining = [item for item in items if not re.search(rf"\b{re.escape(old_ref)}\b", item)]
            if remaining and len(remaining) < len(items):
                new_select = ", ".join(remaining)
                sql = re.sub(r"^\s*SELECT\s+.*?\s+FROM\b", f"SELECT {new_select} FROM", sql, count=1, flags=re.IGNORECASE)
                repairs.append(f"explain_drop_col:{old_ref}")
                return sql, repairs

        return sql, repairs

    def _inject_missing_fk_join(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Add a JOIN when a single-table query filters on a column of an FK-referenced table."""
        alias_map = self._aliases(sql)
        where = re.search(r"\bWHERE\s+(.*?)(?:\bGROUP\b|\bORDER\b|\bLIMIT\b|$)", sql, re.IGNORECASE)
        if len(alias_map) != 1 or not where:
            return sql, []

        base_alias, base_table = next(iter(alias_map.items()))
        if base_table not in self.table_columns:
            return sql, []

        for col in re.findall(rf"\b({IDENT})\s*[=<>!]", where.group(1)):
            if col.lower() in self._columns(base_table):
                continue
            for from_table, from_col, to_table, to_col in self.fk_relations:
                if from_table == base_table and col.lower() in self._columns(to_table):
                    join = f" JOIN {to_table} ON {base_alias}.{from_col} = {to_table}.{to_col}"
                    sql = re.sub(
                        rf"\bFROM\s+{re.escape(base_table)}(?:\s+(?:AS\s+)?{re.escape(base_alias)})?",
                        f"FROM {base_table}{join}",
                        sql,
                        count=1,
                        flags=re.IGNORECASE,
                    )
                    return sql, [f"injected_fk_join:{to_table}"]
        return sql, []

    @staticmethod
    def _strip_unmentioned_filters(sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Drop WHERE predicates whose string or numeric literal never appears in the question."""
        parts = re.split(r"\bWHERE\b", sql, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) != 2:
            return sql, []

        prefix, rest = parts
        tail_start = re.search(r"(\s+GROUP\s+BY\b.*|\s+ORDER\s+BY\b.*|\s+LIMIT\b.*|$)", rest, re.IGNORECASE).start()
        where_body, tail = rest[:tail_start], rest[tail_start:]

        repairs: list[str] = []
        kept: list[str] = []
        aggregate_words = {"total", "average", "avg", "count", "sum", "min", "max", "each", "every", "per", "all"}
        for pred in (p.strip() for p in re.split(r"\bAND\b", where_body, flags=re.IGNORECASE) if p.strip()):
            str_literal = re.search(r"['\"]([^'\"]+)['\"]", pred)
            num_literal = re.search(r"[=<>!]+\s*(\d+(?:\.\d+)?)\b", pred)
            if str_literal:
                val = str_literal.group(1).strip().lower()
                if val in aggregate_words or val not in q_lower:
                    repairs.append(f"stripped_unmentioned_filter:{pred}")
                    continue
            elif num_literal and num_literal.group(1) not in q_lower:
                repairs.append(f"stripped_unmentioned_numeric_filter:{pred}")
                continue
            kept.append(pred)

        sql = f"{prefix}WHERE {' AND '.join(kept)}{tail}" if kept else f"{prefix.rstrip()}{tail}"
        return sql, repairs

    def _fix_value_filter_columns(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Align 'WHERE col = literal' with the catalog column that actually stores that literal."""
        repairs: list[str] = []
        alias_map = self._aliases(sql)
        if not alias_map:
            return sql, repairs

        def replace_filter(match: re.Match) -> str:
            lhs, quote, literal = match.groups()
            locations = self.value_to_table_col.get(literal.strip().lower(), [])
            if not locations:
                return match.group(0)

            valid_refs = [
                (alias, col)
                for alias, table in alias_map.items()
                for loc_table, col in locations
                if loc_table == table
            ]
            if len(valid_refs) != 1:
                return match.group(0)

            target_alias, target_col = valid_refs[0]
            target_ref = (
                f"{target_alias}.{target_col}"
                if len(alias_map) > 1 or target_alias != alias_map[target_alias]
                else target_col
            )
            if lhs.lower() == target_ref.lower():
                return match.group(0)

            repairs.append(f"value_col_fix:{lhs}->{target_ref}")
            return f"{target_ref} = {quote}{literal}{quote}"

        return re.sub(r"\b([A-Za-z0-9_.]+)\s*=\s*(['\"])([^'\"]+)\2", replace_filter, sql), repairs

    @staticmethod
    def _where_to_having_avg(sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Turn 'WHERE col > N GROUP BY g' into 'GROUP BY g HAVING AVG(col) > N' for 'average X greater than N'."""
        if not re.search(r"\baverage\s+[a-z_]+\s+(?:greater|more|less|higher|lower)\s+than\b", q_lower):
            return sql, []
        match = re.search(
            r"\s+WHERE\s+([A-Za-z0-9_.]+)\s*([<>]=?)\s*(\d+(?:\.\d+)?)\s+GROUP\s+BY\s+([A-Za-z0-9_.]+)",
            sql,
            re.IGNORECASE,
        )
        if not match or "HAVING" in sql.upper():
            return sql, []

        col, op, val, group_col = match.groups()
        sql = f"{sql[:match.start()]} GROUP BY {group_col} HAVING AVG({col}) {op} {val}{sql[match.end():]}"
        return sql, [f"where_to_having_avg:AVG({col}){op}{val}"]

    def _count_to_sum(self, sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Replace COUNT(*) with SUM(numeric column) when the question asks for 'total <column>'."""
        total = re.search(r"\btotal\s+([a-z_]+)\b", q_lower)
        if not total or "COUNT(*)" not in sql.upper():
            return sql, []

        noun = total.group(1).rstrip("s")
        alias_map = self._aliases(sql)
        numeric_cols = [
            (alias, table, col)
            for alias, table in alias_map.items()
            for col, col_type in self.table_columns.get(table, {}).items()
            if any(t in col_type for t in NUMERIC_TYPES)
        ]
        match = next((c for c in numeric_cols if c[2].lower() == noun), None) or next(
            (c for c in numeric_cols if noun in c[2].lower()), None
        )
        if not match:
            return sql, []

        alias, table, col = match
        column_ref = f"{alias}.{col}" if len(alias_map) > 1 or alias != table else col
        sql = re.sub(r"COUNT\(\*\)", f"SUM({column_ref})", sql, count=1, flags=re.IGNORECASE)
        return sql, [f"agg_fix:COUNT(*)->SUM({column_ref})"]

    @staticmethod
    def _remove_spurious_group_by(sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Remove GROUP BY from a single-aggregate query when the question does not ask for grouping."""
        if any(w in q_lower for w in GROUPING_WORDS) or re.search(r"\bHAVING\b", sql, re.IGNORECASE):
            return sql, []
        select = SELECT_CLAUSE.match(sql)
        if not select or not SINGLE_AGGREGATE.match(select.group(1).strip()):
            return sql, []

        new_sql = re.sub(r"\s+GROUP\s+BY\s+[A-Za-z0-9_.,\s]+$", "", sql, flags=re.IGNORECASE)
        return (new_sql, ["removed_spurious_group_by"]) if new_sql != sql else (sql, [])

    @staticmethod
    def _project_group_column(sql: str, q_lower: str) -> tuple[str, list[str]]:
        """Ensure SELECT projections in GROUP BY queries match the grouped column plus aggregates."""
        group = re.search(r"\bGROUP\s+BY\s+([A-Za-z0-9_.,\s]+?)(?:\s+HAVING|\s+ORDER|\s+LIMIT|$)", sql, re.IGNORECASE)
        select = SELECT_CLAUSE.match(sql)
        if not group or not select:
            return sql, []

        repairs: list[str] = []
        group_col = group.group(1).strip().split(",")[0].strip()
        select_clause = select.group(1).strip()
        has_having = bool(re.search(r"\bHAVING\b", sql, re.IGNORECASE))

        if not has_having:
            items = [i.strip() for i in select_clause.split(",") if i.strip()]
            agg_items = [i for i in items if "(" in i]
            non_agg_items = [i for i in items if "(" not in i]
            if agg_items and [c.lower() for c in non_agg_items] != [group_col.lower()]:
                new_select = f"{group_col}, {', '.join(agg_items)}"
                sql = re.sub(r"^\s*SELECT\s+.*?\s+FROM\b", f"SELECT {new_select} FROM", sql, count=1, flags=re.IGNORECASE)
                repairs.append(f"project_group_col:{group_col}")
        elif "(" not in select_clause and group_col.lower() not in select_clause.lower():
            sql = re.sub(r"^\s*SELECT\s+.*?\s+FROM\b", f"SELECT {group_col} FROM", sql, count=1, flags=re.IGNORECASE)
            repairs.append(f"having_select_fix:{select_clause}->{group_col}")

        if has_having:
            having_nums = set(re.findall(r"\bHAVING\b.*?\b(\d+)\b", sql, re.IGNORECASE))
            where = re.search(r"\s+WHERE\s+([A-Za-z0-9_.]+\s*[<>!=]+\s*(\d+))(?=\s+GROUP\s+BY)", sql, re.IGNORECASE)
            if where and where.group(2) in having_nums:
                where_col = where.group(1).split()[0].split(".")[-1].lower()
                if where_col not in q_lower:
                    sql = sql[:where.start()] + sql[where.end():]
                    repairs.append("removed_duplicate_where_threshold")

        return sql, repairs


sql_validator = SQLValidator(schema_linker)
