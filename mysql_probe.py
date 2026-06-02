#!/usr/bin/env python3
"""Try multiple MySQL connection modes and report which one works.

Usage (from data_warehouse_builder/)::

    python mysql_probe.py
    python mysql_probe.py --user root --password YOUR_PASSWORD
    python mysql_probe.py --user dw_user --password secret --host 127.0.0.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text


def try_connect(
    *,
    driver: str,
    host: str,
    port: int,
    user: str,
    password: str,
    database: str,
) -> tuple[bool, str]:
    safe_user = quote_plus(user)
    safe_pass = quote_plus(password)
    url = f"mysql+{driver}://{safe_user}:{safe_pass}@{host}:{port}/{database}?charset=utf8mb4"
    connect_args: dict = {}
    try:
        engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "connected"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe MySQL connection options")
    parser.add_argument("--user", default=None)
    parser.add_argument("--password", default=None)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--database", default=None)
    args = parser.parse_args()

    from app.core.config import settings

    user = args.user or settings.mysql_user
    password = args.password if args.password is not None else settings.mysql_password
    port = args.port or settings.mysql_port
    database = args.database or settings.db_metadata

    hosts = [args.host] if args.host else ["127.0.0.1", "localhost"]
    drivers = ["pymysql", "mysqlconnector"]

    print("MySQL connection probe")
    print(f"  user={user!r}  password_len={len(password)}  port={port}  database={database}")
    print()

    ok_any = False
    for host in hosts:
        for driver in drivers:
            label = f"driver={driver:14} host={host:12}"
            ok, msg = try_connect(
                driver=driver,
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
            )
            if ok:
                print(f"  [OK ] {label}")
                print()
                print("Put this in your .env file:")
                print(f"  MYSQL_HOST={host}")
                print(f"  MYSQL_USER={user}")
                print(f"  MYSQL_PASSWORD={password}")
                print(f"  MYSQL_DRIVER={driver}")
                ok_any = True
            else:
                short = msg.split("\n")[0][:120]
                print(f"  [FAIL] {label} -> {short}")

    if not ok_any:
        print()
        print("No connection worked.")
        print()
        print("Error guide:")
        print("  1045 = wrong password or user does not exist")
        print("  1044 = password OK, but user lacks permission on that database")
        print()
        print("If you see 1044, run in MySQL Workbench as admin (root):")
        print(f"     -- First create databases if missing:")
        print("     SOURCE sql/generated/create_databases.sql;")
        print(f"     GRANT ALL ON dw_metadata.* TO '{user}'@'%';")
        print(f"     GRANT ALL ON dw_bronze.*   TO '{user}'@'%';")
        print(f"     GRANT ALL ON dw_silver.*   TO '{user}'@'%';")
        print(f"     GRANT ALL ON dw_gold.*     TO '{user}'@'%';")
        print(f"     GRANT ALL ON dw_metadata.* TO '{user}'@'localhost';")
        print(f"     GRANT ALL ON dw_bronze.*   TO '{user}'@'localhost';")
        print(f"     GRANT ALL ON dw_silver.*   TO '{user}'@'localhost';")
        print(f"     GRANT ALL ON dw_gold.*     TO '{user}'@'localhost';")
        print("     FLUSH PRIVILEGES;")
        print()
        print("Or run the ready-made script:")
        print("     sql/generated/grant_saber_user.sql  (edit username if not saber)")
        print()
        print("Common fixes in MySQL Workbench (run as admin user):")
        print("  -- Create user allowed from this PC:")
        print("     CREATE USER 'dw_user'@'localhost' IDENTIFIED BY 'YourPassword';")
        print("     CREATE USER 'dw_user'@'127.0.0.1' IDENTIFIED BY 'YourPassword';")
        print("     GRANT ALL PRIVILEGES ON dw_metadata.* TO 'dw_user'@'localhost';")
        print("     GRANT ALL PRIVILEGES ON dw_bronze.*   TO 'dw_user'@'localhost';")
        print("     GRANT ALL PRIVILEGES ON dw_silver.*   TO 'dw_user'@'localhost';")
        print("     GRANT ALL PRIVILEGES ON dw_gold.*     TO 'dw_user'@'localhost';")
        print("     GRANT ALL PRIVILEGES ON dw_metadata.* TO 'dw_user'@'127.0.0.1';")
        print("     GRANT ALL PRIVILEGES ON dw_bronze.*   TO 'dw_user'@'127.0.0.1';")
        print("     GRANT ALL PRIVILEGES ON dw_silver.*   TO 'dw_user'@'127.0.0.1';")
        print("     GRANT ALL PRIVILEGES ON dw_gold.*     TO 'dw_user'@'127.0.0.1';")
        print("     FLUSH PRIVILEGES;")
        print()
        print("Then test:")
        print("  python mysql_probe.py --user dw_user --password YourPassword")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
