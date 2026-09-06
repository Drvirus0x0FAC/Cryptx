"""
Regulatory report generation: SAR, CTR, and Travel Rule (IVMS101-style).

Builds compliance-ready report objects from investigation data, auto-enriched
with sanctions screening (sanctions_engine) and VASP attribution
(vasp_directory). Each generator returns a structured dict plus a rendered
Markdown document suitable for export/printing.

These are DRAFT artifacts to accelerate analyst filing. They are not legal
filings and must be reviewed by a compliance officer before submission.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import sanctions_engine
import vasp_directory

CTR_THRESHOLD_USD = 10_000.0  # FinCEN CTR aggregation threshold

SAR_ACTIVITY_CATEGORIES = [
    "Money laundering", "Terrorist financing", "Sanctions evasion", "Fraud / scam",
    "Ransomware", "Darknet marketplace", "Mixer / tumbler use", "Structuring",
    "Stolen funds", "Unregistered MSB / VASP", "Other",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _enrich_address(address: str, chain: Optional[str] = None) -> dict[str, Any]:
    """Attach sanctions + VASP context to an address."""
    sanc = sanctions_engine.screen_address(address, chain)
    vasp = vasp_directory.identify_vasp(address, chain)
    return {
        "address": address,
        "chain": chain or "",
        "sanctioned": sanc["sanctioned"],
        "sanctions_matches": sanc["matches"],
        "is_vasp": vasp["is_vasp"],
        "vasp": vasp["vasp"],
    }


# ---------------------------------------------------------------------------
# SAR — Suspicious Activity Report
# ---------------------------------------------------------------------------
def generate_sar(payload: dict[str, Any]) -> dict[str, Any]:
    subject = (payload.get("subject_address") or "").strip()
    chain = payload.get("chain") or ""
    narrative = payload.get("narrative") or ""
    categories = payload.get("activity_categories") or []
    counterparties = payload.get("counterparties") or []
    transactions = payload.get("transactions") or []
    amount_usd = float(payload.get("total_amount_usd") or 0)
    filer = payload.get("filing_institution") or "CryptoOSINT Investigator"
    case_id = payload.get("case_id") or ""

    subject_ctx = _enrich_address(subject, chain) if subject else {}
    cp_ctx = [_enrich_address(c.get("address", c) if isinstance(c, dict) else c, chain) for c in counterparties]
    sanctioned_hits = ([subject_ctx] if subject_ctx.get("sanctioned") else []) + [c for c in cp_ctx if c["sanctioned"]]

    report = {
        "report_type": "SAR",
        "report_standard": "FinCEN Suspicious Activity Report (crypto)",
        "generated_at": _now(),
        "case_id": case_id,
        "filing_institution": filer,
        "subject": subject_ctx,
        "suspicious_activity": {
            "categories": categories,
            "total_amount_usd": amount_usd,
            "narrative": narrative,
            "transaction_count": len(transactions),
        },
        "counterparties": cp_ctx,
        "transactions": transactions,
        "sanctions_hits": sanctioned_hits,
        "auto_flags": _auto_flags(subject_ctx, cp_ctx, categories),
    }
    report["markdown"] = _render_sar_md(report)
    return report


def _auto_flags(subject_ctx: dict, cp_ctx: list[dict], categories: list[str]) -> list[str]:
    flags = []
    if subject_ctx.get("sanctioned"):
        flags.append("Subject address matches a sanctions list — priority escalation.")
    sanc_cp = [c for c in cp_ctx if c.get("sanctioned")]
    if sanc_cp:
        flags.append(f"{len(sanc_cp)} counterparty address(es) match sanctions lists.")
    vasp_cp = [c for c in cp_ctx if c.get("is_vasp")]
    if vasp_cp:
        flags.append(f"{len(vasp_cp)} counterparty address(es) attributed to known VASPs (potential off-ramp).")
    if "Mixer / tumbler use" in categories:
        flags.append("Mixer usage indicated — consider demixing analysis for source/destination pairing.")
    return flags


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out) + "\n"


def _render_sar_md(r: dict[str, Any]) -> str:
    s = r["subject"]
    sa = r["suspicious_activity"]
    lines = [
        f"# Suspicious Activity Report (DRAFT)",
        "",
        f"**Standard:** {r['report_standard']}  ",
        f"**Generated:** {r['generated_at']}  ",
        f"**Filing institution:** {r['filing_institution']}  ",
        f"**Case ID:** {r['case_id'] or '—'}",
        "",
        "## 1. Subject",
        f"- **Address:** `{s.get('address','—')}` ({s.get('chain') or 'n/a'})",
        f"- **Sanctioned:** {'YES — ' + ', '.join(m['name'] for m in s.get('sanctions_matches', [])) if s.get('sanctioned') else 'No match'}",
        f"- **VASP:** {s['vasp']['name'] if s.get('is_vasp') and s.get('vasp') else '—'}",
        "",
        "## 2. Suspicious Activity",
        f"- **Categories:** {', '.join(sa['categories']) or '—'}",
        f"- **Total amount (USD):** ${sa['total_amount_usd']:,.2f}",
        f"- **Transactions:** {sa['transaction_count']}",
        "",
        "### Narrative",
        sa["narrative"] or "_No narrative provided._",
        "",
        "## 3. Automated Flags",
    ]
    lines += [f"- {f}" for f in r["auto_flags"]] or ["_None._"]
    lines += [
        "",
        "## 4. Counterparties",
        _md_table(
            ["Address", "Sanctioned", "VASP"],
            [[c["address"], "YES" if c["sanctioned"] else "—", (c["vasp"]["name"] if c.get("vasp") else "—")] for c in r["counterparties"]],
        ),
        "## 5. Transactions",
        _md_table(
            ["Hash", "From", "To", "Amount", "Asset"],
            [[t.get("hash", "—"), t.get("from", "—"), t.get("to", "—"), t.get("amount", "—"), t.get("asset", "—")] for t in r["transactions"]],
        ),
        "---",
        "_DRAFT — review by a compliance officer required before filing._",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CTR — Currency Transaction Report
# ---------------------------------------------------------------------------
def generate_ctr(payload: dict[str, Any]) -> dict[str, Any]:
    subject = (payload.get("subject_address") or "").strip()
    chain = payload.get("chain") or ""
    transactions = payload.get("transactions") or []
    threshold = float(payload.get("threshold_usd") or CTR_THRESHOLD_USD)
    filer = payload.get("filing_institution") or "CryptoOSINT Investigator"

    total = sum(float(t.get("amount_usd") or 0) for t in transactions)
    reportable = total >= threshold
    subject_ctx = _enrich_address(subject, chain) if subject else {}

    report = {
        "report_type": "CTR",
        "report_standard": "FinCEN Currency Transaction Report (aggregated crypto)",
        "generated_at": _now(),
        "filing_institution": filer,
        "subject": subject_ctx,
        "threshold_usd": threshold,
        "aggregate_amount_usd": total,
        "reportable": reportable,
        "transaction_count": len(transactions),
        "transactions": transactions,
    }
    lines = [
        "# Currency Transaction Report (DRAFT)",
        "",
        f"**Standard:** {report['report_standard']}  ",
        f"**Generated:** {report['generated_at']}  ",
        f"**Filing institution:** {filer}",
        "",
        f"- **Subject:** `{subject or '—'}` ({chain or 'n/a'})",
        f"- **Aggregate amount:** ${total:,.2f}",
        f"- **Threshold:** ${threshold:,.2f}",
        f"- **Reportable:** {'YES — exceeds threshold' if reportable else 'No — below threshold'}",
        f"- **Transactions:** {len(transactions)}",
        "",
        "## Transactions",
        _md_table(
            ["Hash", "Date", "Amount (USD)", "Asset", "Direction"],
            [[t.get("hash", "—"), t.get("date", "—"), f"${float(t.get('amount_usd') or 0):,.2f}", t.get("asset", "—"), t.get("direction", "—")] for t in transactions],
        ),
        "---",
        "_DRAFT — review by a compliance officer required before filing._",
    ]
    report["markdown"] = "\n".join(lines)
    return report


# ---------------------------------------------------------------------------
# Travel Rule (FATF Recommendation 16 / IVMS101-style)
# ---------------------------------------------------------------------------
def generate_travel_rule(payload: dict[str, Any]) -> dict[str, Any]:
    originator = payload.get("originator") or {}
    beneficiary = payload.get("beneficiary") or {}
    chain = payload.get("chain") or ""
    amount = payload.get("amount") or ""
    asset = payload.get("asset") or ""
    tx_hash = payload.get("tx_hash") or ""

    orig_addr = (originator.get("address") or "").strip()
    benef_addr = (beneficiary.get("address") or "").strip()
    orig_vasp = vasp_directory.identify_vasp(orig_addr, chain) if orig_addr else {"is_vasp": False, "vasp": None}
    benef_vasp = vasp_directory.identify_vasp(benef_addr, chain) if benef_addr else {"is_vasp": False, "vasp": None}
    orig_sanc = sanctions_engine.screen_address(orig_addr, chain) if orig_addr else {"sanctioned": False, "matches": []}
    benef_sanc = sanctions_engine.screen_address(benef_addr, chain) if benef_addr else {"sanctioned": False, "matches": []}

    report = {
        "report_type": "TRAVEL_RULE",
        "report_standard": "FATF Recommendation 16 / IVMS101",
        "generated_at": _now(),
        "transfer": {"chain": chain, "asset": asset, "amount": amount, "tx_hash": tx_hash},
        "originator": {
            "name": originator.get("name", ""),
            "address": orig_addr,
            "vasp": orig_vasp["vasp"],
            "is_vasp": orig_vasp["is_vasp"],
            "sanctioned": orig_sanc["sanctioned"],
        },
        "beneficiary": {
            "name": beneficiary.get("name", ""),
            "address": benef_addr,
            "vasp": benef_vasp["vasp"],
            "is_vasp": benef_vasp["is_vasp"],
            "sanctioned": benef_sanc["sanctioned"],
        },
        "compliance": {
            "both_vasps_identified": orig_vasp["is_vasp"] and benef_vasp["is_vasp"],
            "sanctions_blocker": orig_sanc["sanctioned"] or benef_sanc["sanctioned"],
        },
    }
    o, b = report["originator"], report["beneficiary"]
    report["markdown"] = "\n".join([
        "# Travel Rule Message (DRAFT)",
        "",
        f"**Standard:** {report['report_standard']}  ",
        f"**Generated:** {report['generated_at']}",
        "",
        f"**Transfer:** {amount} {asset} on {chain or 'n/a'} — tx `{tx_hash or '—'}`",
        "",
        "## Originator",
        f"- **Name:** {o['name'] or '—'}",
        f"- **Address:** `{o['address'] or '—'}`",
        f"- **VASP:** {o['vasp']['name'] if o['vasp'] else '—'}",
        f"- **Sanctioned:** {'YES' if o['sanctioned'] else 'No'}",
        "",
        "## Beneficiary",
        f"- **Name:** {b['name'] or '—'}",
        f"- **Address:** `{b['address'] or '—'}`",
        f"- **VASP:** {b['vasp']['name'] if b['vasp'] else '—'}",
        f"- **Sanctioned:** {'YES' if b['sanctioned'] else 'No'}",
        "",
        "## Compliance",
        f"- **Both VASPs identified:** {'Yes' if report['compliance']['both_vasps_identified'] else 'No — counterparty VASP unknown'}",
        f"- **Sanctions blocker:** {'YES — DO NOT TRANSMIT' if report['compliance']['sanctions_blocker'] else 'None detected'}",
        "",
        "---",
        "_DRAFT — verify counterparty VASP and beneficiary details before transmitting._",
    ])
    return report


if __name__ == "__main__":
    sanctions_engine.init_sanctions_tables()
    vasp_directory.init_vasp_tables()
    out = generate_sar({
        "subject_address": "0x8589427373d6d84e98730d7795d8f6f8731fda16",
        "chain": "eth", "narrative": "Funds routed through Tornado Cash.",
        "activity_categories": ["Mixer / tumbler use", "Sanctions evasion"],
        "counterparties": ["0x28c6c06298d514db089934071355e5743bf21d60"],
        "total_amount_usd": 250000,
    })
    print(out["markdown"][:500])
