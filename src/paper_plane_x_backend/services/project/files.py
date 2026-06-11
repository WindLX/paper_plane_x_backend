"""Project sandbox file service.

集中管理项目文件沙箱的路径校验、文件操作和生命周期。
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal, cast

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.pandoc import (
    ExportFormat,
    convert_markdown,
    get_content_type,
    get_extension,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".toml"}
)
SUPPORTED_EXPORT_FORMATS: frozenset[str] = frozenset(
    {"markdown", "docx", "pdf", "html"}
)
_PROJECT_FILE_ACTIONS: frozenset[str] = frozenset(
    {"replace", "insert_before", "insert_after", "delete"}
)


class ProjectFileError(Exception):
    """Project file service error."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ProjectFileExportResult:
    """Single project-file export result."""

    content: bytes
    content_type: str
    download_name: str


class ProjectFileManager:
    """Manage project sandbox files and directories."""

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
            if suffix not in ALLOWED_EXTENSIONS:
                allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
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
    ) -> Path:
        """Resolve and validate a file path inside a project sandbox."""
        return self._resolve_path(
            project_id,
            file_path,
            allow_root=False,
            allow_missing=allow_missing,
            enforce_extension=True,
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

    def _read_text_file(self, project_id: str, file_path: str) -> tuple[Path, str]:
        target = self.resolve_file_path(project_id, file_path, allow_missing=False)
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
                size = child.stat().st_size if child_is_file else None
            except OSError:
                size = None
            items.append({"name": child.name, "is_dir": is_dir, "size": size})
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
            return {"file_path": file_path, "bytes_written": 0, "is_dir": True}

        target = self.resolve_file_path(project_id, file_path, allow_missing=True)
        if target.exists() and target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
        bytes_written = self._write_text_file(target, content, file_path)
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
        """Write binary content to a sandbox file."""
        self._ensure_max_size(len(content), file_path)
        target = self.resolve_file_path(project_id, file_path, allow_missing=True)
        if target.exists() and target.is_dir():
            raise ProjectFileError(
                "path_is_directory",
                f"Path is a directory: {file_path}",
                400,
            )
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
        return {"file_path": file_path, "bytes_written": len(content), "is_dir": False}

    def remove_path(self, project_id: str, file_path: str) -> dict[str, object]:
        """Remove a file or an empty directory from the sandbox."""
        target = self.resolve_file_path(project_id, file_path, allow_missing=False)
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
        """Export a markdown file to the requested format."""
        fmt = output_format.lower()
        if fmt not in SUPPORTED_EXPORT_FORMATS:
            supported = ", ".join(sorted(SUPPORTED_EXPORT_FORMATS))
            raise ProjectFileError(
                "unsupported_export_format",
                f"Unsupported format: {output_format}. Supported: {supported}",
                400,
            )
        export_format = cast(ExportFormat, fmt)
        target, content = self._read_text_file(project_id, file_path)
        file_name = target.stem
        try:
            output_bytes = (
                content.encode("utf-8")
                if export_format == "markdown"
                else convert_markdown(content, export_format, title=file_name)
            )
        except RuntimeError as exc:
            raise ProjectFileError("export_failed", str(exc), 500) from exc
        return ProjectFileExportResult(
            content=output_bytes,
            content_type=get_content_type(export_format),
            download_name=f"{file_name}.{get_extension(export_format)}",
        )

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


def get_project_file_manager() -> ProjectFileManager:
    """Return the process-wide project file manager singleton."""
    global _project_file_manager
    if _project_file_manager is None:
        _project_file_manager = ProjectFileManager()
    return _project_file_manager
