"""
Make a copy of the demo database with a `commercial` schema, so the Cube
model can use the same table names it would use in Redshift.

Run from the project root after generate_data.py:  python cube/prepare_cube_db.py
"""
import os
import shutil

import duckdb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "crm_demo.duckdb")
DST = os.path.join(ROOT, "data", "cube_demo.duckdb")

shutil.copyfile(SRC, DST)
con = duckdb.connect(DST)
con.execute("CREATE SCHEMA IF NOT EXISTS commercial")
for table in ["cases", "accounts", "physicians", "territories"]:
    con.execute(f"CREATE OR REPLACE VIEW commercial.{table} AS SELECT * FROM main.{table}")
con.close()
print(f"Wrote {DST}")
