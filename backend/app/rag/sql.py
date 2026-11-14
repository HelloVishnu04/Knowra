import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import Engine, create_engine, inspect, text
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.core.config import settings
from app.llm.base import LLMProvider
from app.rag.base import RetrievalResult, RetrievedChunk, Retriever


class SQLGuardrailError(ValueError):
    """Raised before the database sees SQL that violates the policy."""


@dataclass(frozen=True)
class PreparedSQL:
    sql: str
    tables: tuple[str, ...]
    sensitive_tables: tuple[str, ...]


class SensitiveSQLApprovalRequired(RuntimeError):
    def __init__(self, prepared: PreparedSQL) -> None:
        self.prepared = prepared
        super().__init__(
            "Approval is required to read sensitive tables: "
            + ", ".join(prepared.sensitive_tables)
        )


def _table_name(table: exp.Table) -> str:
    parts = [str(part) for part in (table.catalog, table.db, table.name) if part]
    return ".".join(parts).lower()


def _configured_tables(value: str) -> set[str]:
    return {item.strip().lower() for item in value.split(",") if item.strip()}


class SQLGuardrails:
    _ALLOWED_FUNCTIONS: ClassVar[set[str]] = {
        "abs",
        "age",
        "avg",
        "cast",
        "ceil",
        "ceiling",
        "char_length",
        "coalesce",
        "count",
        "date_trunc",
        "extract",
        "floor",
        "greatest",
        "least",
        "length",
        "lower",
        "max",
        "min",
        "nullif",
        "round",
        "sum",
        "upper",
    }

    def __init__(
        self,
        allowed_tables: set[str],
        *,
        sensitive_tables: set[str] | None = None,
        row_limit: int = 100,
    ) -> None:
        self.allowed_tables = {name.lower() for name in allowed_tables}
        self.sensitive_tables = {name.lower() for name in (sensitive_tables or set())}
        if not self.allowed_tables:
            raise SQLGuardrailError(
                "SQL retrieval requires an explicit table allow-list"
            )
        if not self.sensitive_tables <= self.allowed_tables:
            raise SQLGuardrailError("Sensitive tables must also be allow-listed")
        if row_limit < 1:
            raise SQLGuardrailError("The SQL row limit must be positive")
        self.row_limit = row_limit

    def _resolve_table(self, name: str) -> str:
        if name in self.allowed_tables:
            return name
        if "." not in name:
            matches = [
                item for item in self.allowed_tables if item.rsplit(".", 1)[-1] == name
            ]
            if len(matches) == 1:
                return matches[0]
        raise SQLGuardrailError(f"Table is not allow-listed: {name}")

    def validate(self, sql: str) -> PreparedSQL:
        try:
            statements = parse(sql, read="postgres")
        except ParseError as exc:
            raise SQLGuardrailError(
                f"Generated SQL could not be parsed: {exc}"
            ) from exc
        if len(statements) != 1:
            raise SQLGuardrailError("Exactly one SQL statement is allowed")
        statement = statements[0]
        if not isinstance(statement, exp.Query):
            raise SQLGuardrailError("Only SELECT queries are allowed")
        if any(
            isinstance(node, (exp.DML, exp.DDL, exp.Command))
            for node in statement.walk()
        ):
            raise SQLGuardrailError(
                "Data-changing and administrative SQL is not allowed"
            )
        if statement.find(exp.Into) is not None:
            raise SQLGuardrailError("SELECT INTO is not allowed")
        if statement.args.get("locks"):
            raise SQLGuardrailError("Locking SELECT queries are not allowed")

        cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
        tables: list[str] = []
        for table in statement.find_all(exp.Table):
            name = _table_name(table)
            if not table.db and table.name.lower() in cte_names:
                continue
            resolved = self._resolve_table(name)
            if resolved not in tables:
                tables.append(resolved)
        if not tables:
            raise SQLGuardrailError("A query must read at least one allow-listed table")

        for function in statement.find_all(exp.Func):
            name = (
                str(function.name)
                if isinstance(function, exp.Anonymous)
                else function.sql_name()
            ).lower()
            if name not in self._ALLOWED_FUNCTIONS:
                raise SQLGuardrailError(f"SQL function is not allow-listed: {name}")

        limit = statement.args.get("limit")
        existing_limit: int | None = None
        if limit is not None and isinstance(limit.expression, exp.Literal):
            try:
                existing_limit = int(limit.expression.this)
            except (TypeError, ValueError):
                existing_limit = None
        if existing_limit is None or existing_limit > self.row_limit:
            statement = statement.limit(self.row_limit, copy=True)

        sensitive = tuple(name for name in tables if name in self.sensitive_tables)
        return PreparedSQL(
            sql=statement.sql(dialect="postgres"),
            tables=tuple(tables),
            sensitive_tables=sensitive,
        )


class SQLExecutor:
    def __init__(
        self,
        engine: Engine,
        *,
        statement_timeout_ms: int,
        row_limit: int,
    ) -> None:
        self.engine = engine
        self.statement_timeout_ms = statement_timeout_ms
        self.row_limit = row_limit

    def _configure_transaction(self, connection: Any) -> None:
        if self.engine.dialect.name == "postgresql":
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(
                text("SELECT set_config('statement_timeout', :value, true)"),
                {"value": f"{self.statement_timeout_ms}ms"},
            )

    def schema(self, tables: set[str]) -> list[dict[str, Any]]:
        inspector = inspect(self.engine)
        result: list[dict[str, Any]] = []
        for qualified_name in sorted(tables):
            if "." in qualified_name:
                schema, name = qualified_name.rsplit(".", 1)
            else:
                schema, name = None, qualified_name
            columns = inspector.get_columns(name, schema=schema)
            result.append(
                {
                    "table": qualified_name,
                    "columns": [
                        {
                            "name": column["name"],
                            "type": str(column["type"]),
                            "nullable": bool(column.get("nullable", True)),
                        }
                        for column in columns
                    ],
                }
            )
        return result

    def execute(self, prepared: PreparedSQL) -> dict[str, Any]:
        started = time.monotonic()
        with self.engine.connect() as connection, connection.begin():
            self._configure_transaction(connection)
            rows = (
                connection.execute(text(prepared.sql))
                .mappings()
                .fetchmany(self.row_limit + 1)
            )
        truncated = len(rows) > self.row_limit
        visible_rows = rows[: self.row_limit]
        json_rows = json.loads(
            json.dumps([dict(row) for row in visible_rows], default=str)
        )
        return {
            "sql": prepared.sql,
            "tables": list(prepared.tables),
            "columns": list(visible_rows[0].keys()) if visible_rows else [],
            "rows": json_rows,
            "row_count": len(visible_rows),
            "truncated": truncated,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }


def _extract_sql(value: str) -> str:
    fenced = re.search(
        r"```(?:sql)?\s*(.*?)```", value, flags=re.IGNORECASE | re.DOTALL
    )
    return (fenced.group(1) if fenced else value).strip().rstrip(";")


class SQLRetriever(Retriever):
    def __init__(
        self,
        provider: LLMProvider,
        *,
        model: str,
        guardrails: SQLGuardrails,
        executor: SQLExecutor,
    ) -> None:
        self.provider = provider
        self.model = model
        self.guardrails = guardrails
        self.executor = executor

    @classmethod
    def from_settings(cls, provider: LLMProvider, *, model: str) -> "SQLRetriever":
        url = settings.SQL_DATABASE_URL or settings.DATABASE_URL
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        guardrails = SQLGuardrails(
            _configured_tables(settings.SQL_ALLOWED_TABLES),
            sensitive_tables=_configured_tables(settings.SQL_SENSITIVE_TABLES),
            row_limit=settings.DEFAULT_ROW_LIMIT,
        )
        return cls(
            provider,
            model=model,
            guardrails=guardrails,
            executor=SQLExecutor(
                create_engine(url, pool_pre_ping=True),
                statement_timeout_ms=settings.STATEMENT_TIMEOUT_MS,
                row_limit=settings.DEFAULT_ROW_LIMIT,
            ),
        )

    async def prepare(self, query: str) -> PreparedSQL:
        schema = await asyncio.to_thread(
            self.executor.schema, self.guardrails.allowed_tables
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Convert the question to one PostgreSQL SELECT query. Use only the "
                    "provided tables and columns. Return SQL only, with no explanation. "
                    "Never use SELECT *, mutations, DDL, system catalogs, or functions "
                    "that access files, settings, extensions, or server state.\n"
                    f"Schema: {json.dumps(schema, default=str)}"
                ),
            },
            {"role": "user", "content": query},
        ]
        generated = await self.provider.chat(messages, self.model)
        return self.guardrails.validate(_extract_sql(generated))

    async def execute_prepared(self, arguments: dict[str, Any]) -> dict[str, Any]:
        prepared = self.guardrails.validate(str(arguments.get("sql", "")))
        expected = {str(item).lower() for item in arguments.get("tables", [])}
        if expected and expected != set(prepared.tables):
            raise SQLGuardrailError("Approved SQL table set changed before execution")
        return await asyncio.to_thread(self.executor.execute, prepared)

    @staticmethod
    def result_to_retrieval(query: str, result: dict[str, Any]) -> RetrievalResult:
        sql = str(result["sql"])
        sql_id = hashlib.sha256(sql.encode()).hexdigest()[:20]
        content = (
            f"Generated SQL:\n{sql}\n\n"
            f"Query result:\n{json.dumps(result['rows'], default=str)}"
        )
        return RetrievalResult(
            source="sql",
            query=query,
            latency_ms=int(result.get("latency_ms", 0)),
            chunks=[
                RetrievedChunk(
                    id=f"sql:{sql_id}",
                    content=content,
                    source="sql",
                    score=1.0,
                    metadata={
                        "label": "SQL query result",
                        "sql": sql,
                        "tables": result.get("tables", []),
                        "columns": result.get("columns", []),
                        "row_count": result.get("row_count", 0),
                        "truncated": result.get("truncated", False),
                    },
                )
            ],
        )

    async def retrieve(
        self,
        query: str,
        *,
        workspace_id: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> RetrievalResult:
        del workspace_id, top_k, filters
        prepared = await self.prepare(query)
        if prepared.sensitive_tables:
            raise SensitiveSQLApprovalRequired(prepared)
        result = await asyncio.to_thread(self.executor.execute, prepared)
        return self.result_to_retrieval(query, result)
