"""显式修复旧版本取消/失败任务留下的文献处理状态。"""

import argparse
from datetime import datetime
from pathlib import Path

from paper_plane_x_backend.config import settings
from paper_plane_x_backend.services.database import Database
from paper_plane_x_backend.services.paper.repository import PaperRepository


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=settings.database_path)
    parser.add_argument(
        "--apply", action="store_true", help="Back up the database and apply the repair"
    )
    args = parser.parse_args()
    database_path = args.database.resolve()
    if not database_path.is_file():
        parser.error("Database file does not exist")
    db = Database(database_path)
    repo = PaperRepository(db)
    count = repo.release_interrupted_processing(dry_run=True)
    print(f"interrupted_papers={count}")
    if not args.apply or not count:
        return

    backup_path = database_path.with_name(
        f"{database_path.name}.before-paper-repair-{datetime.now():%Y%m%d-%H%M%S-%f}.bak"
    )
    backup_path.touch(mode=0o600, exist_ok=False)
    with (
        db.get_connection() as source,
        Database(backup_path).get_connection() as backup,
    ):
        source.backup(backup)
    repaired = repo.release_interrupted_processing()
    print(f"backup={backup_path}")
    print(f"repaired_papers={repaired}")


if __name__ == "__main__":
    main()
