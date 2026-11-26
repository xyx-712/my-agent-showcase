"""Coordinated consistent backup and offline rollback-capable restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from src.server.coordination import maintenance, maintenance_action, require_offline


def database_paths():
    from src.config import MEMORY_DB, CHECKPOINT_DB
    from src.server.session import APP_DB
    return {"app.db": Path(APP_DB).resolve(), "memory.db": Path(MEMORY_DB).resolve(),
            "checkpoints.db": Path(CHECKPOINT_DB).resolve()}


def restore_marker():
    return database_paths()["app.db"].with_name("restore_pending.json")


def require_complete_restore():
    if restore_marker().exists():
        raise RuntimeError("检测到未完成恢复，请停止服务并用原备份重新执行 restore --confirm-restore")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_database(source, destination):
    original = sqlite3.connect(source)
    copied = sqlite3.connect(destination)
    try:
        original.backup(copied)
        if copied.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("数据库完整性检查失败")
    finally:
        copied.close()
        original.close()


def backup(destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("备份目标目录已存在，请使用新目录")
    destination.parent.mkdir(parents=True, exist_ok=True)
    require_complete_restore()
    with maintenance() as owner, tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staging = Path(tmp) / "snapshot"
        staging.mkdir()
        files = {}
        missing = [name for name, source in database_paths().items() if not source.is_file()]
        if missing:
            raise ValueError("数据库不完整，请先成功启动后端再备份：" + ", ".join(missing))
        for name, source in database_paths().items():
            if source.exists():
                copy_database(source, staging / name)
                files[name] = digest(staging / name)
        from src.server.history import HISTORY_FILE
        if HISTORY_FILE.exists():
            shutil.copyfile(HISTORY_FILE, staging / "legacy-history.json")
            files["legacy-history.json"] = digest(staging / "legacy-history.json")
        (staging / "manifest.json").write_text(json.dumps({"format": 1, "files": files}, indent=2), encoding="utf-8")
        maintenance_action(owner, lambda: os.replace(staging, destination))
    return {"directory": str(destination), "files": list(files)}


def restore(source, confirm=False):
    if not confirm:
        raise ValueError("恢复会覆盖当前数据库，需传入 --confirm-restore")
    source = Path(source).resolve()
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    paths = database_paths()
    allowed = {*paths, "legacy-history.json"}
    if manifest.get("format") != 1 or not set(manifest["files"]) <= allowed:
        raise ValueError("备份格式无效")
    if not set(paths) <= set(manifest["files"]):
        raise ValueError("恢复需要包含三个数据库的完整备份")
    for name, checksum in manifest["files"].items():
        if digest(source / name) != checksum:
            raise ValueError("备份校验和不匹配")
    with maintenance() as owner, tempfile.TemporaryDirectory() as tmp:
        require_offline()
        rollback = Path(tmp)
        existing = {}
        for name, target in paths.items():
            if target.exists():
                copy_database(target, rollback / name)
                existing[name] = True
        def replace_database(snapshot, target):
            target.parent.mkdir(parents=True, exist_ok=True)
            pending = target.with_name(target.name + ".restore-" + os.urandom(6).hex())
            try:
                copy_database(snapshot, pending)
                for suffix in ("-wal", "-shm", "-journal"):
                    target.with_name(target.name + suffix).unlink(missing_ok=True)
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
        marker = restore_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"source": str(source), "files": manifest["files"]}), encoding="utf-8")
        try:
            for name, target in paths.items():
                maintenance_action(owner, lambda n=name, t=target: replace_database(source / n, t))
        except Exception:
            maintenance_action(owner, lambda: None)
            for name, target in paths.items():
                if existing.get(name):
                    maintenance_action(owner, lambda n=name, t=target: replace_database(rollback / n, t))
                else:
                    maintenance_action(owner, lambda t=target: t.unlink(missing_ok=True))
            marker.unlink(missing_ok=True)
            raise
        def revoke_restored_tokens():
            db = sqlite3.connect(paths["app.db"])
            try:
                with db:
                    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "rag_indexes" in tables:
                        # Vectors are derived, not part of the SQLite snapshot: require a new generation.
                        db.execute("DELETE FROM rag_indexes")
                        if "rag_cleanup" in tables:
                            db.execute("DELETE FROM rag_cleanup")
                    for table in ("sessions", "account_tokens"):
                        if table in tables:
                            db.execute(f"DELETE FROM {table}")
            finally:
                db.close()
        maintenance_action(owner, revoke_restored_tokens)
        marker.unlink(missing_ok=True)
    return {"restored": list(paths), "legacy_history": "旧 JSON 仅保留在备份中；迁移后的聊天以 app.db 为准"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("directory")
    parser.add_argument("--confirm-restore", action="store_true")
    args = parser.parse_args()
    result = backup(args.directory) if args.action == "backup" else restore(args.directory, args.confirm_restore)
    print(json.dumps(result, ensure_ascii=False))
