from enum import Enum


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class PaperSortKey(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    TITLE = "title"


class ProjectSortKey(str, Enum):
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"
    NAME = "name"


class TaskSortKey(str, Enum):
    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    STATUS = "status"


class AgentTraceSortKey(str, Enum):
    CREATED_AT = "created_at"
    AGENT_NAME = "agent_name"
    LLM_MODEL = "llm_model"
    TOTAL_TOKENS = "total_tokens"
