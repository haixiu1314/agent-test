"""只读环境检测：不安装依赖、不读取密钥、不修改现有服务。"""
from __future__ import annotations

import ctypes
import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from ctypes import wintypes
from datetime import datetime, timezone


def main() -> None:
    """输出可保存到 JSON 的检测证据；单项失败不阻止其他项目。"""
    report: dict = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "logical_cpus": os.cpu_count(),
    }
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in (
                    "total_phys", "avail_phys", "total_page", "avail_page",
                    "total_virtual", "avail_virtual", "avail_extended",
                )
            ]
        memory = MemoryStatus()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            report["memory"] = {
                "total_gib": round(memory.total_phys / 2**30, 2),
                "available_gib": round(memory.avail_phys / 2**30, 2),
            }
    report["executables"] = {
        name: shutil.which(name) for name in (
            "python", "node", "npm", "mysql", "docker", "git", "java",
            "redis-server", "jmeter", "postman",
        )
    }
    names = [
        "fastapi", "uvicorn", "pydantic", "sqlalchemy", "pymysql", "alembic",
        "langchain", "langchain-openai", "pymilvus", "pytest", "deepeval",
        "ragas", "pandas", "matplotlib", "playwright", "cryptography",
        "python-docx", "PyMuPDF",
    ]
    report["packages"] = {}
    for name in names:
        try:
            report["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            report["packages"][name] = None
    report["imports"] = {}
    for name in ["fastapi", "uvicorn", "sqlalchemy", "pymysql", "langchain", "langchain_openai", "pytest", "playwright.sync_api"]:
        try:
            importlib.import_module(name)
            report["imports"][name] = "ok"
        except Exception as exc:
            report["imports"][name] = f"{type(exc).__name__}: {exc}"
    report["ports"] = {}
    for port in [3306, 19530, 9091, 2379, 9000, 6379, 8000, 5173]:
        with socket.socket() as connection:
            connection.settimeout(0.5)
            report["ports"][str(port)] = connection.connect_ex(("127.0.0.1", port)) == 0
    check = subprocess.run([sys.executable, "-m", "pip", "check"], capture_output=True, text=True, timeout=60)
    report["pip_check"] = {"exit_code": check.returncode, "output": check.stdout + check.stderr}
    # 仅记录变量是否存在，绝不输出密码或模型密钥。
    report["configured_environment_names"] = [name for name in [
        "DATABASE_URL", "MILVUS_URI", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
        "EMBEDDING_MODEL", "JWT_SECRET_KEY",
    ] if os.environ.get(name)]
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
