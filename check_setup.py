#!/usr/bin/env python3
"""Quick environment check before running Streamlit or the API.

Usage (from data_warehouse_builder/)::

    python check_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OK, FAIL, WARN = "OK ", "FAIL", "WARN"


def check(name: str, fn) -> bool:
    try:
        msg = fn()
        print(f"  [{OK}] {name}" + (f" — {msg}" if msg else ""))
        return True
    except Exception as exc:
        print(f"  [{FAIL}] {name} — {exc}")
        return False


def main() -> int:
    print("Data Warehouse Builder — setup check\n")
    passed = 0
    total = 0

    def t(name, fn):
        nonlocal passed, total
        total += 1
        if check(name, fn):
            passed += 1

    t("Python path (project root)", lambda: str(ROOT))
    t("import streamlit", lambda: (__import__("streamlit"), "")[1])
    t("import fastapi", lambda: (__import__("fastapi"), "")[1])
    t("import polars", lambda: (__import__("polars"), "")[1])
    t("import sqlalchemy", lambda: (__import__("sqlalchemy"), "")[1])
    t("import mysql.connector", lambda: (__import__("mysql.connector"), "")[1])

    from app.core.config import settings

    t("storage dirs exist", lambda: (
        f"{settings.storage_root} writable"
        if settings.storage_root.exists() else (_ for _ in ()).throw(OSError("missing"))
    ))

    t("storage backend", lambda: settings.storage_backend)

    if settings.use_file_storage:
        t("file batch store import", lambda: (
            __import__("app.services.file_store", fromlist=["list_all_batches"]),
            "STORAGE_BACKEND=file — MySQL not required",
        )[1])
    else:
        def mysql_check():
            from sqlalchemy import create_engine, text
            from urllib.parse import quote_plus

            errors: list[str] = []
            drivers = ["pymysql", "mysqlconnector"]
            hosts = [settings.mysql_host]
            if settings.mysql_host == "127.0.0.1":
                hosts.append("localhost")
            elif settings.mysql_host == "localhost":
                hosts.append("127.0.0.1")

            user = quote_plus(settings.mysql_user)
            password = quote_plus(settings.mysql_password)

            for host in hosts:
                for driver in drivers:
                    url = (
                        f"mysql+{driver}://{user}:{password}@{host}:{settings.mysql_port}/"
                        f"{settings.db_metadata}?charset={settings.mysql_charset}"
                    )
                    try:
                        engine = create_engine(url, pool_pre_ping=True, connect_args={})
                        with engine.connect() as conn:
                            conn.execute(text("SELECT 1"))
                        hint = ""
                        if host != settings.mysql_host or driver != settings.mysql_driver:
                            hint = f" (update .env: MYSQL_HOST={host}, MYSQL_DRIVER={driver})"
                        return f"{settings.mysql_user}@{host}:{settings.mysql_port}/{settings.db_metadata}{hint}"
                    except Exception as exc:
                        errors.append(f"{driver}@{host}: {exc}")

            raise RuntimeError(errors[0] if errors else "MySQL connection failed")

        total += 1
        if check("MySQL connection", mysql_check):
            passed += 1
        else:
            print()
            print("  MySQL is required when STORAGE_BACKEND=mysql. Fix options:")
            print("  1) Or switch to file mode: STORAGE_BACKEND=file in .env")
            print("  2) Run probe:  python mysql_probe.py")
            print("  3) Match .env to Workbench user (MYSQL_USER, MYSQL_PASSWORD, MYSQL_DRIVER=pymysql)")
            print("  4) If error 1044: grant dw_* access — see sql/generated/grant_saber_user.sql")
            print()
            print("  Streamlit works in file mode without MySQL.")

    print(f"\nResult: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
