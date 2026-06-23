"""PaperParser tests."""

from datetime import datetime
from pathlib import Path

import pytest

from paper_plane_x_backend.models import Project
from paper_plane_x_backend.services.paper.parser import PaperParser, PaperParserError
from paper_plane_x_backend.services.paper.repository import PaperRepository
from paper_plane_x_backend.services.pdf_parser.base import PdfParseResult


class _FakePdfParser:
    async def parse_pdf(  # type: ignore[no-untyped-def]
        self, file_path: Path, output_md_name: str, save_dir: Path
    ) -> PdfParseResult:
        _ = file_path, output_md_name, save_dir
        return PdfParseResult(md_content="# parsed", image_paths=[Path("/tmp/a.png")])


@pytest.mark.asyncio
async def test_prepare_inputs_uses_existing_markdown(db) -> None:
    repo = PaperRepository(db)
    now = datetime.now()
    project = Project(
        project_id="proj-parser-1",
        name="parser-test",
        description=None,
        created_at=now,
        updated_at=now,
        operation_logs=[],
    )
    db.insert("projects", project.to_db_dict())

    paper = repo.create(md_content="# existing", images_paths=["/tmp/old.png"])
    repo.link_to_project(paper.paper_id, project.project_id)

    parser = PaperParser(pdf_parser=_FakePdfParser())  # type: ignore[arg-type]
    md_content, image_paths = await parser.prepare_inputs(
        paper_id=paper.paper_id,
        paper=paper,
        pdf_path=None,
    )

    assert md_content == "# existing"
    assert [str(p) for p in image_paths] == ["/tmp/old.png"]


@pytest.mark.asyncio
async def test_prepare_inputs_requires_pdf_when_no_markdown(db) -> None:
    repo = PaperRepository(db)
    paper = repo.create(md_content="", images_paths=[])
    parser = PaperParser(pdf_parser=_FakePdfParser())  # type: ignore[arg-type]

    with pytest.raises(PaperParserError):
        await parser.prepare_inputs(
            paper_id=paper.paper_id,
            paper=paper,
            pdf_path=None,
        )


def test_load_images_base64_encodes_png(tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"fake-image-bytes")

    values = PaperParser.load_images_base64([img])

    assert len(values) == 1
    assert values[0].startswith("data:image/png;base64,")
