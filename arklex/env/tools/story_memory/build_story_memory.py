import sqlite3
import argparse
import os
from pathlib import Path


def build_story_memory(folder_path: str) -> None:
    db_path: Path = Path(folder_path) / "stories.sqlite"
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE stories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            summary TEXT,
            details TEXT
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
    build_story_memory(args.folder_path)