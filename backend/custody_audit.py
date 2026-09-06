"""
Chain-of-custody audit report.

Generates a comprehensive audit trail for a case: who viewed/exported what, when.
Essential for court admissibility — establishes that evidence hasn't been tampered
with and who had access throughout the investigation lifecycle.

Aggregates from:
  - evidence_vault audit log
  - evidence_vault hash-chain verification
  - report_artifacts (exports)
  - case address/note changes
  - attribution audit
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import database as db


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_custody_report(case_id: str) -> dict:
    """Generate a full chain-of-custody report for a case."""
    import evidence_vault
    evidence_vault.init_evidence_tables()

    case = db.get_case(case_id)
    if not case:
        raise ValueError("case not found")

    # 1. Evidence custody verification
    chain_verification = evidence_vault.verify_chain(case_id=case_id)

    # 2. All evidence audit-log entries for this case
    evidence_list = evidence_vault.list_evidence(case_id, limit=500)
    audit_entries: list[dict] = []
    for ev in evidence_list:
        ev_audit = evidence_vault.get_audit_log(ev["id"])
        for entry in ev_audit:
            entry["evidence_title"] = ev.get("title", "")
            entry["evidence_type"] = ev.get("evidence_type", "")
            audit_entries.append(entry)
    audit_entries.sort(key=lambda x: x.get("timestamp", ""))

    # 3. Report exports
    with db.get_connection() as con:
        exports = con.execute(
            "SELECT id, subject, title, format, created_at FROM report_artifacts WHERE case_id=? ORDER BY created_at",
            (case_id,),
        ).fetchall()

    # 4. Case timeline (creation, address additions, notes)
    case_events: list[dict] = []
    case_events.append({
        "timestamp": case.get("created_at", ""),
        "actor": "system",
        "action": "case_created",
        "detail": f"Case '{case.get('name', '')}' created",
    })
    for addr in (case.get("addresses") or []):
        case_events.append({
            "timestamp": addr.get("added_at", ""),
            "actor": "investigator",
            "action": "address_added",
            "detail": f"{addr.get('address', '')} ({addr.get('chain', '')}) — {addr.get('label', '')}",
        })
    for note in (case.get("notes") or []):
        case_events.append({
            "timestamp": note.get("created_at", ""),
            "actor": "investigator",
            "action": "note_added",
            "detail": note.get("note", "")[:150],
        })
    case_events.sort(key=lambda x: x.get("timestamp", ""))

    # 5. Attribution audit (if available)
    attribution_entries: list[dict] = []
    try:
        import attribution_engine
        attribution_entries = attribution_engine.audit(case_id=case_id, limit=100)
    except Exception:
        pass

    # 6. Summary statistics
    actor_activity: dict[str, int] = {}
    action_counts: dict[str, int] = {}
    for entry in audit_entries + case_events:
        actor = entry.get("actor", "unknown")
        actor_activity[actor] = actor_activity.get(actor, 0) + 1
        action = entry.get("action", "")
        action_counts[action] = action_counts.get(action, 0) + 1

    return {
        "case_id": case_id,
        "case_name": case.get("name", ""),
        "generated_at": _now(),
        "custody_integrity": {
            "chain_valid": chain_verification.get("valid", False),
            "records_checked": chain_verification.get("records_checked", 0),
            "problems": chain_verification.get("problems", []),
            "chain_tip": chain_verification.get("chain_tip", ""),
        },
        "evidence_summary": evidence_vault.case_evidence_summary(case_id),
        "audit_trail": audit_entries,
        "case_events": case_events,
        "exports": [dict(e) for e in exports],
        "attribution_changes": attribution_entries,
        "summary": {
            "total_audit_entries": len(audit_entries),
            "total_case_events": len(case_events),
            "total_exports": len(exports),
            "actor_activity": actor_activity,
            "action_counts": action_counts,
            "first_activity": (audit_entries or case_events or [{}])[0].get("timestamp", ""),
            "last_activity": (audit_entries or case_events or [{}])[-1].get("timestamp", ""),
        },
    }


def custody_report_html(case_id: str) -> str:
    """Render the custody report as a printable HTML document."""
    report = generate_custody_report(case_id)
    from html import escape
    e = escape
    rows = ""
    for entry in (report["audit_trail"] + report["case_events"])[:200]:
        rows += (
            f"<tr><td>{e(entry.get('timestamp', ''))}</td>"
            f"<td>{e(entry.get('actor', ''))}</td>"
            f"<td>{e(entry.get('action', ''))}</td>"
            f"<td>{e(str(entry.get('detail', ''))[:200])}</td></tr>"
        )
    chain_ok = "✅ VALID" if report["custody_integrity"]["chain_valid"] else "❌ BROKEN"
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
    <title>Chain of Custody — {e(report['case_name'])}</title>
    <style>
    body {{ font-family: -apple-system, sans-serif; margin: 40px; color: #1a1a1a; }}
    h1 {{ color: #dc2626; }} h2 {{ border-bottom: 2px solid #dc2626; padding-bottom: 6px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: left; }}
    th {{ background: #fee2e2; }} tr:nth-child(even) {{ background: #f9fafb; }}
    .summary {{ background: #f3f4f6; padding: 16px; border-radius: 8px; margin: 16px 0; }}
    .integrity-ok {{ color: #16a34a; font-weight: bold; }}
    .integrity-broken {{ color: #dc2626; font-weight: bold; }}
    @media print {{ body {{ margin: 12px; }} }}
    </style></head><body>
    <h1>Chain of Custody Report</h1>
    <p><strong>Case:</strong> {e(report['case_name'])} ({e(case_id[:8])}…)<br>
    <strong>Generated:</strong> {e(report['generated_at'])}</p>
    <div class="summary">
      <h2>Custody Integrity</h2>
      <p class="{'integrity-ok' if report['custody_integrity']['chain_valid'] else 'integrity-broken'}">
        Hash chain: {chain_ok} — {report['custody_integrity']['records_checked']} records checked</p>
      <p><strong>Evidence records:</strong> {report['evidence_summary'].get('total', 0)} |
         <strong>Avg quality:</strong> {report['evidence_summary'].get('avg_quality', 0)}/100 |
         <strong>Exports:</strong> {report['summary']['total_exports']}</p>
    </div>
    <h2>Audit Trail ({len(report['audit_trail']) + len(report['case_events'])} events)</h2>
    <table><thead><tr><th>Timestamp</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
    <tbody>{rows}</tbody></table>
    <p style="font-size:10px;color:#666;margin-top:40px;">
    Generated by CrypTX Investigation Platform. This audit trail establishes the chain of
    custody for all evidence artifacts in this case. The tamper-evident hash chain
    cryptographically verifies that no evidence record has been altered since recording.
    </p>
    </body></html>"""
