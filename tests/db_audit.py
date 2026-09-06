"""DB schema + query audit: row counts, missing indexes on hot lookup columns."""
import sqlite3
con = sqlite3.connect('cryptoosint.db')
con.row_factory = sqlite3.Row

print("=== TABLE ROW COUNTS (non-empty) ===")
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
).fetchall()]
for t in tables:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    if n > 0:
        print(f"  {t:40} {n:>8}")

print("\n=== HOT LOOKUP COLUMNS — checking for missing indexes ===")
# Columns frequently filtered on but may lack an index.
checks = [
    ("case_addresses", "address"),
    ("case_addresses", "chain"),
    ("victim_reports", "scammer_address"),
    ("victim_reports", "status"),
    ("evidence_vault", "subject"),
    ("evidence_vault", "evidence_type"),
    ("evidence_vault", "case_id"),
    ("attributions", "category"),
    ("sanctions_hits", "address"),
    ("graph_edges", "source"),
    ("graph_edges", "target"),
    ("address_cache_v2", "chain"),
    ("alert_rules", "address"),
    ("monitor_watches", "address"),
    ("price_cache", "asset"),
]
existing = {}
for t in tables:
    idxs = con.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name=?", (t,)
    ).fetchall()
    existing[t] = [(i["name"], (i["sql"] or "").lower()) for i in idxs]

for tbl, col in checks:
    # Does any index on this table mention the column?
    has = any(col in (sql or "") for _, sql in existing.get(tbl, []))
    # Does the table+column exist?
    try:
        cols = [r["name"] for r in con.execute(f"PRAGMA table_info({tbl})").fetchall()]
        exists = col in cols
    except Exception:
        exists = False
    flag = ""
    if not exists:
        flag = "(column/table absent)"
    elif not has:
        flag = "  <-- NO INDEX"
    print(f"  {tbl}.{col:18} {'✓ indexed' if (exists and has) else 'MISSING/UNINDEXED'} {flag}")

print("\n=== EXPLAIN QUERY PLAN: sample hot queries ===")
sample_queries = [
    ("victim by scammer", "SELECT * FROM victim_reports WHERE scammer_address='0x47666fab8bd0ac7003bce3f5c3585383f09486e2'"),
    ("evidence by case", "SELECT * FROM evidence_vault WHERE case_id='demo0000-0000-4000-a000-embe4f0463e0'"),
    ("case_addresses by address", "SELECT case_id FROM case_addresses WHERE address='0x47666fab8bd0ac7003bce3f5c3585383f09486e2'"),
    ("attributions by address", "SELECT * FROM attributions WHERE address='0x47666fab8bd0ac7003bce3f5c3585383f09486e2'"),
]
for label, q in sample_queries:
    try:
        plan = con.execute(f"EXPLAIN QUERY PLAN {q}").fetchall()
        detail = " | ".join(str(p[3]) for p in plan)
        scan = "SCAN" in detail.upper()
        print(f"  {label:32} {'🟢' if not scan else '🔴 SCAN(table)'}  {detail[:90]}")
    except Exception as e:
        print(f"  {label:32} (query error: {e})")
