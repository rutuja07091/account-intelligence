"""
Export Tableau-ready CSVs from the same governed definitions the assistant uses.

Each file is the base SQL of one model in semantic_model.yaml, run as of the
snapshot date. Because Tableau and the assistant read the same definitions,
"utilization" or "recently quiet" means the same thing in both places.

Output folder: tableau/data/
    accounts.csv            one row per account (utilization, last 90 vs prior 90 days)
    account_monthly.csv     one row per account per month since go-live (ramp curves)
    physician_activity.csv  one row per physician (days since last case, status)
    event_followup.csv      one row per physician per event attended (before vs after)
    cases.csv               one row per completed case (no patient data)

Run:  python3 export_for_tableau.py
"""
from __future__ import annotations

import os

import duckdb

from semantic_layer import DEFAULT_DB_PATH, SemanticLayer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "tableau", "data")


def main(db_path: str = DEFAULT_DB_PATH, out_dir: str = OUT_DIR) -> list:
    layer = SemanticLayer(db_path=db_path)
    os.makedirs(out_dir, exist_ok=True)
    con = duckdb.connect(db_path, read_only=True)
    written = []
    try:
        for name, model in layer.models.items():
            sql = model["sql"].replace("{as_of}", f"DATE '{layer.as_of}'")
            path = os.path.join(out_dir, f"{name}.csv")
            df = con.execute(sql).df()
            df.to_csv(path, index=False)
            written.append(path)
            print(f"  {name}.csv  {len(df):,} rows")
    finally:
        con.close()
    return written


if __name__ == "__main__":
    print(f"Writing Tableau extracts to {OUT_DIR}")
    main()
