"""API 请求/响应模型.

定义 REST API 的输入输出数据结构。
"""

from paper_plane_x_backend.schemas.api.common import ErrorResponse, MessageResponse
from paper_plane_x_backend.schemas.api.agent_trace import (
    AgentTraceQueryRequest,
    AgentTraceQueryResponse,
    AgentTraceResponse,
)
from paper_plane_x_backend.schemas.api.data_process import (
    DataProcessManualUpdateRequest,
    DataProcessRequest,
    DataProcessSubmitResponse,
    DataProcessTaskListResponse,
    DataProcessTaskResponse,
)
from paper_plane_x_backend.schemas.api.librarian import (
    LibrarianConditionGroup,
    LibrarianConditionPredicate,
    LibrarianMatrixRequest,
    LibrarianMatrixResponse,
    LibrarianProjectionRequest,
    LibrarianProjectionResponse,
    LibrarianUnifiedSearchRequest,
    LibrarianUnifiedSearchResponse,
)
from paper_plane_x_backend.schemas.api.paper import (
    PaperDetailResponse,
    PaperListResponse,
    PaperResponse,
)
from paper_plane_x_backend.schemas.api.project import (
    ProjectExportRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
)

__all__ = [
    "AgentTraceQueryRequest",
    "AgentTraceQueryResponse",
    "AgentTraceResponse",
    "DataProcessManualUpdateRequest",
    "DataProcessRequest",
    "DataProcessSubmitResponse",
    "DataProcessTaskListResponse",
    "DataProcessTaskResponse",
    "ErrorResponse",
    "LibrarianConditionGroup",
    "LibrarianConditionPredicate",
    "LibrarianMatrixRequest",
    "LibrarianMatrixResponse",
    "LibrarianProjectionRequest",
    "LibrarianProjectionResponse",
    "LibrarianUnifiedSearchRequest",
    "LibrarianUnifiedSearchResponse",
    "MessageResponse",
    "PaperDetailResponse",
    "PaperListResponse",
    "PaperResponse",
    "ProjectCreateRequest",
    "ProjectExportRequest",
    "ProjectListResponse",
    "ProjectResponse",
    "ProjectUpdateRequest",
]
