"""Create the WallaceSign MySQL database/user using root credentials.

Usage:
  .\\.venv\\Scripts\\python scripts\\setup_mysql.py
  .\\.venv\\Scripts\\python scripts\\setup_mysql.py --password YOUR_ROOT_PASSWORD
"""

from __future__ import annotations

import argparse
import getpass
import sys

import pymysql


SQL = [
    "CREATE DATABASE IF NOT EXISTS wallacesign CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci",
    "CREATE USER IF NOT EXISTS 'wallacesign'@'localhost' IDENTIFIED BY 'wallacesign'",
    "CREATE USER IF NOT EXISTS 'wallacesign'@'127.0.0.1' IDENTIFIED BY 'wallacesign'",
    "GRANT ALL PRIVILEGES ON wallacesign.* TO 'wallacesign'@'localhost'",
    "GRANT ALL PRIVILEGES ON wallacesign.* TO 'wallacesign'@'127.0.0.1'",
    "FLUSH PRIVILEGES",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Setup WallaceSign MySQL database")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3306)
    parser.add_argument("--user", default="root")
    parser.add_argument("--password", default=None)
    args = parser.parse_args()

    password = args.password
    if password is None:
        password = getpass.getpass(f"MySQL password for {args.user}: ")

    try:
        conn = pymysql.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            autocommit=True,
        )
    except pymysql.Error as exc:
        print(f"Failed to connect as {args.user}: {exc}", file=sys.stderr)
        return 1

    with conn.cursor() as cur:
        for statement in SQL:
            cur.execute(statement)
            print("OK:", statement)

    conn.close()
    print("MySQL setup complete. App credentials: wallacesign / wallacesign @ wallacesign")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
