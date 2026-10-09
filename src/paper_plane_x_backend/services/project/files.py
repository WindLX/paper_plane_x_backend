"""Project sandbox file service.

集中管理项目文件沙箱的路径校验、文件操作和生命周期。
"""

from __future__ import annotations

import logging
import posixpath
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterable, Literal, cast
from urllib.parse import unquote, urlsplit

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.pandoc import (
    ExportFormat,
    ExportResourceMarkupError,
    collect_image_references,
    convert_markdown,
    get_content_type,
    get_extension,
    rewrite_image_references,
)
from paper_plane_x_backend.services.project.images import (
    IMAGE_CONTENT_TYPES,
    IMAGE_EXTENSIONS,
    ImageValidationError,
    image_content_type,
    is_image_extension,
    raster_to_png,
    svg_to_png,
    validate_image,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from paper_plane_x_backend.services.database import Database
    from paper_plane_x_backend.services.project.activity import ProjectActivityStore

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".toml"}
)
UPLOAD_EXTENSIONS: frozenset[str] = ALLOWED_EXTENSIONS | IMAGE_EXTENSIONS
SUPPORTED_EXPORT_FORMATS: frozenset[str] = frozenset(
    {"markdown", "docx", "pdf", "html"}
)
_DOWNLOAD_CONTENT_TYPES: dict[str, str] = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".json": "application/json",
    ".csv": "text/csv",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".toml": "application/toml",
    **IMAGE_CONTENT_TYPES,
}
_PROJECT_FILE_ACTIONS: frozenset[str] = frozenset(
    {"replace", "insert_before", "insert_after", "delete"}
)
_CONVERTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset({".webp", ".gif", ".svg"})
_SELF_CONTAINED_REFERENCE_PREFIX = "data:"


class ProjectFileError(Exception):
    """Project file service error."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


@dataclass(frozen=True)
class ProjectFileExportResult:
    """Single project-file export result."""

    content: bytes
    content_type: str
    download_name: str


@dataclass(frozen=True)
class ProjectFileDownloadResult:
    """Single project-file raw attachment download result."""

    content: bytes
    content_type: str
    download_name: str


@dataclass(frozen=True)
class _ExportResource:
    """导出时需要暂存到临时目录的资源。"""

    staged_relative_path: str
    content: bytes


@dataclass(frozen=True)
class _ExportPlan:
    """导出资源暂存计划。"""

    resources: list[_ExportResource]
    replacements: dict[str, str]


class ProjectFileManager:
    """Manage project sandbox files and directories."""

    def __init__(self, activity_store: ProjectActivityStore | None = None) -> None:
        self.activity_store = activity_store

    def _record_change(
        self,
        project_id: str,
        file_path: str,
        event_type: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        if self.activity_store is not None:
            self.activity_store.record(
                project_id=project_id,
                category="file",
                event_type=event_type,
                status="completed",
                object_name=Path(file_path).name,
                file_path=file_path,
                detail=detail,
            )

    def projects_root(self) -> Path:
        """Return the root directory containing all project sandboxes."""
        return (settings.data_dir / "projects").expanduser().absolute()

    def _sandbox_candidate(self, project_id: str) -> Path:
        if not project_id:
            raise ProjectFileError(
                "invalid_project_id",
                "project_id is required",
                400,
            )
        if project_id in {".", ".."} or "/" in project_id or "\\" in project_id:
            raise ProjectFileError(
                "invalid_project_id",
                f"Invalid project_id: {project_id}",
                400,
            )
        return self.projects_root() / project_id

    def sandbox_root(self, project_id: str) -> Path:
        """Return the validated sandbox root for a project."""
        root = self.projects_root()
        root.mkdir(parents=True, exist_ok=True)
        candidate = self._sandbox_candidate(project_id)
        if candidate.exists() and candidate.is_symlink():
            raise ProjectFileError(
                "invalid_sandbox_root",
                f"Project sandbox is a symlink: {project_id}",
                500,
            )
        resolved = candidate.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ProjectFileError(
                "invalid_sandbox_root",
                f"Project sandbox escapes projects root: {project_id}",
                500,
            ) from exc
        return resolved

    def ensure_project_sandbox(self, project_id: str) -> Path:
        """Create the sandbox directory for a project if missing."""
        root = self.sandbox_root(project_id)
        if root.exists() and not root.is_dir():
            raise ProjectFileError(
                "sandbox_not_directory",
                f"Project sandbox is not a directory: {project_id}",
                500,
            )
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ProjectFileError(
                "sandbox_create_failed",
                f"Failed to create project sandbox: {exc}",
                500,
            ) from exc
        return root

    def ensure_project_sandboxes(self, project_ids: Iterable[str]) -> int:
        """Ensure sandbox directories for a collection of projects.

        Returns the number of project IDs processed.
        """
        count = 0
        for project_id in project_ids:
            self.ensure_project_sandbox(project_id)
            count += 1
        return count

    def delete_project_sandbox(self, project_id: str) -> bool:
        """Remove a project's sandbox recursively.

        Missing sandboxes are treated as successful no-ops.
        """
        root = self.sandbox_root(project_id)
        if not root.exists():
            return False
        if not root.is_dir():
            raise ProjectFileError(
                "sandbox_not_directory",
                f"Project sandbox is not a directory: {project_id}",
                500,
            )
        try:
            shutil.rmtree(root)
        except OSError as exc:
            raise ProjectFileError(
                "sandbox_delete_failed",
                f"Failed to delete project sandbox: {exc}",
                500,
            ) from exc
        return True

    def _clean_relative_path(
        self,
        raw_path: str,
        *,
        allow_root: bool,
        label: str,
    ) -> str:
        clean_path = raw_path.lstrip("/")
        if not clean_path:
            if allow_root:
                return ""
            raise ProjectFileError(
                "invalid_path",
                f"{label} cannot be empty",
                400,
            )
        if ".." in Path(clean_path).parts:
            raise ProjectFileError(
                "path_traversal",
                f"Path traversal not allowed: {raw_path}",
                400,
            )
        return clean_path

    def _resolve_path(
        self,
        project_id: str,
        raw_path: str,
        *,
        allow_root: bool,
        allow_missing: bool,
        enforce_extension: bool,
        allowed_extensions: frozenset[str],
        is_dir: bool,
        label: str,
    ) -> Path:
        clean_path = self._clean_relative_path(
            raw_path,
            allow_root=allow_root,
            label=label,
        )
        root = self.sandbox_root(project_id)
        target = (root / clean_path).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ProjectFileError(
                "path_escapes_sandbox",
                f"Path escapes sandbox: {raw_path}",
                400,
            ) from exc

        if target.exists() and target.is_dir():
            return target

        if enforce_extension and not is_dir:
            suffix = target.suffix.lower()
            if suffix not in allowed_extensions:
                allowed = ", ".join(sorted(allowed_extensions))
                raise ProjectFileError(
                    "invalid_extension",
                    f"File extension '{target.suffix}' not allowed. Allowed: {allowed}",
                    400,
                )

        if not allow_missing and not target.exists():
            missing_kind = "Directory" if label == "dir_path" else "File"
            raise ProjectFileError(
                "not_found",
                f"{missing_kind} not found: {raw_path}",
                404,
            )
        return target

    def resolve_file_path(
        self,
        project_id: str,
        file_path: str,
        *,
        allow_missing: bool = True,
        is_dir: bool = False,
        allowed_extensions: frozenset[str] = ALLOWED_EXTENSIONS,
    ) -> Path:
        """Resolve and validate a file path inside a project sandbox.

        默认只接受文本扩展名；图片等上传类型需要显式传入 ``UPLOAD_EXTENSIONS``。
        """
        return self._resolve_path(
            project_id,
            file_path,
            allow_root=False,
            allow_missing=allow_missing,
            enforce_extension=True,
            allowed_extensions=allowed_extensions,
            is_dir=is_dir,
            label="file_path",
        )

    def resolve_dir_path(
        self,
        project_id: str,
        dir_path: str = "/",
        *,
        allow_missing: bool = True,
    ) -> Path:
        """Resolve and validate a directory path inside a project sandbox."""
        return self._resolve_path(
            project_id,
            dir_path,
            allow_root=True,
            allow_missing=allow_missing,
            enforce_extension=False,
            allowed_extensions=ALLOWED_EXTENSIONS,
            is_dir=True,
            label="dir_path",
        )

    def _ensure_max_size(self, size: int, path: str) -> None:
        if size > MAX_FILE_SIZE:
            raise ProjectFileError(
                "file_too_large",
                f"File too large (>{MAX_FILE_SIZE} bytes): {path}",
                413,
            )

    def _resolve_readable_file(
        self,
        project_id: str,
        file_path: str,
    ) -> Path:
        """解析可读文本文件；图片等二进制文件在文本接口上会被拒绝。"""
        target = self.resolve_file_path(
            project_id,
            file_path,
            allow_missing=False,
            allowed_extensions=UPLOAD_EXTENSIONS,
        )
        if target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
        if is_image_extension(target.suffix):
            raise ProjectFileError(
                "not_text_file",
                f"Image files cannot be read as text: {file_path}",
                400,
            )
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise ProjectFileError(
                "stat_failed",
                f"Failed to stat file: {file_path}",
                500,
            ) from exc
        self._ensure_max_size(size, file_path)
        return target

    def _read_text_file(self, project_id: str, file_path: str) -> tuple[Path, str]:
        target = self._resolve_readable_file(project_id, file_path)
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectFileError(
                "decode_failed",
                f"File is not valid UTF-8 text: {file_path}",
                400,
            ) from exc
        except OSError as exc:
            raise ProjectFileError(
                "read_failed",
                f"Failed to read file: {file_path}",
                500,
            ) from exc
        return target, content

    def download_file(
        self,
        project_id: str,
        file_path: str,
    ) -> ProjectFileDownloadResult:
        """Read a sandbox file as raw bytes for attachment download.

        与文本读取不同，这里不做 UTF-8 解码，保证下载字节与磁盘内容一致。
        """
        target = self._resolve_downloadable_file(project_id, file_path)
        suffix = target.suffix.lower()
        content_type = _DOWNLOAD_CONTENT_TYPES.get(suffix)
        if content_type is None:
            raise ProjectFileError(
                "unsupported_content_type",
                f"No download content type for extension: {suffix}",
                500,
            )
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise ProjectFileError(
                "read_failed",
                f"Failed to read file: {file_path}",
                500,
            ) from exc
        return ProjectFileDownloadResult(
            content=content,
            content_type=content_type,
            download_name=target.name,
        )

    def preview_image(
        self,
        project_id: str,
        file_path: str,
    ) -> ProjectFileDownloadResult:
        """读取图片用于内联预览，返回按真实内容判定的 MIME 类型。"""
        target = self._resolve_downloadable_file(project_id, file_path)
        suffix = target.suffix.lower()
        if not is_image_extension(suffix):
            raise ProjectFileError(
                "not_an_image",
                f"Preview only supports image files: {file_path}",
                400,
            )
        try:
            content = target.read_bytes()
        except OSError as exc:
            raise ProjectFileError(
                "read_failed",
                f"Failed to read file: {file_path}",
                500,
            ) from exc
        self._validate_image_bytes(suffix, content, file_path)
        content_type = _DOWNLOAD_CONTENT_TYPES.get(suffix)
        if content_type is None:
            raise ProjectFileError(
                "invalid_image_content",
                f"File content is not a recognized image: {file_path}",
                400,
            )
        return ProjectFileDownloadResult(
            content=content,
            content_type=content_type,
            download_name=target.name,
        )

    def _resolve_downloadable_file(self, project_id: str, file_path: str) -> Path:
        """解析允许上传的任意沙箱文件（文本或图片）。"""
        target = self.resolve_file_path(
            project_id,
            file_path,
            allow_missing=False,
            allowed_extensions=UPLOAD_EXTENSIONS,
        )
        if target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
        try:
            size = target.stat().st_size
        except OSError as exc:
            raise ProjectFileError(
                "stat_failed",
                f"Failed to stat file: {file_path}",
                500,
            ) from exc
        self._ensure_max_size(size, file_path)
        return target

    def _validate_image_bytes(
        self, extension: str, content: bytes, file_path: str
    ) -> None:
        try:
            validate_image(extension, content)
        except ImageValidationError as exc:
            raise ProjectFileError(
                exc.code,
                f"{exc.message}: {file_path}",
                exc.status_code,
            ) from exc

    def _write_text_file(self, target: Path, content: str, display_path: str) -> int:
        encoded = content.encode("utf-8")
        self._ensure_max_size(len(encoded), display_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ProjectFileError(
                "write_failed",
                f"Failed to write file: {display_path}",
                500,
            ) from exc
        return len(encoded)

    def list_files(self, project_id: str, dir_path: str = "/") -> dict[str, object]:
        """List direct children in a sandbox directory."""
        target = self.resolve_dir_path(project_id, dir_path, allow_missing=False)
        if not target.is_dir():
            raise ProjectFileError(
                "path_not_directory",
                f"Path is not a directory: {dir_path}",
                400,
            )

        items: list[dict[str, object]] = []
        try:
            children = sorted(target.iterdir())
        except OSError as exc:
            raise ProjectFileError(
                "list_failed",
                f"Failed to list directory: {dir_path}",
                500,
            ) from exc
        for child in children:
            is_symlink = child.is_symlink()
            child_is_file = child.is_file() if not is_symlink else False
            is_dir = child.is_dir() if not is_symlink else False
            try:
                stat_result = child.stat()
            except OSError:
                stat_result = None
            size = (
                stat_result.st_size
                if stat_result is not None and child_is_file
                else None
            )
            modified_at = (
                datetime.fromtimestamp(stat_result.st_mtime, tz=UTC).isoformat()
                if stat_result is not None
                else None
            )
            suffix = child.suffix.lower()
            if is_dir:
                kind = "directory"
                content_type = None
            elif is_image_extension(suffix):
                kind = "image"
                content_type = image_content_type(suffix)
            else:
                kind = "text"
                content_type = _DOWNLOAD_CONTENT_TYPES.get(suffix)
            items.append(
                {
                    "name": child.name,
                    "is_dir": is_dir,
                    "size": size,
                    "kind": kind,
                    "content_type": content_type,
                    "modified_at": modified_at,
                }
            )
        return {"items": items}

    def read_file(self, project_id: str, file_path: str) -> dict[str, object]:
        """Read a UTF-8 text file from a project sandbox."""
        _, content = self._read_text_file(project_id, file_path)
        return {"file_path": file_path, "content": content}

    def write_file(
        self,
        project_id: str,
        file_path: str,
        content: str,
        *,
        is_dir: bool = False,
    ) -> dict[str, object]:
        """Write a text file or create a directory in a project sandbox."""
        if is_dir:
            target = self.resolve_dir_path(project_id, file_path, allow_missing=True)
            existed = target.exists()
            if target.exists() and not target.is_dir():
                raise ProjectFileError(
                    "path_not_directory",
                    f"Path is not a directory: {file_path}",
                    400,
                )
            try:
                target.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ProjectFileError(
                    "directory_create_failed",
                    f"Failed to create directory: {file_path}",
                    500,
                ) from exc
            logger.info(
                "event=project_file.write project_id=%s file_path=%s bytes=%s is_dir=%s",
                project_id,
                file_path,
                0,
                True,
            )
            if not existed:
                self._record_change(project_id, file_path, "directory_created")
            return {"file_path": file_path, "bytes_written": 0, "is_dir": True}

        target = self.resolve_file_path(project_id, file_path, allow_missing=True)
        if target.exists() and target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
        bytes_written = self._write_text_file(target, content, file_path)
        self._record_change(
            project_id, file_path, "file_written", {"bytes_written": bytes_written}
        )
        logger.info(
            "event=project_file.write project_id=%s file_path=%s bytes=%s is_dir=%s",
            project_id,
            file_path,
            bytes_written,
            False,
        )
        return {"file_path": file_path, "bytes_written": bytes_written, "is_dir": False}

    def write_bytes(
        self,
        project_id: str,
        file_path: str,
        content: bytes,
    ) -> dict[str, object]:
        """Write binary content to a sandbox file.

        文本扩展名按原样保存；图片扩展名先按真实内容校验，再原样落盘。
        """
        self._ensure_max_size(len(content), file_path)
        target = self.resolve_file_path(
            project_id,
            file_path,
            allow_missing=True,
            allowed_extensions=UPLOAD_EXTENSIONS,
        )
        if target.exists() and target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
        suffix = target.suffix.lower()
        if is_image_extension(suffix):
            self._validate_image_bytes(suffix, content, file_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        except OSError as exc:
            raise ProjectFileError(
                "write_failed",
                f"Failed to write file: {file_path}",
                500,
            ) from exc
        logger.info(
            "event=project_file.upload project_id=%s file_path=%s bytes=%s",
            project_id,
            file_path,
            len(content),
        )
        self._record_change(
            project_id, file_path, "file_uploaded", {"bytes_written": len(content)}
        )
        return {"file_path": file_path, "bytes_written": len(content), "is_dir": False}

    def remove_path(self, project_id: str, file_path: str) -> dict[str, object]:
        """Remove a file or an empty directory from the sandbox."""
        target = self.resolve_file_path(
            project_id,
            file_path,
            allow_missing=False,
            allowed_extensions=UPLOAD_EXTENSIONS,
        )
        if target.is_dir():
            try:
                target.rmdir()
            except OSError as exc:
                raise ProjectFileError(
                    "directory_not_empty",
                    f"Directory is not empty: {file_path}",
                    400,
                ) from exc
            logger.info(
                "event=project_file.delete project_id=%s file_path=%s",
                project_id,
                file_path,
            )
            self._record_change(project_id, file_path, "directory_deleted")
            return {"removed": file_path}

        try:
            target.unlink()
        except OSError as exc:
            raise ProjectFileError(
                "remove_failed",
                f"Failed to remove file: {file_path}",
                500,
            ) from exc
        logger.info(
            "event=project_file.delete project_id=%s file_path=%s",
            project_id,
            file_path,
        )
        self._record_change(project_id, file_path, "file_deleted")
        return {"removed": file_path}

    def read_file_lines(
        self,
        project_id: str,
        file_path: str,
        start_line: int,
        end_line: int | None = None,
    ) -> dict[str, object]:
        """Read a 1-based inclusive line range from a file."""
        _, content = self._read_text_file(project_id, file_path)
        lines = content.splitlines()
        total_lines = len(lines)
        resolved_end_line = end_line if end_line is not None else start_line
        if start_line < 1 or resolved_end_line < start_line:
            raise ProjectFileError("invalid_line_range", "Invalid line range", 400)
        if start_line > total_lines:
            raise ProjectFileError(
                "line_out_of_range",
                f"start_line out of range: {start_line} > {total_lines}",
                400,
            )

        selected: list[dict[str, object]] = []
        for index in range(start_line, min(resolved_end_line, total_lines) + 1):
            selected.append({"line_no": index, "text": lines[index - 1]})
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": min(resolved_end_line, total_lines),
            "total_lines": total_lines,
            "lines": selected,
        }

    def find_in_file(
        self,
        project_id: str,
        file_path: str,
        query: str,
        *,
        case_sensitive: bool = False,
        max_matches: int = 20,
    ) -> dict[str, object]:
        """Find text occurrences in a sandbox file."""
        if not query:
            raise ProjectFileError("empty_query", "query cannot be empty", 400)
        _, content = self._read_text_file(project_id, file_path)
        haystack_lines = content.splitlines()
        needle = query if case_sensitive else query.lower()
        total_matches = 0
        matches: list[dict[str, object]] = []

        for line_no, line in enumerate(haystack_lines, start=1):
            search_line = line if case_sensitive else line.lower()
            start = 0
            while True:
                index = search_line.find(needle, start)
                if index < 0:
                    break
                total_matches += 1
                if len(matches) < max_matches:
                    matches.append(
                        {
                            "line_no": line_no,
                            "start_col": index + 1,
                            "end_col": index + len(query),
                            "text": line,
                        }
                    )
                start = index + max(1, len(needle))

        return {
            "file_path": file_path,
            "query": query,
            "total_matches": total_matches,
            "matches": matches,
        }

    def replace_file_lines(
        self,
        project_id: str,
        file_path: str,
        start_line: int,
        end_line: int,
        new_text: str,
    ) -> dict[str, object]:
        """Replace a 1-based inclusive line range in a file."""
        target, content = self._read_text_file(project_id, file_path)
        lines = content.splitlines()
        total_lines = len(lines)
        if start_line < 1 or end_line < start_line:
            raise ProjectFileError("invalid_line_range", "Invalid line range", 400)
        if end_line > total_lines:
            raise ProjectFileError(
                "line_out_of_range",
                f"end_line out of range: {end_line} > {total_lines}",
                400,
            )

        replacement_lines = new_text.splitlines()
        updated_lines = [
            *lines[: start_line - 1],
            *replacement_lines,
            *lines[end_line:],
        ]
        updated_content = "\n".join(updated_lines)
        if content.endswith("\n"):
            updated_content += "\n"

        bytes_written = self._write_text_file(target, updated_content, file_path)
        self._record_change(
            project_id,
            file_path,
            "file_written",
            {"operation": "replace_lines", "bytes_written": bytes_written},
        )
        return {
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "lines_replaced": end_line - start_line + 1,
            "bytes_written": bytes_written,
        }

    def replace_file_text(
        self,
        project_id: str,
        file_path: str,
        old_text: str,
        new_text: str,
        *,
        replace_all: bool = False,
        expected_occurrences: int = 1,
    ) -> dict[str, object]:
        """Replace exact text in a file."""
        if not old_text:
            raise ProjectFileError("empty_old_text", "old_text cannot be empty", 400)
        if expected_occurrences < 1:
            raise ProjectFileError(
                "invalid_expected_occurrences",
                "expected_occurrences must be >= 1",
                400,
            )
        target, content = self._read_text_file(project_id, file_path)
        occurrences = content.count(old_text)
        if occurrences == 0:
            raise ProjectFileError("old_text_not_found", "old_text not found", 400)
        if not replace_all and occurrences != expected_occurrences:
            raise ProjectFileError(
                "occurrence_mismatch",
                (
                    f"Expected {expected_occurrences} occurrence(s), found {occurrences}. "
                    "Set replace_all=true or adjust expected_occurrences."
                ),
                400,
            )

        replacements = occurrences if replace_all else expected_occurrences
        updated_content = (
            content.replace(old_text, new_text)
            if replace_all
            else content.replace(old_text, new_text, expected_occurrences)
        )
        bytes_written = self._write_text_file(target, updated_content, file_path)
        self._record_change(
            project_id,
            file_path,
            "file_written",
            {"operation": "replace_text", "bytes_written": bytes_written},
        )
        return {
            "file_path": file_path,
            "replacements": replacements,
            "bytes_written": bytes_written,
        }

    def patch_file(
        self,
        project_id: str,
        file_path: str,
        action: str,
        anchor_text: str,
        content: str = "",
        *,
        expected_occurrences: int = 1,
    ) -> dict[str, object]:
        """Patch a file around an exact anchor text."""
        if not anchor_text:
            raise ProjectFileError(
                "empty_anchor_text",
                "anchor_text cannot be empty",
                400,
            )
        if action not in _PROJECT_FILE_ACTIONS:
            raise ProjectFileError(
                "invalid_action",
                "action must be one of: replace, insert_before, insert_after, delete",
                400,
            )
        if expected_occurrences < 1:
            raise ProjectFileError(
                "invalid_expected_occurrences",
                "expected_occurrences must be >= 1",
                400,
            )

        target, original = self._read_text_file(project_id, file_path)
        occurrences = original.count(anchor_text)
        if occurrences != expected_occurrences:
            raise ProjectFileError(
                "occurrence_mismatch",
                (
                    f"Expected {expected_occurrences} occurrence(s) of anchor_text, "
                    f"found {occurrences}"
                ),
                400,
            )

        typed_action = cast(
            Literal["replace", "insert_before", "insert_after", "delete"],
            action,
        )
        if typed_action == "replace":
            updated = original.replace(anchor_text, content, expected_occurrences)
        elif typed_action == "insert_before":
            updated = original.replace(
                anchor_text,
                f"{content}{anchor_text}",
                expected_occurrences,
            )
        elif typed_action == "insert_after":
            updated = original.replace(
                anchor_text,
                f"{anchor_text}{content}",
                expected_occurrences,
            )
        else:
            updated = original.replace(anchor_text, "", expected_occurrences)

        bytes_written = self._write_text_file(target, updated, file_path)
        self._record_change(
            project_id,
            file_path,
            "file_written",
            {"operation": "patch", "bytes_written": bytes_written},
        )
        return {
            "file_path": file_path,
            "action": action,
            "occurrences": occurrences,
            "bytes_written": bytes_written,
        }

    def export_markdown_file(
        self,
        project_id: str,
        file_path: str,
        output_format: str,
    ) -> ProjectFileExportResult:
        """Export a markdown file to the requested format.

        markdown 导出返回磁盘上的原始字节；其他格式先解析 markdown 与 HTML 中的图片引用，
        校验引用全部位于沙箱内且内容合法，再只把被引用的资源暂存到临时目录交给 pandoc。
        """
        fmt = output_format.lower()
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_EXPORT_FORMATS))
            raise ProjectFileError(
                "unsupported_export_format",
                f"Unsupported format: {output_format}. Supported: {supported}",
                400,
            )
        export_format = cast(ExportFormat, fmt)
        target = self._resolve_readable_file(project_id, file_path)
        try:
            raw_content = target.read_bytes()
        except OSError as exc:
            raise ProjectFileError(
                "read_failed",
                f"Failed to read file: {file_path}",
                500,
            ) from exc
        file_name = target.stem
        activity_id = None
        if self.activity_store is not None:
            activity_id = self.activity_store.record_pending(
                project_id=project_id,
                category="export",
                event_type="file_exported",
                object_name=target.name,
                file_path=file_path,
                detail={"format": export_format},
            )
        try:
            output_bytes = (
                raw_content
                if export_format == "markdown"
                else self._convert_markdown_export(
                    project_id,
                    target,
                    raw_content,
                    export_format,
                    file_name,
                )
            )
        except ProjectFileError as exc:
            if self.activity_store is not None and activity_id is not None:
                self.activity_store.fail(activity_id, error=exc.message)
            raise
        except (RuntimeError, ImageValidationError) as exc:
            if self.activity_store is not None and activity_id is not None:
                self.activity_store.fail(activity_id, error=str(exc))
            raise ProjectFileError("export_failed", str(exc), 500) from exc
        if self.activity_store is not None and activity_id is not None:
            self.activity_store.complete(activity_id, object_name=target.name)
        return ProjectFileExportResult(
            content=output_bytes,
            content_type=get_content_type(export_format),
            download_name=f"{file_name}.{get_extension(export_format)}",
        )

    def _convert_markdown_export(
        self,
        project_id: str,
        target: Path,
        raw_content: bytes,
        export_format: ExportFormat,
        file_name: str,
    ) -> bytes:
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProjectFileError(
                "decode_failed",
                f"File is not valid UTF-8 text: {target.name}",
                400,
            ) from exc
        root = self.sandbox_root(project_id)
        source_dir = (
            "" if target.parent == root else target.parent.relative_to(root).as_posix()
        )
        plan = self._plan_export_resources(root, source_dir, text, export_format)
        with tempfile.TemporaryDirectory() as tmpdir:
            workdir = Path(tmpdir)
            for resource in plan.resources:
                destination = workdir / resource.staged_relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(resource.content)
            rewritten = rewrite_image_references(text, plan.replacements)
            input_relative_path = (
                posixpath.join(source_dir, target.name) if source_dir else target.name
            )
            return convert_markdown(
                rewritten,
                export_format,
                title=file_name,
                workdir=workdir,
                input_relative_path=input_relative_path,
                embed_resources=export_format == "html",
            )

    def _plan_export_resources(
        self,
        root: Path,
        source_dir: str,
        text: str,
        export_format: ExportFormat,
    ) -> _ExportPlan:
        resources: dict[str, _ExportResource] = {}
        replacements: dict[str, str] = {}
        errors: list[dict[str, str]] = []
        convert_images = export_format in ("docx", "pdf")

        try:
            references = collect_image_references(text)
        except ExportResourceMarkupError as exc:
            raise ProjectFileError(
                "export_invalid_resources",
                "Only project images and self-contained styling can be included; upload external images first",
                400,
                details={
                    "references": [
                        {"reference": exc.reference, "reason": "unsupported_markup"}
                    ]
                },
            ) from exc
        for index, reference in enumerate(references):
            decoded = unquote(reference).strip()
            if not decoded or decoded.startswith(_SELF_CONTAINED_REFERENCE_PREFIX):
                continue
            if _is_external_reference(decoded):
                errors.append({"reference": reference, "reason": "external"})
                continue
            if not urlsplit(decoded).path:
                # 只有查询串或片段的引用不是项目内资源，保持原样即可。
                continue
            resolved_reference = _reference_logical_path(decoded, source_dir)
            if resolved_reference is None:
                errors.append(
                    {"reference": reference, "reason": "path_escapes_sandbox"}
                )
                continue
            logical, url_suffix = resolved_reference
            absolute = root / logical
            if absolute.is_symlink() or any(
                parent.is_symlink()
                for parent in absolute.parents
                if parent.is_relative_to(root)
            ):
                errors.append({"reference": reference, "reason": "symlink"})
                continue
            resolved_path = absolute.resolve()
            if not resolved_path.is_relative_to(root):
                errors.append(
                    {"reference": reference, "reason": "path_escapes_sandbox"}
                )
                continue
            if not resolved_path.is_file():
                errors.append({"reference": reference, "reason": "missing"})
                continue
            extension = Path(logical).suffix.lower()
            if not is_image_extension(extension):
                errors.append({"reference": reference, "reason": "unsupported_type"})
                continue
            try:
                size = resolved_path.stat().st_size
            except OSError:
                errors.append({"reference": reference, "reason": "unreadable"})
                continue
            if size > MAX_FILE_SIZE:
                errors.append({"reference": reference, "reason": "too_large"})
                continue
            try:
                content = resolved_path.read_bytes()
            except OSError:
                errors.append({"reference": reference, "reason": "unreadable"})
                continue
            try:
                validate_image(extension, content)
            except ImageValidationError as exc:
                errors.append(
                    {"reference": reference, "reason": f"invalid_image:{exc.code}"}
                )
                continue

            staged_logical = logical
            if convert_images and extension in _CONVERTED_IMAGE_EXTENSIONS:
                staged_logical = _converted_resource_path(logical, extension, index)
                content = _convert_resource_image(extension, content)

            resources[staged_logical] = _ExportResource(staged_logical, content)
            resolved_url = (
                posixpath.relpath(staged_logical, source_dir or ".") + url_suffix
            )
            if resolved_url != decoded:
                replacements[decoded] = resolved_url

        if errors:
            raise ProjectFileError(
                "export_invalid_resources",
                f"Export preflight found {len(errors)} unresolved image reference(s)",
                400,
                details={"references": errors},
            )
        return _ExportPlan(list(resources.values()), replacements)

    def collect_sandbox_files(self, project_id: str) -> list[tuple[Path, str]]:
        """Collect regular non-symlink sandbox files for project export."""
        root = self.sandbox_root(project_id)
        if not root.exists():
            return []
        if not root.is_dir():
            raise ProjectFileError(
                "sandbox_not_directory",
                f"Project sandbox is not a directory: {project_id}",
                500,
            )

        files: list[tuple[Path, str]] = []
        try:
            candidates = sorted(root.rglob("*"))
        except OSError as exc:
            raise ProjectFileError(
                "sandbox_scan_failed",
                f"Failed to scan project sandbox: {exc}",
                500,
            ) from exc
        for file_path in candidates:
            if file_path.is_symlink() or not file_path.is_file():
                continue
            relative_path = file_path.relative_to(root).as_posix()
            files.append((file_path, relative_path))
        return files


_project_file_manager: ProjectFileManager | None = None


def _is_external_reference(decoded: str) -> bool:
    """判断图片引用是否指向沙箱之外（http、file、协议相对地址等）。"""
    if decoded.startswith("//"):
        return True
    try:
        return bool(urlsplit(decoded).scheme)
    except ValueError:
        return True


def _reference_logical_path(decoded: str, source_dir: str) -> tuple[str, str] | None:
    """把图片引用解析为项目内相对路径，并保留查询串/片段后缀.

    根相对引用（``/assets/a.png``）以项目根为基准，其余引用以被导出 markdown 所在目录为基准；
    解析结果逃出项目根目录时返回 None。
    """
    path_part = urlsplit(decoded).path
    url_suffix = decoded[len(path_part) :]
    if path_part.startswith("/"):
        logical = posixpath.normpath(path_part.lstrip("/"))
    else:
        logical = posixpath.normpath(posixpath.join(source_dir, path_part))
    if not logical or logical == "." or logical.startswith("../"):
        return None
    return logical, url_suffix


def _converted_resource_path(logical: str, extension: str, index: int) -> str:
    """为需要转换的导出资源生成唯一的暂存相对路径。"""
    directory, _, name = logical.rpartition("/")
    stem = name[: -len(extension)] if name.lower().endswith(extension) else name
    converted = f"{stem}__ppx_{extension.lstrip('.')}_{index}.png"
    return f"{directory}/{converted}" if directory else converted


def _convert_resource_image(extension: str, content: bytes) -> bytes:
    """把导出用图片转换为 PNG：SVG 走 rsvg-convert，动图取首帧。"""
    if extension == ".svg":
        return svg_to_png(content)
    return raster_to_png(content)


def get_project_file_manager(db: Database | None = None) -> ProjectFileManager:
    """Return the process-wide project file manager singleton."""
    global _project_file_manager
    if db is not None:
        from paper_plane_x_backend.services.project.activity import ProjectActivityStore

        return ProjectFileManager(ProjectActivityStore(db))
    if _project_file_manager is None:
        _project_file_manager = ProjectFileManager()
    return _project_file_manager
