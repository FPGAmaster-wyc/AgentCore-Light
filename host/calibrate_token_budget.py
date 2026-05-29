import argparse
import sqlite3
from pathlib import Path


STATE_DB_PATH = Path.home() / ".codex" / "state_5.sqlite"


def latest_tokens_used():
    con = sqlite3.connect(str(STATE_DB_PATH))
    cur = con.cursor()
    cur.execute("SELECT tokens_used FROM threads ORDER BY updated_at_ms DESC LIMIT 1")
    row = cur.fetchone()
    con.close()
    if not row or row[0] is None:
        raise RuntimeError("Cannot read tokens_used from state_5.sqlite")
    return int(row[0])


def main():
    parser = argparse.ArgumentParser(description="Calibrate CODEX_TOKEN_BUDGET from current percent")
    parser.add_argument("current_percent", type=int, help="Current percent shown by Codex UI, e.g. 15")
    args = parser.parse_args()

    p = max(0, min(100, args.current_percent))
    used = latest_tokens_used()

    if p >= 100:
        budget = max(used, 1)
    else:
        budget = int(round(used * 100.0 / max(1, 100 - p)))

    print(f"tokens_used={used}")
    print(f"recommended CODEX_TOKEN_BUDGET={budget}")
    print(f"setx CODEX_TOKEN_BUDGET {budget}")


if __name__ == "__main__":
    main()
