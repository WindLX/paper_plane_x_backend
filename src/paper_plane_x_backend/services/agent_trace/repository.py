"""Agent Trace 数据仓库.

封装所有 agent_traces 表的数据库访问，不包含任何业务编排或外部服务调用逻辑。
"""

import json
import logging
from typing import Any, cast

from paper_plane_x_backend.models import AgentTrace
from paper_plane_x_backend.services.database import Database

logger = logging.getLogger(__name__)


class AgentTraceRepositoryError(Exception):
    """AgentTraceRepository 异常."""

    def __init__(
        self,
        message: str,
        trace_id: str | None = None,
        error_code: str = "bad_request",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.trace_id = trace_id
        self.error_code = error_code


class AgentTraceRepository:
    """Agent Trace 数据访问层."""

    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _parse_messages(value: object) -> list[dict[str, Any]]:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            if isinstance(parsed, list):
                parsed_list = cast(list[Any], parsed)
                return [
                    {k: v for k, v in item_dict.items()}
                    for item in parsed_list
                    if isinstance(item, dict)
                    for item_dict in [cast(dict[str, Any], item)]
                ]
            return []

        if isinstance(value, list):
            value_list = cast(list[Any], value)
            return [
                {k: v for k, v in item_dict.items()}
                for item in value_list
                if isinstance(item, dict)
                for item_dict in [cast(dict[str, Any], item)]
            ]

        return []

    @staticmethod
    def _parse_usage_payload(value: object) -> dict[str, Any] | None:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, dict):
                parsed_dict = cast(dict[str, Any], parsed)
                return {k: v for k, v in parsed_dict.items()}
            return None

        if isinstance(value, dict):
            value_dict = cast(dict[str, Any], value)
            return {k: v for k, v in value_dict.items()}

        return None

    @staticmethod
    def _parse_tools(value: object) -> list[dict[str, Any]] | None:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return None
            if isinstance(parsed, list):
                parsed_list = cast(list[Any], parsed)
                return [
                    {k: v for k, v in item_dict.items()}
                    for item in parsed_list
                    if isinstance(item, dict)
                    for item_dict in [cast(dict[str, Any], item)]
                ]
            return None
        if isinstance(value, list):
            value_list = cast(list[Any], value)
            return [
                {k: v for k, v in item_dict.items()}
                for item in value_list
                if isinstance(item, dict)
                for item_dict in [cast(dict[str, Any], item)]
            ]
        return None

    def _row_to_trace(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": row["trace_id"],
            "agent_name": row["agent_name"],
            "messages": self._parse_messages(row.get("messages")),
            "llm_model": row.get("llm_model"),
            "prompt_tokens": row.get("prompt_tokens"),
            "completion_tokens": row.get("completion_tokens"),
            "total_tokens": row.get("total_tokens"),
            "usage_payload": self._parse_usage_payload(row.get("usage_payload")),
            "tools": self._parse_tools(row.get("tools")),
            "caller": row.get("caller"),
            "caller_id": row.get("caller_id"),
            "created_at": row["created_at"],
        }

    def batch_get(self, trace_ids: list[str]) -> list[dict[str, Any]]:
        """批量查询 agent traces."""
        if not trace_ids:
            return []
        placeholders = ", ".join(["?"] * len(trace_ids))
        rows = self.db.fetchall(
            f"""
            SELECT
                trace_id, agent_name, messages, llm_model,
                prompt_tokens, completion_tokens, total_tokens, usage_payload,
                tools, caller, caller_id, created_at
            FROM agent_traces
            WHERE trace_id IN ({placeholders})
            """,
            tuple(trace_ids),
        )
        logger.debug(
            "event=agent_trace.batch_get_completed requested=%s found=%s",
            len(trace_ids),
            len(rows),
        )
        return [self._row_to_trace(row) for row in rows]

    def delete(self, trace_id: str) -> None:
        """删除单条 trace（含存在检查）."""
        row = self.db.fetchone(
            "SELECT 1 FROM agent_traces WHERE trace_id = ?",
            (trace_id,),
        )
        if row is None:
            logger.warning(
                "event=agent_trace.delete_not_found trace_id=%s",
                trace_id,
            )
            raise AgentTraceRepositoryError(
                f"Trace {trace_id} not found",
                trace_id=trace_id,
                error_code="not_found",
            )
        self.db.delete("agent_traces", "trace_id = ?", (trace_id,))
        logger.info("event=agent_trace.deleted trace_id=%s", trace_id)

    def create(self, trace: AgentTrace) -> None:
        """插入 agent trace."""
        self.db.insert("agent_traces", trace.to_db_dict())
        logger.info(
            "event=agent.trace_created trace_id=%s agent=%s",
            trace.trace_id,
            trace.agent_name,
        )

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
        agent_name: str | None = None,
        caller: str | None = None,
        caller_id: str | None = None,
        llm_model: str | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
    ) -> list[dict[str, Any]]:
        """分页列式查询 agent traces."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if agent_name:
            where_clauses.append("agent_name = ?")
            params.append(agent_name)
        if caller:
            where_clauses.append("caller = ?")
            params.append(caller)
        if caller_id:
            where_clauses.append("caller_id = ?")
            params.append(caller_id)
        if llm_model:
            where_clauses.append("llm_model = ?")
            params.append(llm_model)
        if created_at_from:
            where_clauses.append("created_at >= ?")
            params.append(created_at_from)
        if created_at_to:
            where_clauses.append("created_at <= ?")
            params.append(created_at_to)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        order_by = f"{sort_by} {sort_order.upper()}"

        rows = self.db.fetchall(
            f"""
            SELECT
                trace_id, agent_name, messages, llm_model,
                prompt_tokens, completion_tokens, total_tokens, usage_payload,
                tools, caller, caller_id, created_at
            FROM agent_traces
            {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
            """,
            tuple([*params, limit, offset]),
        )
        logger.debug(
            "event=agent_trace.list_completed offset=%s limit=%s returned=%s",
            offset,
            limit,
            len(rows),
        )
        return [self._row_to_trace(row) for row in rows]

    def count(
        self,
        *,
        agent_name: str | None = None,
        caller: str | None = None,
        caller_id: str | None = None,
        llm_model: str | None = None,
        created_at_from: str | None = None,
        created_at_to: str | None = None,
    ) -> int:
        """统计符合条件的 trace 数量."""
        where_clauses: list[str] = []
        params: list[Any] = []

        if agent_name:
            where_clauses.append("agent_name = ?")
            params.append(agent_name)
        if caller:
            where_clauses.append("caller = ?")
            params.append(caller)
        if caller_id:
            where_clauses.append("caller_id = ?")
            params.append(caller_id)
        if llm_model:
            where_clauses.append("llm_model = ?")
            params.append(llm_model)
        if created_at_from:
            where_clauses.append("created_at >= ?")
            params.append(created_at_from)
        if created_at_to:
            where_clauses.append("created_at <= ?")
            params.append(created_at_to)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        row = self.db.fetchone(
            f"SELECT COUNT(*) AS count FROM agent_traces {where_sql}",
            tuple(params),
        )
        total = int(row["count"]) if row else 0
        logger.debug("event=agent_trace.count_completed total=%s", total)
        return total

    def count_by_agent_name(self) -> dict[str, int]:
        """按 agent_name 分组统计 trace 数量."""
        rows = self.db.fetchall(
            """
            SELECT agent_name, COUNT(*) AS count
            FROM agent_traces
            GROUP BY agent_name
            ORDER BY count DESC
            """,
        )
        return {row["agent_name"]: int(row["count"]) for row in rows}
