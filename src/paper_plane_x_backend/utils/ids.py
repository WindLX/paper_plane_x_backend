"""带前缀的 ID 生成工具.

所有业务 ID 均采用 {prefix}-{uuid_hex} 格式，便于人工识别和日志排查。
"""

from uuid import uuid4


def _generate_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def generate_paper_id() -> str:
    """生成 Paper ID，前缀 pap-."""
    return _generate_id("pap")


def generate_project_id() -> str:
    """生成 Project ID，前缀 prj-."""
    return _generate_id("prj")


def generate_task_id() -> str:
    """生成 Data Process Task ID，前缀 tsk-."""
    return _generate_id("tsk")


def generate_trace_id() -> str:
    """生成 Agent Trace ID，前缀 trc-."""
    return _generate_id("trc")
