"""
A small semantic layer: the only path from a question to the database.

A caller (the AI assistant, a test, a dashboard) sends a MetricQuery naming a
model, measures, dimensions, and filters from semantic_model.yaml. This module
    1. validates every name against the YAML (anything unknown is rejected),
    2. adds the user's territory filter (row level security), and
    3. compiles parameterized SQL and runs it read only.

Filter values are always passed as query parameters, never pasted into SQL,
so a value like "x'; DROP TABLE cases; --" is just a string that matches
nothing. In production this module is Cube; the ideas map one to one.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import duckdb
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MODEL_PATH = os.path.join(HERE, "semantic_model.yaml")
DEFAULT_DB_PATH = os.path.join(HERE, "data", "crm_demo.duckdb")

OPERATORS = {"equals", "not_equals", "contains", "in", "gt", "lt"}
MAX_LIMIT = 200
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class QueryError(ValueError):
    """Raised when a request asks for something the semantic model does not define."""


@dataclass
class User:
    """Who is asking. territory=None means they can see every territory."""
    name: str
    territory: Optional[str] = None


@dataclass
class MetricQuery:
    model: str
    measures: List[str]
    dimensions: List[str] = field(default_factory=list)
    filters: List[Dict[str, Any]] = field(default_factory=list)
    date_range: Optional[List[str]] = None
    order_by: Optional[str] = None
    order_direction: str = "desc"
    limit: int = 50

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MetricQuery":
        return cls(
            model=d.get("model", ""),
            measures=list(d.get("measures") or []),
            dimensions=list(d.get("dimensions") or []),
            filters=list(d.get("filters") or []),
            date_range=d.get("date_range"),
            order_by=d.get("order_by"),
            order_direction=d.get("order_direction", "desc"),
            limit=int(d.get("limit", 50)),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v not in (None, [], "")}


class SemanticLayer:
    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, db_path: str = DEFAULT_DB_PATH):
        with open(model_path) as f:
            spec = yaml.safe_load(f)
        self.as_of = str(spec["as_of_date"])
        self.models: Dict[str, Dict[str, Any]] = spec["models"]
        self.db_path = db_path

    # ---------- catalog, used to tell the assistant what exists ----------
    def catalog_text(self) -> str:
        lines = [f"Data is a snapshot as of {self.as_of}."]
        for name, m in self.models.items():
            lines.append(f"\nMODEL {name}: {' '.join(m['description'].split())}")
            if m.get("time_dimension"):
                lines.append("  supports date_range on its date")
            lines.append("  dimensions:")
            for d, spec in m["dimensions"].items():
                lines.append(f"    - {d}: {spec['description']}")
            lines.append("  measures:")
            for ms, spec in m["measures"].items():
                lines.append(f"    - {ms}: {spec['description']}")
        return "\n".join(lines)

    # ---------- validation and compilation ----------
    def compile(self, q: MetricQuery, user: User) -> Tuple[str, List[Any]]:
        if q.model not in self.models:
            raise QueryError(f"Unknown model '{q.model}'. Available: {', '.join(self.models)}")
        m = self.models[q.model]
        dims, meas = m["dimensions"], m["measures"]

        if not q.measures:
            raise QueryError("Ask for at least one measure.")
        for name in q.measures:
            if name not in meas:
                raise QueryError(f"Unknown measure '{name}' in model '{q.model}'. Available: {', '.join(meas)}")
        for name in q.dimensions:
            if name not in dims:
                raise QueryError(f"Unknown dimension '{name}' in model '{q.model}'. Available: {', '.join(dims)}")
        if not 1 <= q.limit <= MAX_LIMIT:
            raise QueryError(f"limit must be between 1 and {MAX_LIMIT}")
        if q.order_direction not in ("asc", "desc"):
            raise QueryError("order_direction must be 'asc' or 'desc'")
        if q.order_by and q.order_by not in q.measures + q.dimensions:
            raise QueryError("order_by must be one of the requested measures or dimensions")

        where, params = [], []

        # Row level security: added by the system, not by the caller, so it cannot be skipped.
        if user.territory is not None:
            where.append(f"({dims['territory']['sql']}) = ?")
            params.append(user.territory)

        for f in q.filters:
            dim, op, values = f.get("dimension"), f.get("operator"), f.get("values")
            if dim not in dims:
                raise QueryError(f"Cannot filter on unknown dimension '{dim}'")
            if op not in OPERATORS:
                raise QueryError(f"Unknown operator '{op}'. Use one of: {', '.join(sorted(OPERATORS))}")
            if not isinstance(values, list) or not values:
                raise QueryError("Filter values must be a non-empty list")
            expr = f"({dims[dim]['sql']})"
            if op == "equals":
                where.append(f"{expr} = ?"); params.append(values[0])
            elif op == "not_equals":
                where.append(f"{expr} <> ?"); params.append(values[0])
            elif op == "contains":
                where.append(f"{expr} ILIKE ?"); params.append(f"%{values[0]}%")
            elif op == "in":
                where.append(f"{expr} IN ({', '.join('?' for _ in values)})"); params.extend(values)
            elif op == "gt":
                where.append(f"{expr} > ?"); params.append(values[0])
            elif op == "lt":
                where.append(f"{expr} < ?"); params.append(values[0])

        if q.date_range:
            time_col = m.get("time_dimension")
            if not time_col:
                raise QueryError(f"Model '{q.model}' has no date to filter on")
            if len(q.date_range) != 2 or not all(DATE_RE.match(str(d)) for d in q.date_range):
                raise QueryError("date_range must be two dates, YYYY-MM-DD")
            where.append(f"{time_col} BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)")
            params.extend(q.date_range)

        select = [f"{dims[d]['sql']} AS {d}" for d in q.dimensions]
        select += [f"{meas[ms]['sql']} AS {ms}" for ms in q.measures]
        base_sql = m["sql"].replace("{as_of}", f"DATE '{self.as_of}'")

        sql = f"SELECT {', '.join(select)}\nFROM (\n{base_sql}) AS base"
        if where:
            sql += "\nWHERE " + "\n  AND ".join(where)
        if q.dimensions:
            sql += "\nGROUP BY " + ", ".join(str(i) for i in range(1, len(q.dimensions) + 1))
        order = q.order_by or (q.measures[0])
        sql += f"\nORDER BY {order} {q.order_direction.upper()} NULLS LAST"
        sql += f"\nLIMIT {int(q.limit)}"
        return sql, params

    def run(self, q: MetricQuery, user: User) -> Tuple[pd.DataFrame, str, List[Any]]:
        sql, params = self.compile(q, user)
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            df = con.execute(sql, params).df()
        finally:
            con.close()
        # SUM() comes back as a float in pandas; show whole numbers as whole numbers.
        for col in df.columns:
            if df[col].dtype.kind == "f" and (df[col].dropna() % 1 == 0).all():
                df[col] = df[col].astype("Int64")
        return df, sql, params

    def territories(self) -> List[Tuple[str, str]]:
        """(territory_name, tam_name) pairs, for the sign-in picker."""
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            rows = con.execute("SELECT territory_name, tam_name FROM territories ORDER BY 1").fetchall()
        finally:
            con.close()
        return [(r[0], r[1]) for r in rows]
