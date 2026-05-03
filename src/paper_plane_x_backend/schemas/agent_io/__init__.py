"""Agent I/O schemas."""

from paper_plane_x_backend.schemas.agent_io.base import (
    AssistantMessage,
    Citation,
    CitedText,
    SystemMessage,
    ToolCallMessage,
    UserMessage,
)
from paper_plane_x_backend.schemas.agent_io.data_processor import (
    ExtractionAgentOutput,
    ExtractionAgentUserInput,
    FactCheckAgentOutput,
    FactCheckAgentUserInput,
    FactCheckError,
    KeyResults,
    Methodology,
    QuickScan,
    ResearchGap,
    SynthesisData,
)
from paper_plane_x_backend.schemas.agent_io.librarian import (
    DeepDiverAgentInput,
    DeepDiverAgentOutput,
    GlobalFinderAgentInput,
    GlobalFinderAgentOutput,
    GlobalFinderPaperSummary,
    GlobalFinderStats,
    QueryBuilderAgentInput,
    QueryBuilderAgentOutput,
    TagCount,
    YearDistribution,
)

__all__ = [
    # Base schemas
    "Citation",
    "CitedText",
    "ToolCallMessage",
    "SystemMessage",
    "UserMessage",
    "AssistantMessage",
    # Data processor schemas
    "QuickScan",
    "ResearchGap",
    "Methodology",
    "KeyResults",
    "SynthesisData",
    "FactCheckError",
    "ExtractionAgentUserInput",
    "ExtractionAgentOutput",
    "FactCheckAgentUserInput",
    "FactCheckAgentOutput",
    # Librarian agent schemas
    "DeepDiverAgentInput",
    "DeepDiverAgentOutput",
    "GlobalFinderPaperSummary",
    "GlobalFinderStats",
    "GlobalFinderAgentInput",
    "GlobalFinderAgentOutput",
    "QueryBuilderAgentInput",
    "QueryBuilderAgentOutput",
    "YearDistribution",
    "TagCount",
]
