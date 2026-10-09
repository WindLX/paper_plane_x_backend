"""真实本地转换用例：验证项目 markdown 导出的暂存、路径改写与资源嵌入.

这些用例直接调用系统 pandoc（以及 rsvg-convert、PDF engine），本机缺少对应工具时跳过。
"""

import shutil
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.project.files import ProjectFileManager

_PDF_ENGINES = (
    "typst",
    "weasyprint",
    "wkhtmltopdf",
    "pagedjs-cli",
    "prince",
    "xelatex",
    "pdflatex",
    "lualatex",
    "tectonic",
)

pytestmark = pytest.mark.skipif(
    shutil.which("pandoc") is None,
    reason="pandoc is not installed",
)


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (30, 90, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def _webp_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (200, 90, 30)).save(buffer, format="WEBP")
    return buffer.getvalue()


def _gif_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), (30, 200, 90)).save(buffer, format="GIF")
    return buffer.getvalue()


_STATIC_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8">'
    '<circle cx="4" cy="4" r="3" fill="red"/></svg>'
).encode()


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectFileManager:
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    return ProjectFileManager()


@pytest.fixture
def sandbox(manager: ProjectFileManager) -> Path:
    return manager.ensure_project_sandbox("proj-1")


def test_html_export_embeds_referenced_images(
    manager: ProjectFileManager,
    sandbox: Path,
) -> None:
    (sandbox / "images").mkdir()
    (sandbox / "images" / "figure.png").write_bytes(_png_bytes())
    (sandbox / "images" / "diagram.svg").write_bytes(_STATIC_SVG)
    manager.write_file(
        "proj-1",
        "/notes/draft.md",
        "![figure](../images/figure.png)\n\n![diagram](../images/diagram.svg)\n",
    )

    result = manager.export_markdown_file("proj-1", "/notes/draft.md", "html")

    html = result.content.decode("utf-8")
    assert "data:image/png;base64," in html
    assert "data:image/svg+xml;base64," in html
    assert "../images/figure.png" not in html
    assert "../images/diagram.svg" not in html


def test_html_export_rewrites_root_relative_references(
    manager: ProjectFileManager,
    sandbox: Path,
) -> None:
    (sandbox / "assets").mkdir()
    (sandbox / "assets" / "a.png").write_bytes(_png_bytes())
    manager.write_file("proj-1", "/notes/draft.md", "![a](/assets/a.png)\n")

    result = manager.export_markdown_file("proj-1", "/notes/draft.md", "html")

    html = result.content.decode("utf-8")
    assert "data:image/png;base64," in html
    assert "/assets/a.png" not in html


def test_docx_export_converts_webp_gif_and_svg_to_png(
    manager: ProjectFileManager,
    sandbox: Path,
) -> None:
    if shutil.which("rsvg-convert") is None:
        pytest.skip("rsvg-convert is not installed")
    (sandbox / "picture.webp").write_bytes(_webp_bytes())
    (sandbox / "animation.gif").write_bytes(_gif_bytes())
    (sandbox / "icon.svg").write_bytes(_STATIC_SVG)
    manager.write_file(
        "proj-1",
        "/doc.md",
        "![w](picture.webp)\n\n![g](animation.gif)\n\n![s](icon.svg)\n",
    )

    result = manager.export_markdown_file("proj-1", "/doc.md", "docx")

    with zipfile.ZipFile(BytesIO(result.content)) as archive:
        media = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert len(media) == 3
        assert all(name.endswith(".png") for name in media)
        for name in media:
            assert archive.read(name).startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.skipif(
    all(shutil.which(engine) is None for engine in _PDF_ENGINES),
    reason="no pandoc PDF engine is installed",
)
def test_pdf_export_embeds_png(
    manager: ProjectFileManager,
    sandbox: Path,
) -> None:
    (sandbox / "figure.png").write_bytes(_png_bytes())
    manager.write_file("proj-1", "/doc.md", "# Report\n\n![f](figure.png)\n")

    result = manager.export_markdown_file("proj-1", "/doc.md", "pdf")

    assert result.content.startswith(b"%PDF")
    assert result.content_type == "application/pdf"


@pytest.mark.skipif(
    shutil.which("typst") is None or shutil.which("rsvg-convert") is None,
    reason="Typst or rsvg-convert is unavailable",
)
def test_pdf_export_uses_configured_typst_with_relative_svg(
    manager: ProjectFileManager, sandbox: Path
) -> None:
    from paper_plane_x_backend.services.app_settings import get_app_settings_repo

    repo = get_app_settings_repo()
    previous = repo.get().pandoc.pdf_engine
    repo.update_pandoc({"pdf_engine": shutil.which("typst")})
    (sandbox / "images").mkdir()
    (sandbox / "images" / "diagram.svg").write_bytes(_STATIC_SVG)
    manager.write_file(
        "proj-1", "/notes/doc.md", "# Report\n\n![Diagram](../images/diagram.svg)\n"
    )
    try:
        result = manager.export_markdown_file("proj-1", "/notes/doc.md", "pdf")
    finally:
        repo.update_pandoc({"pdf_engine": previous})
    assert result.content.startswith(b"%PDF")
