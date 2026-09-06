#!/usr/bin/env python3
"""
Tenant-isolation audit — CI guard against org_id leaks.

Scans every backend engine + router for SELECT/INSERT/UPDATE/DELETE statements
that touch a tenant-owned table WITHOUT an org_id predicate in the same
statement (or an adjacent scope() call). This is the regression-prevention layer
for row-level multi-tenancy: a single missed WHERE clause leaks data across orgs.

Usage:
    python scripts/audit_tenant_isolation.py
    python scripts/audit_tenant_isolation.py --path backend/routers/cases.py

Exit code 0 = clean, 1 = violations found. Run this in CI on every PR.

NOTE: This is a static heuristic, not a proof. It flags *potential* leaks for
human review. Tables in tenancy.GLOBAL_TABLES are intentionally unscoped. A
statement that uses tenancy.scoped_param() or _check_org_access() is considered
guarded. False positives are expected on dynamic SQL — annotate with a
`# tenancy:scoped` comment to silence reviewed cases.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Make backend importable so we can read tenancy.TENANT_TABLES.
BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

import tenancy  # noqa: E402

# Statements that read/write tenant data. We look for the table name appearing
# after one of these keywords. Crude but catches the vast majority of raw SQL.
SQL_KEYWORDS = re.compile(
    r"\b(FROM|JOIN|INTO|UPDATE|DELETE\s+FROM|INSERT\s+INTO)\s+([a-z_]+)",
    re.IGNORECASE,
)
# A statement is considered org-scoped if it contains "org_id" anywhere in the
# same string literal or the line carries an explicit silence marker.
SCOPE_MARKER = "org_id"
SILENCE_MARKER = "tenancy:scoped"
# Functions that establish scope before the SQL runs.
GUARD_PATTERNS = [
    "scope(",
    "scoped_param(",
    "_check_org_access(",
    "tenancy.scope",
    "tenancy.scoped_param",
]


def find_sql_strings(src: str):
    """Yield (lineno, string_content) for triple-quoted and double-quoted strings
    that contain a SQL keyword + a tenant table name."""
    # Triple-quoted strings (most common for multi-line SQL in this codebase).
    for m in re.finditer(r'"""(.*?)"""|\'\'\'(.*?)\'\'\'', src, re.DOTALL):
        content = m.group(1) or m.group(2) or ""
        if any(k in content.upper() for k in ("FROM", "JOIN", "INTO", "UPDATE", "DELETE")):
            # Map back to the first line of the match.
            start = m.start()
            lineno = src.count("\n", 0, start) + 1
            yield lineno, content
    # Single-line f-strings / regular strings with SQL.
    for m in re.finditer(r'f?"((?:[^"\\]|\\.)*)"', src):
        content = m.group(1)
        if any(k in content.upper() for k in (" FROM ", " JOIN ", " INTO ", "UPDATE ", "DELETE FROM")):
            start = m.start()
            lineno = src.count("\n", 0, start) + 1
            yield lineno, content


def audit_file(path: Path) -> list[str]:
    """Return a list of violation messages for the given file."""
    src = path.read_text(encoding="utf-8", errors="replace")
    tenant_tables = set(tenancy.TENANT_TABLES)
    violations: list[str] = []

    for lineno, sql in find_sql_strings(src):
        if SILENCE_MARKER in sql:
            continue
        # Find tenant tables referenced in this SQL string.
        referenced = set()
        for km in SQL_KEYWORDS.finditer(sql):
            tbl = km.group(2).lower().strip("`\"'")
            if tbl in tenant_tables:
                referenced.add(tbl)
        if not referenced:
            continue
        # Is it scoped?
        if SCOPE_MARKER in sql:
            continue
        # Is there a guard call within ~5 lines before this SQL?
        line_start = src.rfind("\n", 0, src.find(sql, 0)) if sql in src else 0
        window = src[max(0, line_start - 400): line_start + len(sql)]
        if any(g in window for g in GUARD_PATTERNS):
            continue
        violations.append(
            f"  {path.name}:{lineno} — unscoped access to tenant table(s) "
            f"{sorted(referenced)} (no org_id predicate or scope() guard found). "
            f"Add WHERE org_id=? or annotate with # tenancy:scoped if reviewed."
        )
    return violations


def main() -> int:
    target = Path(sys.argv[2]) if "--path" in sys.argv else BACKEND
    if target.is_file():
        files = [target]
    else:
        files = sorted(
            p for p in target.rglob("*.py")
            if "venv" not in p.parts and "__pycache__" not in p.parts
            and "tests" not in p.parts
        )

    total_violations = 0
    for f in files:
        v = audit_file(f)
        if v:
            total_violations += len(v)
            rel = f.relative_to(BACKEND.parent) if BACKEND.parent in f.parents else f
            print(f"\n{rel}:")
            for line in v:
                print(line)

    # Also report the authoritative table lists for visibility.
    print(f"\n--- Tenant-owned tables ({len(tenancy.TENANT_TABLES)}): require org_id ---")
    print(f"--- Global tables ({len(tenancy.GLOBAL_TABLES)}): intentionally unscoped ---")

    if total_violations:
        print(f"\nFAILED: {total_violations} potential tenant-isolation violation(s) found.")
        print("Review each one — add org_id scoping or annotate with # tenancy:scoped.")
        return 1
    print("\nOK: no unscoped tenant-table access detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
