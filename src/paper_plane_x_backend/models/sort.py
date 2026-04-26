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
    STATUS = "status"
