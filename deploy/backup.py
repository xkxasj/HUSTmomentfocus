"""一致性备份：SQLite + 上传图片。

为什么不用直接复制 .db 文件：SQLite 在 WAL 模式下有 -wal/-shm 两个伴生文件，
运行中直接 cp 可能拿到「主库旧、WAL 新」的撕裂快照。`sqlite3.Connection.backup`
走的是 SQLite 官方的在线备份 API，会拿到一个自洽的快照。

用法（在仓库根目录）：
    python deploy/backup.py                    # 默认读环境变量/相对路径
    python deploy/backup.py --out D:/mouke-backups
    python deploy/backup.py --keep-days 30

容器内（镜像里已复制本脚本到 /app/backup.py）：
    docker compose --env-file .env.production -f deploy/docker-compose.yml exec backend \
        python backup.py --db /data/mouke.db --uploads /data/uploads --out /data/backups
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tarfile
import time
from datetime import datetime, timedelta
from pathlib import Path


def default_db() -> Path:
    return Path(os.getenv("MOUKE_DB_PATH", Path(__file__).resolve().parents[1] / "backend" / "app" / "mouke.db"))


def default_uploads() -> Path:
    return Path(os.getenv("MOUKE_UPLOAD_DIR", Path(__file__).resolve().parents[1] / "backend" / "app" / "uploads"))


def backup_database(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SystemExit(f"数据库不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 只读打开源库，避免备份动作反过来写生产库。
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src, \
            sqlite3.connect(destination) as dst:
        src.backup(dst)


def backup_uploads(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    with tarfile.open(destination, "w:gz") as archive:
        archive.add(source, arcname="uploads")


def prune(output_dir: Path, keep_days: int) -> None:
    cutoff = datetime.now() - timedelta(days=keep_days)
    for path in output_dir.glob("mouke-*"):
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="某刻数据备份")
    parser.add_argument("--db", type=Path, default=default_db())
    parser.add_argument("--uploads", type=Path, default=default_uploads())
    parser.add_argument("--out", type=Path, default=Path(os.getenv("MOUKE_BACKUP_DIR", "backups")))
    parser.add_argument("--keep-days", type=int, default=14)
    args = parser.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    db_target = args.out / f"mouke-{stamp}.db"
    uploads_target = args.out / f"mouke-uploads-{stamp}.tar.gz"

    backup_database(args.db, db_target)
    backup_uploads(args.uploads, uploads_target)
    prune(args.out, args.keep_days)

    print(f"数据库：{db_target} ({db_target.stat().st_size} bytes)")
    if uploads_target.exists():
        print(f"上传目录：{uploads_target} ({uploads_target.stat().st_size} bytes)")
    print("提醒：备份文件包含用户数据，请存放在加密磁盘，并定期做一次恢复演练。")


if __name__ == "__main__":
    main()
