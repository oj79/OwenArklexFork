import sqlite3
import argparse
import os
from pathlib import Path


def build_portfolio_db(folder_path: str) -> None:
    db_path: Path = Path(folder_path) / "portfolio.sqlite"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE trades (
            id TEXT PRIMARY KEY,
            trade_date TEXT,
            symbol TEXT,
            quantity REAL,
            price REAL,
            side TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE positions (
            id TEXT PRIMARY KEY,
            symbol TEXT UNIQUE,
            quantity REAL,
            avg_price REAL
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE notes (
            id TEXT PRIMARY KEY,
            timestamp TEXT,
            note TEXT
        )
        """
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder_path", required=True, type=str)
    args = parser.parse_args()
    if not os.path.exists(args.folder_path):
        os.makedirs(args.folder_path, exist_ok=True)
    build_portfolio_db(args.folder_path)