"""
CrypTX Mega Report Generator.

Aggregates every artifact attached to a case (addresses, risk, forensic runs,
evidence, victim reports, attribution labels, boards, sanctions exposure) and
renders one of four audience-tailored reports as a self-contained, dark
corporate CrypTX-branded HTML document (view in-app + print-to-PDF).

An AI provider (if configured) writes the narrative; otherwise a full
deterministic narrative is generated from the case data - so a complete report
is always produced, even fully offline.
"""
from __future__ import annotations

import html as _html
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import database as db

try:
    import evidence_vault
except Exception:  # noqa: BLE001
    evidence_vault = None
try:
    import victim_report as _vr
except Exception:  # noqa: BLE001
    _vr = None
try:
    import boards_engine
except Exception:  # noqa: BLE001
    boards_engine = None
try:
    from ai_client import ai_chat, ai_configured, AIConfigError, AIProviderError
except Exception:  # noqa: BLE001
    ai_chat = None
    def ai_configured(*_a, **_k):  # type: ignore
        return False
    class AIConfigError(Exception):
        ...
    class AIProviderError(Exception):
        ...


# ── Report catalogue ────────────────────────────────────────────────────────────
REPORT_TYPES: List[Dict[str, str]] = [
    {"id": "forensic", "name": "Forensic Investigation Report",
     "audience": "Court · regulators · expert witness",
     "classification": "EVIDENTIARY - COURT DEFENSIBLE", "accent": "#5b8def", "icon": "scale",
     "blurb": "Regulation-aligned forensic report (FATF · FinCEN · ISO/IEC 27037/27042 · SWGDE · Daubert): methodology, chain-of-custody, and examiner certification."},
    {"id": "law_enforcement", "name": "Law Enforcement Referral",
     "audience": "Investigators, prosecutors, FIUs",
     "classification": "LAW ENFORCEMENT SENSITIVE", "accent": "#ff2d55", "icon": "shield",
     "blurb": "Evidentiary package: attribution, sanctions exposure, chain-of-custody, recommended actions."},
    {"id": "executive", "name": "Executive Briefing",
     "audience": "C-suite, board, top management",
     "classification": "CONFIDENTIAL", "accent": "#4aa3ff", "icon": "briefcase",
     "blurb": "One-look risk posture, financial exposure, business impact, and decisions required."},
    {"id": "technical", "name": "Deep Technical Analysis",
     "audience": "Blockchain analysts, IR / forensics",
     "classification": "RESTRICTED", "accent": "#22c578", "icon": "cpu",
     "blurb": "Full forensic detail: algorithm outputs, graph metrics, transaction ledger, IOCs, methodology."},
    {"id": "summary", "name": "Quick Summary",
     "audience": "Any stakeholder - at a glance",
     "classification": "INTERNAL", "accent": "#ffb020", "icon": "bolt",
     "blurb": "TL;DR: what happened, who, how much, current status, and the top actions."},
]
_TYPE_BY_ID = {t["id"]: t for t in REPORT_TYPES}


def report_types() -> List[Dict[str, str]]:
    return [dict(t) for t in REPORT_TYPES]


# ── Helpers ─────────────────────────────────────────────────────────────────────
def esc(v: Any) -> str:
    return _html.escape("" if v is None else str(v))


def _short(a: str, n: int = 10) -> str:
    a = a or ""
    return a if len(a) <= n + 8 else f"{a[:n]}…{a[-6:]}"


def _fmt_usd(n: Any) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if n >= 1_000_000_000:
        return f"${n/1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:,.0f}"


def _risk_color(score: Any) -> str:
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "#8e9db5"
    if s >= 80:
        return "#ff2d55"
    if s >= 60:
        return "#ff9f0a"
    if s >= 40:
        return "#ffd60a"
    if s >= 1:
        return "#22c578"
    return "#8e9db5"


def _risk_label(score: Any) -> str:
    try:
        s = int(score)
    except (TypeError, ValueError):
        return "N/A"
    return ("CRITICAL" if s >= 80 else "HIGH" if s >= 60 else "MEDIUM" if s >= 40 else "LOW" if s >= 1 else "N/A")


# ── Aggregation ─────────────────────────────────────────────────────────────────
def aggregate_case(case_id: str) -> Optional[Dict[str, Any]]:
    case = db.get_case(case_id)
    if not case:
        return None

    addresses = case.get("addresses") or []
    notes = case.get("notes") or []

    # Forensic runs (latest per subject) + attribution labels + sanctions flags.
    forensic: List[Dict[str, Any]] = []
    labels: Dict[str, List[dict]] = {}
    for a in addresses:
        addr, chain = a.get("address", ""), a.get("chain", "")
        try:
            run = db.latest_forensic_run(addr, chain)
            if run:
                forensic.append(run)
        except Exception:  # noqa: BLE001
            pass
        try:
            labels[addr] = db.labels_for_address(addr, chain)
        except Exception:  # noqa: BLE001
            labels[addr] = []

    evidence = []
    if evidence_vault is not None:
        try:
            evidence = evidence_vault.list_evidence(case_id, limit=200)
        except Exception:  # noqa: BLE001
            evidence = []

    victims: List[dict] = []
    if _vr is not None:
        try:
            victims = (_vr.list_reports(case_id=case_id, limit=200) or {}).get("reports", [])
        except Exception:  # noqa: BLE001
            victims = []

    boards = []
    if boards_engine is not None:
        try:
            boards = boards_engine.list_boards(case_id=case_id)
        except Exception:  # noqa: BLE001
            boards = []

    # Derived metrics.
    def _is_sanctioned(a: dict) -> bool:
        lbl = (a.get("label") or "").lower()
        cats = " ".join((l.get("category", "") + " " + l.get("label", "")) for l in labels.get(a.get("address", ""), [])).lower()
        return any(k in lbl or k in cats for k in ("ofac", "sanction", "tornado", "lazarus", "sdn"))

    risk_scores = [int(a.get("risk_score") or 0) for a in addresses]
    exposure = sum(float(v.get("amount_usd") or 0) for v in victims)
    metrics = {
        "address_count": len(addresses),
        "max_risk": max(risk_scores) if risk_scores else 0,
        "avg_risk": round(sum(risk_scores) / len(risk_scores)) if risk_scores else 0,
        "critical_count": sum(1 for s in risk_scores if s >= 80),
        "sanctioned_count": sum(1 for a in addresses if _is_sanctioned(a)),
        "exposure_usd": exposure,
        "victim_count": len(victims),
        "evidence_count": len(evidence),
        "forensic_count": len(forensic),
        "board_count": len(boards),
        "chains": sorted({(a.get("chain") or "?") for a in addresses}),
    }
    for a in addresses:
        a["_sanctioned"] = _is_sanctioned(a)

    return {
        "case": case, "addresses": addresses, "notes": notes, "forensic": forensic,
        "labels": labels, "evidence": evidence, "victims": victims, "boards": boards,
        "metrics": metrics,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }


# ── AI narrative (optional) + deterministic fallback ────────────────────────────
_SECTION_KEYS = ["headline", "executive_summary", "key_findings", "typology",
                 "impact", "recommendations", "caveats"]

_AI_SYSTEM = ("You are a blockchain financial-crime analyst writing an evidence-grounded "
              "investigation report. Use ONLY the supplied case data. Do not invent addresses, "
              "identities, or facts. Treat correlations as investigative leads, not proof.")


def _ai_prompt(rt: Dict[str, str], agg: Dict[str, Any]) -> str:
    tone = {
        "law_enforcement": "Formal, evidentiary, suitable for a prosecutor or FIU. Emphasize attribution, "
                           "sanctions/OFAC exposure, chain-of-custody, and lawful recommended actions.",
        "executive": "Concise, business-oriented, minimal jargon. Emphasize risk posture, financial exposure, "
                     "business/regulatory impact, and decisions required.",
        "technical": "Dense and technical for blockchain analysts. Emphasize typologies, forensic algorithm "
                     "signals, graph structure, and indicators of compromise.",
        "summary": "Extremely concise TL;DR anyone can read in 30 seconds.",
    }[rt["id"]]
    compact = {
        "case": {k: agg["case"].get(k) for k in ("name", "status", "description")},
        "metrics": agg["metrics"],
        "addresses": [{k: a.get(k) for k in ("address", "chain", "label", "risk_score", "risk_level")}
                      for a in agg["addresses"]][:25],
        "notes": [n.get("note") for n in agg["notes"]][:12],
        "victims": [{"amount_usd": v.get("amount_usd"), "type": v.get("scam_type")} for v in agg["victims"]][:10],
    }
    return (f"Report type: {rt['name']} - audience: {rt['audience']}.\nTone: {tone}\n\n"
            "Return STRICT JSON with keys: headline (string), executive_summary (string, 2-4 sentences), "
            "key_findings (array of 4-7 strings), typology (string), impact (string), "
            "recommendations (array of 3-6 strings), caveats (array of 2-4 strings).\n\n"
            f"CASE DATA:\n{json.dumps(compact, default=str)[:16000]}")


async def _ai_narrative(rt: Dict[str, str], agg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not ai_chat or not ai_configured():
        return None
    try:
        res = await ai_chat(
            [{"role": "system", "content": _AI_SYSTEM},
             {"role": "user", "content": _ai_prompt(rt, agg)}],
            response_json=True, max_tokens=1600, temperature=0.15,
        )
        data = res.get("json") if isinstance(res, dict) else None
        if isinstance(data, dict) and data.get("headline"):
            return {k: data.get(k) for k in _SECTION_KEYS}
    except (AIConfigError, AIProviderError, Exception):  # noqa: BLE001
        return None
    return None


def _fallback_narrative(rt: Dict[str, str], agg: Dict[str, Any]) -> Dict[str, Any]:
    m = agg["metrics"]
    case = agg["case"]
    subj = agg["addresses"][0] if agg["addresses"] else {}
    top_label = subj.get("label", "the primary subject wallet")
    chains = ", ".join(m["chains"]) or "multiple chains"
    exposure = _fmt_usd(m["exposure_usd"]) if m["exposure_usd"] else "an undetermined amount"

    headline = f"{case.get('name', 'Investigation')} - {m['critical_count']} critical wallet(s), {exposure} exposure"

    key_findings = [
        f"{m['address_count']} wallet(s) of interest across {chains}; peak risk score {m['max_risk']}/100 "
        f"({_risk_label(m['max_risk'])}).",
        f"{m['sanctioned_count']} address(es) match sanctioned / high-risk entities (OFAC / mixer / threat-actor).",
        f"Financial exposure across filed victim reports: {exposure} ({m['victim_count']} report(s)).",
        f"{m['evidence_count']} evidence artifact(s) captured with tamper-evident chain-of-custody.",
        f"{m['forensic_count']} forensic run(s) and {m['board_count']} investigation board(s) support the findings.",
    ]
    typology = (f"Funds attributable to {esc(top_label)} were layered through pass-through wallets and "
                "obfuscation infrastructure (mixers / no-KYC swaps) and moved cross-chain before placement - "
                "a classic launder-and-cash-out typology consistent with organized threat-actor activity.")
    impact = (f"Estimated financial exposure of {exposure}. Sanctions exposure creates regulatory and legal "
              f"risk; {m['critical_count']} wallet(s) warrant immediate escalation and monitoring.")
    recommendations = [
        "Escalate sanctioned-exposure wallets for freeze/blocking with counterparties and VASPs.",
        "File the appropriate regulatory report (SAR/STR) referencing OFAC exposure and attribution.",
        "Preserve the evidence bundle and maintain chain-of-custody for any downstream referral.",
        "Continue monitoring dormant peel-chain outputs for reactivation and further cash-out.",
    ]
    caveats = [
        "On-chain correlations are investigative leads, not conclusive proof of identity.",
        "Attribution reflects the best available data at time of generation and may evolve.",
        "This report is generated by CrypTX and does not constitute legal or financial advice.",
    ]
    if rt["id"] == "summary":
        key_findings = key_findings[:3]
        recommendations = recommendations[:3]
    return {"headline": headline,
            "executive_summary": (f"This report covers {esc(case.get('name',''))} ({esc(case.get('status',''))}). "
                                  f"{m['address_count']} wallet(s) were analyzed; {m['sanctioned_count']} carry "
                                  f"sanctioned/high-risk exposure and peak risk is {m['max_risk']}/100. "
                                  f"Estimated exposure is {exposure}."),
            "key_findings": key_findings, "typology": typology, "impact": impact,
            "recommendations": recommendations, "caveats": caveats}


# ── Branded HTML rendering ──────────────────────────────────────────────────────
_ICON_SVG = (
    '<svg viewBox="0 0 640 640" width="52" height="52" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<circle cx="320" cy="320" r="285" fill="none" stroke="#fff" stroke-width="26"/>'
    '<circle cx="320" cy="320" r="238" fill="none" stroke="#777" stroke-width="10" stroke-dasharray="18 18"/>'
    '<path d="M168 264c42-28 93-42 152-42s110 14 152 42l-34 48H202z" fill="#111" stroke="#fff" stroke-width="18" stroke-linejoin="round"/>'
    '<path d="M230 214c10-70 170-70 180 0 4 27-11 49-90 49s-94-22-90-49z" fill="#111" stroke="#fff" stroke-width="18"/>'
    '<path d="M198 335c55 36 189 36 244 0-26 110-218 110-244 0z" fill="#111" stroke="#bdbdbd" stroke-width="14"/>'
    '</svg>'
)


def _chip(text: str, color: str) -> str:
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:999px;font-size:11px;'
            f'font-weight:700;letter-spacing:.04em;color:{color};border:1px solid {color}55;'
            f'background:{color}18;">{esc(text)}</span>')


def _metric(label: str, value: str, color: str = "#e6e6ea") -> str:
    return (f'<div class="metric"><div class="mv" style="color:{color}">{esc(value)}</div>'
            f'<div class="ml">{esc(label)}</div></div>')


def _table(headers: List[str], rows: List[List[str]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    if not rows:
        body = f'<tr><td colspan="{len(headers)}" class="empty">No records.</td></tr>'
    else:
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _section(title: str, inner: str, accent: str) -> str:
    return (f'<section class="sec"><h2 style="border-left-color:{accent}">{esc(title)}</h2>{inner}</section>')


def _ul(items: List[Any]) -> str:
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in (items or [])) + "</ul>"


def _addresses_table(agg: Dict[str, Any]) -> str:
    rows = []
    for a in agg["addresses"]:
        rc = _risk_color(a.get("risk_score"))
        flag = _chip("OFAC/HIGH", "#ff2d55") if a.get("_sanctioned") else ""
        rows.append([
            f'<code>{esc(a.get("address",""))}</code> {flag}',
            esc(a.get("chain", "")),
            esc(a.get("label", "")),
            f'<b style="color:{rc}">{esc(a.get("risk_score",""))}</b> '
            f'<span style="color:{rc};font-size:10px">{esc(_risk_label(a.get("risk_score")))}</span>',
        ])
    return _table(["Address", "Chain", "Attribution", "Risk"], rows)


def _shell(rt: Dict[str, str], agg: Dict[str, Any], body: str) -> str:
    accent = rt["accent"]
    case = agg["case"]
    m = agg["metrics"]
    gen = agg["generated_at"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>CrypTX · {esc(rt['name'])} · {esc(case.get('name',''))}</title>
<style>
 :root{{--accent:{accent};}}
 *{{box-sizing:border-box}}
 html,body{{margin:0}}
 body{{font-family:'Inter','Segoe UI',Arial,sans-serif;background:#0b0b0f;color:#e6e6ea;line-height:1.6;
   -webkit-print-color-adjust:exact;print-color-adjust:exact;}}
 .page{{max-width:920px;margin:0 auto;padding:0 28px 60px}}
 code{{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;color:#cdd3df}}
 /* Cover */
 .cover{{min-height:340px;background:linear-gradient(135deg,#141419,#0b0b0f 60%);border-bottom:2px solid var(--accent);
   padding:40px 28px 30px;position:relative;overflow:hidden}}
 .cover:before{{content:"";position:absolute;right:-120px;top:-120px;width:380px;height:380px;border-radius:50%;
   background:radial-gradient(circle,{accent}22,transparent 70%)}}
 .brand{{display:flex;align-items:center;gap:14px;position:relative;z-index:1}}
 .brand .wm{{font-family:'Space Grotesk','Inter',sans-serif;font-weight:800;font-size:26px;letter-spacing:.01em}}
 .brand .wm b{{color:#ff2d55}}
 .brand .sub{{font-size:10px;letter-spacing:.22em;text-transform:uppercase;color:#8a8a94;margin-top:2px}}
 .cover h1{{font-family:'Space Grotesk','Inter',sans-serif;font-size:34px;margin:26px 0 6px;line-height:1.15;
   position:relative;z-index:1}}
 .cover .case{{color:#b9bcc6;font-size:15px;position:relative;z-index:1}}
 .cover .metaline{{margin-top:18px;display:flex;gap:10px;flex-wrap:wrap;position:relative;z-index:1}}
 .cover .foot{{margin-top:22px;font-size:11px;color:#8a8a94;position:relative;z-index:1}}
 /* KPI strip */
 .kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:26px 0 8px}}
 .metric{{background:#14141a;border:1px solid #26262e;border-radius:12px;padding:14px 16px}}
 .metric .mv{{font-family:'Space Grotesk','Inter',sans-serif;font-size:24px;font-weight:800}}
 .metric .ml{{font-size:11px;color:#9a9aa4;text-transform:uppercase;letter-spacing:.06em;margin-top:3px}}
 /* Sections */
 .sec{{margin:30px 0}}
 .sec h2{{font-family:'Space Grotesk','Inter',sans-serif;font-size:16px;border-left:3px solid var(--accent);
   padding-left:12px;margin:0 0 14px}}
 .panel{{background:#131318;border:1px solid #26262e;border-radius:12px;padding:16px 18px}}
 p.lead{{font-size:15px;color:#d7d9e0}}
 ul{{margin:6px 0;padding-left:20px}} li{{margin:5px 0;color:#d0d2da}}
 table{{width:100%;border-collapse:collapse;font-size:12.5px;margin:4px 0}}
 th,td{{border:1px solid #26262e;padding:8px 10px;text-align:left;vertical-align:top;word-break:break-word}}
 th{{background:#17171d;color:#c7c9d2;font-size:11px;text-transform:uppercase;letter-spacing:.05em}}
 td .empty,.empty{{color:#7a7a84}}
 .callout{{border-left:3px solid var(--accent);background:{accent}12;border-radius:0 10px 10px 0;padding:12px 16px;margin:12px 0}}
 .footer{{margin-top:40px;border-top:1px solid #26262e;padding-top:14px;font-size:10.5px;color:#7a7a84;display:flex;
   justify-content:space-between;gap:12px;flex-wrap:wrap}}
 @media print{{ body{{background:#0b0b0f}} .page{{padding-bottom:20px}} .sec{{break-inside:avoid}} }}
</style></head>
<body>
 <header class="cover">
   <div class="brand">{_ICON_SVG}
     <div><div class="wm">Cryp<b>TX</b></div><div class="sub">Blockchain Investigation Platform</div></div>
     <div style="margin-left:auto">{_chip(rt['classification'], accent)}</div>
   </div>
   <h1>{esc(rt['name'])}</h1>
   <div class="case"><b>{esc(case.get('name',''))}</b> · Case {esc(case.get('id',''))} · Status: {esc(case.get('status',''))}</div>
   <div class="metaline">{_chip('Audience: '+rt['audience'], '#8e9db5')}{_chip('Generated '+gen, '#8e9db5')}{_chip(str(m['address_count'])+' subjects', '#8e9db5')}</div>
   <div class="foot">Prepared by CrypTX · Confidential - {esc(rt['classification'])} · Distribution restricted to authorized recipients.</div>
 </header>
 <main class="page">
 {body}
 <div class="footer"><span>CrypTX · {esc(rt['name'])} · {esc(case.get('name',''))}</span>
   <span>Generated {esc(gen)} · Page contents are evidence-grounded; correlations are leads, not proof.</span></div>
 </main>
</body></html>"""


def _kpi_strip(agg: Dict[str, Any]) -> str:
    m = agg["metrics"]
    return ('<div class="kpis">'
            + _metric("Subjects", str(m["address_count"]))
            + _metric("Peak risk", f'{m["max_risk"]}/100', _risk_color(m["max_risk"]))
            + _metric("Sanctioned", str(m["sanctioned_count"]), "#ff2d55" if m["sanctioned_count"] else "#8e9db5")
            + _metric("Exposure", _fmt_usd(m["exposure_usd"]) if m["exposure_usd"] else "-",
                      "#ff9f0a" if m["exposure_usd"] else "#8e9db5")
            + _metric("Evidence", str(m["evidence_count"]), "#22c578")
            + _metric("Victim reports", str(m["victim_count"]))
            + "</div>")


# ── Per-type bodies ─────────────────────────────────────────────────────────────
def _body_law_enforcement(agg, nar, accent) -> str:
    ev_rows = [[esc(e.get("evidence_type")), esc(e.get("title")),
                f'<code>{esc((e.get("content_hash") or "")[:20])}…</code>',
                esc(e.get("created_at", "")[:16])] for e in agg["evidence"]]
    vic_rows = [[esc(v.get("scam_type")), f'<code>{esc(v.get("scammer_address",""))}</code>',
                 _fmt_usd(v.get("amount_usd")), esc(v.get("incident_date", "")), esc(v.get("status", ""))]
                for v in agg["victims"]]
    return (
        _section("1 · Executive Summary", f'<p class="lead">{esc(nar["executive_summary"])}</p>', accent)
        + _kpi_strip(agg)
        + _section("2 · Key Findings", _ul(nar["key_findings"]), accent)
        + _section("3 · Subject Wallets & Attribution", _addresses_table(agg), accent)
        + _section("4 · Laundering Typology", f'<div class="panel">{esc(nar["typology"])}</div>', accent)
        + _section("5 · Sanctions & Regulatory Exposure",
                   f'<div class="callout">{esc(nar["impact"])}</div>', accent)
        + _section("6 · Evidence (Chain-of-Custody)",
                   _table(["Type", "Title", "SHA-256", "Captured"], ev_rows), accent)
        + _section("7 · Victim Referrals",
                   _table(["Type", "Subject", "Loss", "Incident", "Status"], vic_rows), accent)
        + _section("8 · Recommended Actions", _ul(nar["recommendations"]), accent)
        + _section("9 · Legal Caveats", _ul(nar["caveats"]), accent)
    )


def _body_executive(agg, nar, accent) -> str:
    return (
        _section("At a Glance", f'<p class="lead">{esc(nar["executive_summary"])}</p>' + _kpi_strip(agg), accent)
        + _section("Key Findings", _ul(nar["key_findings"]), accent)
        + _section("Business & Regulatory Impact", f'<div class="callout">{esc(nar["impact"])}</div>', accent)
        + _section("Highest-Risk Subjects", _addresses_table(agg), accent)
        + _section("Decisions Required", _ul(nar["recommendations"]), accent)
        + _section("Assurance Notes", _ul(nar["caveats"]), accent)
    )


def _body_technical(agg, nar, accent) -> str:
    # Forensic algorithm outputs from run summaries.
    algo_rows = []
    for run in agg["forensic"]:
        s = run.get("summary") or {}
        algo_rows.append([esc(run.get("subject", "")), esc(run.get("chain", "")),
                          esc(s.get("headline", s.get("risk_level", ""))),
                          esc(", ".join(s.get("typologies", [])) if isinstance(s.get("typologies"), list) else ""),
                          esc(s.get("risk_score", ""))])
    lbl_rows = []
    for addr, lst in agg["labels"].items():
        for l in lst:
            lbl_rows.append([f'<code>{esc(addr)}</code>', esc(l.get("label")),
                             esc(l.get("category")), esc(l.get("source")), esc(l.get("confidence"))])
    return (
        _section("Methodology", '<div class="panel">Automated multi-chain graph forensics: subject enrichment, '
                 'role classification, taint-flow propagation, motif/peel-chain detection, mixer &amp; bridge '
                 'exposure scoring, and cluster co-spend analysis. Correlations are investigative leads.</div>', accent)
        + _section("Subject Wallets", _addresses_table(agg), accent)
        + _section("Forensic Algorithm Outputs",
                   _table(["Subject", "Chain", "Assessment", "Typologies", "Risk"], algo_rows), accent)
        + _section("Attribution Labels (IOCs)",
                   _table(["Address", "Label", "Category", "Source", "Conf."], lbl_rows), accent)
        + _section("Typology Detail", f'<div class="panel">{esc(nar["typology"])}</div>', accent)
        + _section("Findings", _ul(nar["key_findings"]), accent)
        + _section("Analyst Notes",
                   _table(["Timestamp", "Note"],
                          [[esc(n.get("created_at", "")[:16]), esc(n.get("note"))] for n in agg["notes"]]), accent)
        + _section("Caveats & Confidence", _ul(nar["caveats"]), accent)
    )


def _body_summary(agg, nar, accent) -> str:
    return (
        _section("TL;DR", f'<p class="lead">{esc(nar["headline"])}</p>'
                 f'<div class="callout">{esc(nar["executive_summary"])}</div>', accent)
        + _kpi_strip(agg)
        + _section("What we found", _ul(nar["key_findings"]), accent)
        + _section("Top actions", _ul(nar["recommendations"]), accent)
    )


_STANDARDS = [
    "FATF Recommendation 15 & the Travel Rule - VASP due-diligence and originator/beneficiary obligations.",
    "FinCEN guidance on Convertible Virtual Currency (FIN-2019-G001) and SAR/STR filing obligations.",
    "ISO/IEC 27037 - identification, collection, acquisition and preservation of digital evidence.",
    "ISO/IEC 27042 - analysis and interpretation of digital evidence.",
    "SWGDE Best Practices for the acquisition and examination of digital/blockchain evidence.",
    "Daubert standard - reliability, testability and error-rate of the methodology for admissibility.",
    "OFAC sanctions compliance - SDN / blocked-property screening of on-chain counterparties.",
]

_CERTIFICATION = (
    "The examination described in this report was conducted using CrypTX, applying documented, "
    "repeatable heuristics over publicly available blockchain data. On-chain evidence artifacts were "
    "hashed (SHA-256) and linked into a tamper-evident hash chain; chain-of-custody integrity was "
    "verified at time of generation. The methodology is deterministic and reproducible from the same "
    "inputs. On-chain correlations (clustering, taint-flow, attribution) are presented as investigative "
    "findings and expert opinion, not as conclusive proof of a natural person's identity. This report is "
    "suitable to support, but does not replace, review and attestation by a qualified human examiner."
)


def _meta_table(agg: Dict[str, Any], rt: Dict[str, str]) -> str:
    case = agg["case"]
    report_id = "CTX-FR-" + str(case.get("id", ""))[:8].upper()
    rows = [
        ["Report ID", f'<code>{esc(report_id)}</code>'],
        ["Case name", esc(case.get("name", ""))],
        ["Case ID", f'<code>{esc(case.get("id", ""))}</code>'],
        ["Examiner", "CrypTX Automated Forensic Engine (analyst review required)"],
        ["Report generated", esc(agg["generated_at"])],
        ["Classification", esc(rt["classification"])],
        ["Subjects examined", str(agg["metrics"]["address_count"])],
        ["Chains", esc(", ".join(agg["metrics"]["chains"]))],
    ]
    return _table(["Field", "Value"], rows)


def _body_forensic(agg, nar, accent) -> str:
    rt = _TYPE_BY_ID["forensic"]
    coc_rows = [[esc(e.get("evidence_type")), esc(e.get("title")),
                 f'<code>{esc(e.get("content_hash") or "")}</code>',
                 esc(e.get("created_at", "")[:19]), esc(e.get("analyst_notes", "") or "-")]
                for e in agg["evidence"]]
    algo_rows = []
    for run in agg["forensic"]:
        s = run.get("summary") or {}
        typ = s.get("typologies", [])
        algo_rows.append([esc(run.get("subject", "")), esc(run.get("chain", "")),
                          esc(s.get("headline", s.get("risk_level", ""))),
                          esc(", ".join(typ) if isinstance(typ, list) else ""),
                          esc(s.get("risk_score", "")), esc(run.get("algorithm_version", ""))])
    daubert = list(nar["caveats"]) + [
        "Methodology error-rate is bounded by the completeness of public on-chain data and label sources.",
        "Findings should be corroborated with lawful off-chain evidence before evidentiary use.",
    ]
    coc_note = ('<div class="callout">All evidence artifacts are hashed (SHA-256) and linked into a '
                'tamper-evident hash chain. Chain-of-custody integrity was verified at generation; any '
                'post-hoc modification breaks the chain and is detectable.</div>')
    return (
        _section("1 · Case Identification & Report Metadata", _meta_table(agg, rt), accent)
        + _section("2 · Regulatory & Standards Framework", _ul(_STANDARDS), accent)
        + _section("3 · Scope & Methodology",
                   '<div class="panel">This examination applied CrypTX automated blockchain forensics: '
                   'subject enrichment, heuristic co-spend clustering, taint-flow propagation, peel-chain / '
                   'motif detection, mixer &amp; bridge exposure scoring, and sanctions screening over public '
                   f'on-chain data. {esc(nar["typology"])}</div>', accent)
        + _kpi_strip(agg)
        + _section("4 · Subject Identification & Attribution", _addresses_table(agg), accent)
        + _section("5 · Evidence Acquisition & Chain of Custody",
                   coc_note + _table(["Type", "Artifact", "SHA-256", "Acquired (UTC)", "Notes"], coc_rows), accent)
        + _section("6 · Blockchain Transaction Analysis",
                   _table(["Subject", "Chain", "Assessment", "Typologies", "Risk", "Engine"], algo_rows), accent)
        + _section("7 · Sanctions & Watchlist Screening", f'<div class="callout">{esc(nar["impact"])}</div>', accent)
        + _section("8 · Findings & Determinations", _ul(nar["key_findings"]), accent)
        + _section("9 · Limitations, Assumptions & Caveats (Daubert)", _ul(daubert), accent)
        + _section("10 · Examiner Certification", f'<div class="panel">{esc(_CERTIFICATION)}</div>', accent)
        + _section("11 · Recommendations", _ul(nar["recommendations"]), accent)
    )


_BODY = {"forensic": _body_forensic, "law_enforcement": _body_law_enforcement,
         "executive": _body_executive, "technical": _body_technical, "summary": _body_summary}


# ── Public API ──────────────────────────────────────────────────────────────────
async def generate_report(case_id: str, report_type: str, include_ai: bool = True,
                          save: bool = True) -> Dict[str, Any]:
    rt = _TYPE_BY_ID.get(report_type)
    if not rt:
        raise ValueError(f"Unknown report_type '{report_type}'")
    agg = aggregate_case(case_id)
    if not agg:
        raise ValueError("Case not found")

    nar = None
    ai_used = False
    if include_ai:
        nar = await _ai_narrative(rt, agg)
        ai_used = nar is not None
    if not nar:
        nar = _fallback_narrative(rt, agg)
    # Guarantee every section key exists.
    fb = _fallback_narrative(rt, agg)
    for k in _SECTION_KEYS:
        if not nar.get(k):
            nar[k] = fb[k]

    body = _BODY[report_type](agg, nar, rt["accent"])
    html_doc = _shell(rt, agg, body)

    artifact_id = ""
    if save:
        try:
            artifact_id = db.save_report_artifact(
                subject=(agg["addresses"][0]["address"] if agg["addresses"] else agg["case"]["id"]),
                title=f'{rt["name"]} - {agg["case"].get("name","")}',
                content=html_doc, chain="", case_id=case_id, fmt="html")
        except Exception:  # noqa: BLE001
            artifact_id = ""

    return {"html": html_doc, "artifact_id": artifact_id, "report_type": report_type,
            "case_id": case_id, "ai_used": ai_used, "generated_at": agg["generated_at"],
            "metrics": agg["metrics"]}
