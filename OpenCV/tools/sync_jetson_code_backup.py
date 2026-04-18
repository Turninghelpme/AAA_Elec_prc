from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import paramiko


PROJECT_ROOT = Path(r"D:\OpenCV")
BACKUP_ROOT = PROJECT_ROOT / "backups"
LOCAL_DRIVER_ARCHIVE = PROJECT_ROOT / "peak-linux-driver-8.17.0 (1).tar.gz"

JETSON_HOST = "192.168.19.123"
JETSON_USER = "jetson"
JETSON_PASSWORD = "jetson"
REMOTE_CODE_DIR = "/home/jetson/codex-install"

CODE_SUFFIXES = (
    ".py",
    ".cpp",
    ".c",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".sh",
    ".md",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
)


@dataclass
class SyncedFile:
    remote_path: str
    local_path: Path
    sha256: str
    size: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def list_remote_code_files(client: paramiko.SSHClient) -> list[str]:
    quoted_patterns = " -o ".join([f"-name '*{suffix}'" for suffix in CODE_SUFFIXES])
    command = (
        f"find {REMOTE_CODE_DIR} -maxdepth 1 -type f \\( {quoted_patterns} \\) | sort"
    )
    _, stdout, stderr = client.exec_command(command)
    paths = [line.strip() for line in stdout.read().decode("utf-8", "ignore").splitlines() if line.strip()]
    err = stderr.read().decode("utf-8", "ignore").strip()
    if err:
        raise RuntimeError(err)
    if not paths:
        raise RuntimeError("Jetson 上没有找到可同步的代码文件。")
    return paths


def write_snapshot_readme(snapshot_dir: Path, synced_files: list[SyncedFile]) -> None:
    lines = [
        "# Jetson 代码同步快照",
        "",
        f"- 创建时间：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        f"- Jetson：`{JETSON_USER}@{JETSON_HOST}`",
        f"- 远端目录：`{REMOTE_CODE_DIR}`",
        "",
        "## 已同步代码文件",
        "",
    ]
    for item in synced_files:
        lines.append(f"- `{item.remote_path}` -> `{item.local_path.name}`")

    if LOCAL_DRIVER_ARCHIVE.exists():
        lines.extend(
            [
                "",
                "## 同时保留的本地安装包",
                "",
                f"- `{LOCAL_DRIVER_ARCHIVE.name}`",
            ]
        )

    (snapshot_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(snapshot_dir: Path, synced_files: list[SyncedFile]) -> None:
    lines = [
        "# SHA256 Manifest",
        "",
    ]
    for item in synced_files:
        lines.append(f"{item.sha256}  tools\\{item.local_path.name}  <-  {item.remote_path}")
    if LOCAL_DRIVER_ARCHIVE.exists():
        lines.append(
            f"{sha256_file(LOCAL_DRIVER_ARCHIVE)}  {LOCAL_DRIVER_ARCHIVE.name}  <-  local archive"
        )
    (snapshot_dir / "manifest.sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def zip_snapshot(snapshot_dir: Path) -> Path:
    zip_path = snapshot_dir.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in snapshot_dir.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(snapshot_dir))
    return zip_path


def sync() -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    snapshot_dir = BACKUP_ROOT / f"{timestamp}-code-sync"
    tools_dir = snapshot_dir / "tools"
    ensure_dirs([BACKUP_ROOT, snapshot_dir, tools_dir])

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        JETSON_HOST,
        username=JETSON_USER,
        password=JETSON_PASSWORD,
        timeout=10,
    )

    try:
        remote_files = list_remote_code_files(client)
        sftp = client.open_sftp()
        try:
            synced_files: list[SyncedFile] = []
            for remote_path in remote_files:
                local_path = tools_dir / Path(remote_path).name
                sftp.get(remote_path, str(local_path))
                synced_files.append(
                    SyncedFile(
                        remote_path=remote_path,
                        local_path=local_path,
                        sha256=sha256_file(local_path),
                        size=local_path.stat().st_size,
                    )
                )
        finally:
            sftp.close()
    finally:
        client.close()

    if LOCAL_DRIVER_ARCHIVE.exists():
        shutil.copy2(LOCAL_DRIVER_ARCHIVE, snapshot_dir / LOCAL_DRIVER_ARCHIVE.name)

    write_snapshot_readme(snapshot_dir, synced_files)
    write_manifest(snapshot_dir, synced_files)
    zip_path = zip_snapshot(snapshot_dir)

    (BACKUP_ROOT / "LATEST.txt").write_text(
        f"Current backup: {snapshot_dir}\nZip: {zip_path}\n",
        encoding="utf-8",
    )

    print(f"同步完成：{snapshot_dir}")
    print(f"压缩包：{zip_path}")
    print("已同步文件：")
    for item in synced_files:
        print(f"- {item.local_path.name} ({item.size} bytes)")

    return snapshot_dir


def main() -> int:
    try:
        sync()
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
