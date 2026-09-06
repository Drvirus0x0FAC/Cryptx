"""
Attribution workflow — the Tracker-style label-growth loop + court methodology report.

1. Submission queue: analysts/users submit address→entity attributions with evidence.
   Nothing enters `attribution_engine` until a reviewer approves it, preserving the
   engine's provenance guarantees (source = "submission:<id>", full audit trail).

2. Attribution Source Report: a printable per-address HTML document that explains
   HOW each attribution was derived (source, method class, evidence, confidence,
   analyst, timestamps) — the "transparent methodology for prosecution" artifact.
"""
from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
import attribution_engine as ae

DB_PATH = _config.DB_PATH

STATUSES = ("pending", "approved", "rejected")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _esc(v: Any) -> str:
    return html.escape(str(v if v is not None else ""))


def init_submission_tables() -> None:
    with _conn() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS attribution_submissions (
                id                 TEXT PRIMARY KEY,
                address            TEXT NOT NULL,
                chain              TEXT DEFAULT '',
                category           TEXT DEFAULT 'unknown',
                actor              TEXT DEFAULT '',
                label              TEXT DEFAULT '',
                source             TEXT DEFAULT '',
                confidence         REAL DEFAULT 0.6,
                evidence           TEXT DEFAULT '[]',
                note               TEXT DEFAULT '',
                submitted_by       TEXT DEFAULT '',
                submitted_at       TEXT NOT NULL,
                status             TEXT NOT NULL DEFAULT 'pending',
                reviewed_by        TEXT DEFAULT '',
                reviewed_at        TEXT DEFAULT '',
                review_note        TEXT DEFAULT '',
                resulting_attr_id  TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_subs_status ON attribution_submissions(status);
            CREATE INDEX IF NOT EXISTS idx_subs_address ON attribution_submissions(address);
            """
        )
        con.commit()


# ── submission queue ─────────────────────────────────────────────────────────

def submit(address: str, category: str = "unknown", actor: str = "", label: str = "",
           source: str = "", confidence: float = 0.6, evidence: Optional[list[dict[str, Any]]] = None,
           chain: str = "", note: str = "", submitted_by: str = "analyst") -> dict[str, Any]:
    addr = (address or "").strip()
    if not addr:
        raise ValueError("address is required")
    if not (actor or label):
        raise ValueError("actor or label is required")
    if not evidence:
        raise ValueError("at least one evidence item is required (type + value/ref)")
    sid = f"sub_{uuid.uuid4().hex[:12]}"
    with _conn() as con:
        con.execute(
            """INSERT INTO attribution_submissions
               (id, address, chain, category, actor, label, source, confidence, evidence,
                note, submitted_by, submitted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (sid, addr.lower(), chain, category, actor, label, source,
             max(0.0, min(1.0, float(confidence))), json.dumps(evidence), note,
             submitted_by, _now()),
        )
        con.commit()
    return get_submission(sid)  # type: ignore[return-value]


def get_submission(sub_id: str) -> Optional[dict[str, Any]]:
    with _conn() as con:
        r = con.execute("SELECT * FROM attribution_submissions WHERE id=?", (sub_id,)).fetchone()
    if not r:
        return None
    sub = dict(r)
    try:
        sub["evidence"] = json.loads(sub.get("evidence") or "[]")
    except Exception:  # noqa: BLE001
        sub["evidence"] = []
    return sub


def list_submissions(status: str = "", address: str = "", limit: int = 200) -> list[dict[str, Any]]:
    q, args = "SELECT * FROM attribution_submissions", []
    cond = []
    if status and status in STATUSES:
        cond.append("status=?"); args.append(status)
    if address:
        cond.append("address=?"); args.append(address.strip().lower())
    if cond:
        q += " WHERE " + " AND ".join(cond)
    q += " ORDER BY submitted_at DESC LIMIT ?"
    args.append(limit)
    with _conn() as con:
        rows = con.execute(q, args).fetchall()
    out = []
    for r in rows:
        sub = dict(r)
        try:
            sub["evidence"] = json.loads(sub.get("evidence") or "[]")
        except Exception:  # noqa: BLE001
            sub["evidence"] = []
        out.append(sub)
    return out


def review(sub_id: str, action: str, reviewer: str = "reviewer", review_note: str = "") -> dict[str, Any]:
    """Approve (→ enters attribution_engine with provenance) or reject a submission."""
    if action not in ("approve", "reject"):
        raise ValueError("action must be 'approve' or 'reject'")
    sub = get_submission(sub_id)
    if not sub:
        raise ValueError("submission not found")
    if sub["status"] != "pending":
        raise ValueError(f"submission already {sub['status']}")

    resulting_attr_id = ""
    if action == "approve":
        result = ae.add_attribution(
            sub["address"], category=sub["category"], actor=sub["actor"], label=sub["label"],
            source=sub["source"] or f"Reviewed submission {sub_id} (by {sub['submitted_by']})",
            confidence=sub["confidence"], evidence=sub["evidence"], chain=sub["chain"],
            assigned_by=reviewer, method_class="analyst", method="reviewed_submission",
            note=f"submission:{sub_id}" + (f" · {sub['note']}" if sub["note"] else ""),
        )
        resulting_attr_id = result.get("id", "")

    status = "approved" if action == "approve" else "rejected"
    with _conn() as con:
        con.execute(
            "UPDATE attribution_submissions SET status=?, reviewed_by=?, reviewed_at=?,"
            " review_note=?, resulting_attr_id=? WHERE id=?",
            (status, reviewer, _now(), review_note, resulting_attr_id, sub_id),
        )
        con.commit()
    return get_submission(sub_id)  # type: ignore[return-value]


def queue_stats() -> dict[str, Any]:
    with _conn() as con:
        rows = con.execute(
            "SELECT status, COUNT(*) AS n FROM attribution_submissions GROUP BY status"
        ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {"pending": counts.get("pending", 0), "approved": counts.get("approved", 0),
            "rejected": counts.get("rejected", 0), "total": sum(counts.values())}


# ── attribution source report (court methodology document) ──────────────────

_METHOD_CLASS_EXPLAIN = {
    "deterministic": "Exact-match lookup against a cited authoritative dataset (e.g. OFAC SDN list, "
                     "verified VASP deposit records, verified contract registry). Reproducible by any "
                     "party with access to the same dataset; suitable for evidentiary use.",
    "analyst": "Assertion recorded by a named analyst with supporting evidence, or an approved "
               "external submission that passed reviewer sign-off. Attribution quality depends on "
               "the cited evidence; corroboration recommended before evidentiary use.",
    "heuristic": "Algorithmic inference (clustering, co-spend, behavioral patterns). An investigative "
                 "lead only — NOT a court-defensible identification on its own.",
}


def build_source_report(address: str, chain: Optional[str] = None) -> str:
    """Printable HTML: how every attribution on `address` was derived. Print → PDF."""
    record = ae.attribute(address, chain)
    audit = ae.audit(address)
    now = _now()
    attributions = record.get("attributions", [])
    record_hash = hashlib.sha256(
        json.dumps(record, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    def evidence_rows(evidence: list[dict[str, Any]]) -> str:
        if not evidence:
            return '<tr><td colspan="3" class="note">No structured evidence attached.</td></tr>'
        rows = []
        for ev in evidence:
            rows.append(
                f"<tr><td>{_esc(ev.get('type', '-'))}</td>"
                f"<td>{_esc(ev.get('value', '-'))}</td>"
                f"<td>{_esc(ev.get('ref', ev.get('reference', '-')))}</td></tr>"
            )
        return "".join(rows)

    attr_sections = []
    for i, a in enumerate(attributions, 1):
        mc = a.get("method_class", "-")
        attr_sections.append(f"""
<h2>Attribution {i}: {_esc(a.get('label') or a.get('actor') or a.get('category'))}</h2>
<table>
<tr><th style="width:180px">Category</th><td>{_esc(a.get('category'))}</td></tr>
<tr><th>Actor / Entity</th><td>{_esc(a.get('actor') or '-')}</td></tr>
<tr><th>Source</th><td>{_esc(a.get('source'))}</td></tr>
<tr><th>Method</th><td><code>{_esc(a.get('method'))}</code></td></tr>
<tr><th>Method class</th><td><strong>{_esc(mc)}</strong> — {_esc(_METHOD_CLASS_EXPLAIN.get(mc, ''))}</td></tr>
<tr><th>Confidence</th><td>{_esc(a.get('confidence'))}</td></tr>
<tr><th>Assigned by / at</th><td>{_esc(a.get('assigned_by'))} · {_esc(a.get('assigned_at'))}</td></tr>
<tr><th>Record ID</th><td><code>{_esc(a.get('id') or 'live-computed (recomputed on demand, not stored)')}</code></td></tr>
</table>
<h3>Cited evidence</h3>
<table><tr><th>Type</th><th>Value</th><th>Reference</th></tr>
{evidence_rows(a.get('evidence') or [])}
</table>""")

    revoked = [x for x in (audit.get("records") or [])
               if isinstance(x, dict) and not x.get("valid", 1)]
    revoked_html = ""
    if revoked:
        rows = "".join(
            f"<tr><td>{_esc(x.get('label'))}</td><td>{_esc(x.get('source'))}</td>"
            f"<td>{_esc(x.get('assigned_at'))}</td><td>{_esc(x.get('note'))}</td></tr>"
            for x in revoked
        )
        revoked_html = f"""
<h2>Revoked attributions (full audit trail)</h2>
<p class="note">Revoked records are retained for completeness and shown here for transparency.</p>
<table><tr><th>Label</th><th>Source</th><th>Assigned</th><th>Note</th></tr>{rows}</table>"""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Attribution Source Report — {_esc(address)}</title>
<style>
body {{ font-family: Arial, sans-serif; color:#111827; background:#fff; margin:36px; }}
h1 {{ font-size:22px; margin-bottom:4px; }}
h2 {{ font-size:15px; margin-top:26px; border-left:4px solid #0891b2; padding-left:8px; }}
h3 {{ font-size:13px; margin-top:14px; }}
.meta {{ color:#4b5563; font-size:12px; margin-bottom:20px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:6px; }}
th, td {{ border:1px solid #d1d5db; padding:6px 8px; text-align:left; vertical-align:top; word-break:break-word; }}
th {{ background:#f3f4f6; }}
.note {{ color:#4b5563; font-size:12px; }}
.verdict {{ padding:10px 14px; border-radius:6px; font-weight:700; margin:14px 0; }}
.yes {{ background:#dcfce7; border:1px solid #16a34a; color:#14532d; }}
.no  {{ background:#fef9c3; border:1px solid #ca8a04; color:#713f12; }}
code {{ background:#f3f4f6; padding:1px 4px; border-radius:3px; font-size:11px; }}
.hash {{ font-family:monospace; font-size:10px; color:#6b7280; word-break:break-all; }}
@media print {{ body {{ margin:12mm; }} }}
</style>
</head>
<body>
<h1>Attribution Source Report</h1>
<div class="meta">Generated {_esc(now)} · CrypTX attribution engine · This document explains the derivation
methodology of every attribution attached to the subject address.</div>
<p><strong>Subject:</strong> <code>{_esc(address)}</code> · <strong>Chain:</strong> {_esc(chain or record.get('chain') or 'auto')}</p>

<div class="verdict {'yes' if record.get('court_defensible') else 'no'}">
Court-defensible: {'YES' if record.get('court_defensible') else 'NO — investigative leads only'}
</div>
<p class="note">{_esc(record.get('court_defensible_reason'))}</p>

<h2>Summary</h2>
<table>
<tr><th style="width:180px">Attributions</th><td>{_esc(record.get('attribution_count'))}</td></tr>
<tr><th>Categories</th><td>{_esc(', '.join(record.get('categories') or []) or '-')}</td></tr>
<tr><th>Actors</th><td>{_esc(', '.join(record.get('actors') or []) or '-')}</td></tr>
<tr><th>Overall confidence</th><td>{_esc(record.get('overall_confidence'))}</td></tr>
</table>

{''.join(attr_sections) or '<p class="note">No attributions on record for this address.</p>'}
{revoked_html}

<h2>Methodology statement</h2>
<p class="note">Attributions in this system are provenance-tracked: every record carries its source dataset or
analyst identity, derivation method, confidence, timestamps, and cited evidence. Deterministic exact-match
attributions against authoritative datasets are reproducible by independent parties. Heuristic outputs are
clearly labeled and excluded from court-defensibility determinations. Analyst records identify the submitting
and approving individuals. {_esc(record.get('disclaimer'))}</p>

<h2>Integrity</h2>
<p class="hash">SHA-256 of the attribution record serialized at generation time:<br/>{record_hash}</p>
<p class="note">To produce a PDF: use your browser's Print → Save as PDF. The layout is print-optimized.</p>
</body>
</html>"""
