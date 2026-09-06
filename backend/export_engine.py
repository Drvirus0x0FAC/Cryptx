"""
Export engine — native PDF, DOCX, and FinCEN BSA E-Filing XML generation.

Replaces the browser-print-only reporting with deterministic server-side export so
compliance officers and counsel get editable, submittable artifacts.

Outputs:
  - PDF  (via WeasyPrint if available, else a robust HTML→PDF fallback using reportlab
          when present; degrades to returning print-ready HTML if neither is installed)
  - DOCX (via python-docx if available)
  - FinCEN BSA E-Filing XML (SAR / CTR) — pure stdlib, always available
  - STIX 2.1 bundle — pure stdlib, always available
  - MISP event JSON — pure stdlib, always available

All generators degrade gracefully: if a library is missing, the caller gets back a
descriptive error rather than a crash, and HTML fallback is always offered.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from html import escape
from typing import Any, Optional

import database as db

log = logging.getLogger("export_engine")

# ── Capability detection (lazy, cached) ───────────────────────────────────────

_PDF_ENGINE: Optional[str] = None
_DOCX_ENGINE: Optional[str] = None


def pdf_engine() -> Optional[str]:
    global _PDF_ENGINE
    if _PDF_ENGINE is not None:
        return _PDF_ENGINE if _PDF_ENGINE != "none" else None
    try:
        import weasyprint  # noqa: F401
        _PDF_ENGINE = "weasyprint"
        return _PDF_ENGINE
    except Exception:
        pass
    try:
        from reportlab.pdfgen import canvas  # noqa: F401
        _PDF_ENGINE = "reportlab"
        return _PDF_ENGINE
    except Exception:
        _PDF_ENGINE = "none"
        return None


def docx_engine() -> Optional[str]:
    global _DOCX_ENGINE
    if _DOCX_ENGINE is not None:
        return _DOCX_ENGINE if _DOCX_ENGINE != "none" else None
    try:
        import docx  # noqa: F401  (python-docx)
        _DOCX_ENGINE = "python-docx"
        return _DOCX_ENGINE
    except Exception:
        _DOCX_ENGINE = "none"
        return None


# ── PDF ───────────────────────────────────────────────────────────────────────

def export_pdf(html_content: str, title: str = "CrypTX Report") -> tuple[bytes, str]:
    """Convert HTML report content to PDF bytes.

    Returns (pdf_bytes, engine_used). Raises RuntimeError if no PDF engine available.
    """
    eng = pdf_engine()
    if eng == "weasyprint":
        from weasyprint import HTML
        pdf = HTML(string=html_content).write_pdf()
        return pdf, "weasyprint"
    if eng == "reportlab":
        return _reportlab_pdf(html_content, title), "reportlab"
    raise RuntimeError(
        "No PDF engine installed. Install weasyprint (recommended) or reportlab, "
        "or use the HTML endpoint with browser print-to-PDF."
    )


def _reportlab_pdf(html_content: str, title: str) -> bytes:
    """Fallback PDF: strip HTML and lay out as plain text via reportlab."""
    import io
    import re
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.units import inch

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                            title=title, author="CrypTX")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("CrypH1", parent=styles["Heading1"], fontSize=18, spaceAfter=12,
                        textColor="#dc2626")
    body = ParagraphStyle("CrypBody", parent=styles["BodyText"], fontSize=9, leading=12)

    # crude HTML→flowables: split on headings/paragraphs
    text = re.sub(r"<script.*?</script>", "", html_content, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    parts = re.split(r"<(h[1-6]|/h[1-6]|p|/p|br\s*/?)[^>]*>", text)
    flow = [Paragraph(escape(title), h1), Spacer(1, 0.2 * inch)]
    for chunk in parts:
        chunk = re.sub(r"<[^>]+>", "", chunk).strip()
        if chunk:
            flow.append(Paragraph(escape(chunk), body))
            flow.append(Spacer(1, 6))
    doc.build(flow)
    return buf.getvalue()


# ── DOCX ──────────────────────────────────────────────────────────────────────

def export_docx(case_data: dict, report_data: dict, title: str = "CrypTX Report") -> bytes:
    """Generate an editable Word document from case + report data.

    The DOCX mirrors the structure of the HTML report (executive summary, addresses,
    risk signals, evidence, narrative) so counsel can edit and redact before filing.
    """
    if not docx_engine():
        raise RuntimeError("python-docx not installed. Install with: pip install python-docx")
    from docx import Document
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    import io
    buf = io.BytesIO()
    doc = Document()

    # Title
    h = doc.add_heading(title, level=0)
    for run in h.runs:
        run.font.color.rgb = RGBColor(0xDC, 0x26, 0x26)
    sub = doc.add_paragraph(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    sub.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in sub.runs:
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    # Case metadata
    doc.add_heading("Case", level=1)
    doc.add_paragraph(f"Name: {case_data.get('name', '—')}")
    doc.add_paragraph(f"Status: {case_data.get('status', '—')}")
    if case_data.get("description"):
        doc.add_paragraph(case_data["description"])

    # Addresses
    addrs = case_data.get("addresses") or []
    if addrs:
        doc.add_heading("Addresses under Investigation", level=1)
        table = doc.add_table(rows=1, cols=4)
        table.style = "Light Grid Accent 1"
        hdr = table.rows[0].cells
        hdr[0].text = "Address"
        hdr[1].text = "Chain"
        hdr[2].text = "Risk"
        hdr[3].text = "Label"
        for a in addrs:
            row = table.add_row().cells
            row[0].text = str(a.get("address", ""))
            row[1].text = str(a.get("chain", ""))
            row[2].text = f"{a.get('risk_score', -1)} ({a.get('risk_level', '')})"
            row[3].text = str(a.get("label", ""))

    # Narrative / key findings
    doc.add_heading("Investigation Narrative", level=1)
    narrative = report_data.get("narrative") or {}
    for section_key in ("headline", "executive_summary", "key_findings",
                        "typology", "impact", "recommendations", "caveats"):
        val = narrative.get(section_key)
        if not val:
            continue
        doc.add_heading(section_key.replace("_", " ").title(), level=2)
        if isinstance(val, list):
            for item in val:
                doc.add_paragraph(str(item), style="List Bullet")
        else:
            doc.add_paragraph(str(val))

    # Risk signals
    risk = report_data.get("risk") or {}
    signals = risk.get("signals") or []
    if signals:
        doc.add_heading("Risk Signals", level=1)
        for sig in signals[:30]:
            doc.add_paragraph(
                f"{sig.get('category', '?')} — {sig.get('detail', '')} "
                f"(score +{sig.get('score', 0)})",
                style="List Bullet",
            )

    # Footer disclaimer
    doc.add_page_break()
    doc.add_heading("Disclaimer", level=1)
    p = doc.add_paragraph(
        "This report was generated by the CrypTX investigation platform. Heuristic and "
        "AI-derived findings are investigative leads, not proof of real-world identity or "
        "wrongdoing. All attributions must be independently corroborated before use in any "
        "legal, regulatory, or enforcement action. Deterministic findings (sanctions matches, "
        "contract-registry attributions) are labeled as such."
    )
    for run in p.runs:
        run.font.size = Pt(8)
        run.italic = True

    doc.save(buf)
    return buf.getvalue()


# ── FinCEN BSA E-Filing XML (SAR / CTR) ───────────────────────────────────────
# Generates an XML document structured for FinCEN's BSA E-Filing system.
# This is a structured-data representation; actual filing requires a registered
# FinCEN BSA E-Filing account and may need schema-version adjustments.

FINCEN_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<fincen_doc>
  <Header>
    <Form>{form_type}</Form>
    <SubmittedBy>{submitted_by}</SubmittedBy>
    <SubmittedOn>{submitted_on}</SubmittedOn>
    <ActivityRange>
      <Begin>{activity_start}</Begin>
      <End>{activity_end}</End>
    </ActivityRange>
    <CaseId>{case_id}</CaseId>
    <GeneratedBy>CrypTX Investigation Platform</GeneratedBy>
    <Disclaimer>Auto-generated draft — review by compliance officer before submission.</Disclaimer>
  </Header>
  <FilingInstitution>
    <Name>{institution_name}</Name>
    <EIN>{ein}</EIN>
    <Address>{address}</Address>
  </FilingInstitution>
  <Subject>
    <Address>{subject_address}</Address>
    <Chain>{subject_chain}</Chain>
    <EntityName>{subject_entity}</EntityName>
    <SanctionsMatch>{sanctions_match}</SanctionsMatch>
    <RiskScore>{risk_score}</RiskScore>
  </Subject>
  <Activity>
    <Type>{activity_type}</Type>
    <Narrative>{narrative}</Narrative>
    <TotalUSD>{total_usd}</TotalUSD>
    <TransactionCount>{tx_count}</TransactionCount>
  </Activity>
  <Counterparties>
{counterparties_xml}  </Counterparties>
  <RedFlags>
{red_flags_xml}  </RedFlags>
</fincen_doc>
"""


def export_fincen_xml(payload: dict) -> str:
    """Generate a FinCEN BSA E-Filing SAR or CTR draft as XML.

    payload keys:
      form_type: "SAR" | "CTR"
      case_id, submitted_by, institution_name, ein, address
      activity_start, activity_end, activity_type, narrative, total_usd, tx_count
      subject: {address, chain, entity, sanctions_match, risk_score}
      counterparties: [{address, chain, entity, direction, value_usd}]
      red_flags: [str]

    Consolidation: when form_type is SAR and a subject address is provided, this
    auto-enriches via regulatory_reports.generate_sar (sanctions + VASP context)
    so there is a single SAR-logic source. The raw payload fields are still
    honored as overrides.
    """
    # ── Consolidation: enrich SAR via regulatory_reports (single logic source) ──
    form_type = str(payload.get("form_type", "SAR")).upper()
    subject = payload.get("subject") or {}
    if form_type == "SAR" and subject.get("address") and not payload.get("_skip_enrich"):
        try:
            import regulatory_reports
            sar = regulatory_reports.generate_sar({
                "subject_address": subject.get("address", ""),
                "chain": subject.get("chain", ""),
                "narrative": payload.get("narrative", ""),
                "counterparties": [cp.get("address", "") for cp in (payload.get("counterparties") or [])],
                "total_amount_usd": payload.get("total_usd", 0),
                "case_id": payload.get("case_id", ""),
            })
            # merge enriched data back into payload (enriched values fill gaps)
            sar_subject = sar.get("subject") or {}
            payload.setdefault("red_flags", [])
            payload["red_flags"] = list(payload["red_flags"]) + [
                f["label"] for f in (sar.get("auto_flags") or []) if f.get("label")
            ]
            if sar_subject.get("sanctions_match") and not subject.get("sanctions_match"):
                subject["sanctions_match"] = "true"
            if not payload.get("counterparties") and sar.get("counterparties"):
                payload["counterparties"] = sar["counterparties"]
        except Exception:
            pass  # enrichment is best-effort; fall back to raw payload

    cp_lines = []
    for cp in (payload.get("counterparties") or [])[:50]:
        cp_lines.append(
            f"    <Counterparty>\n"
            f"      <Address>{escape(str(cp.get('address', '')))}</Address>\n"
            f"      <Chain>{escape(str(cp.get('chain', '')))}</Chain>\n"
            f"      <Entity>{escape(str(cp.get('entity', '')))}</Entity>\n"
            f"      <Direction>{escape(str(cp.get('direction', '')))}</Direction>\n"
            f"      <ValueUSD>{cp.get('value_usd', 0)}</ValueUSD>\n"
            f"    </Counterparty>"
        )
    rf_lines = [f"    <Flag>{escape(str(f))}</Flag>" for f in (payload.get("red_flags") or [])[:50]]
    subject = payload.get("subject") or {}
    return FINCEN_TEMPLATE.format(
        form_type=escape(str(payload.get("form_type", "SAR"))),
        submitted_by=escape(str(payload.get("submitted_by", ""))),
        submitted_on=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        activity_start=escape(str(payload.get("activity_start", ""))),
        activity_end=escape(str(payload.get("activity_end", ""))),
        case_id=escape(str(payload.get("case_id", ""))),
        institution_name=escape(str(payload.get("institution_name", ""))),
        ein=escape(str(payload.get("ein", ""))),
        address=escape(str(payload.get("address", ""))),
        subject_address=escape(str(subject.get("address", ""))),
        subject_chain=escape(str(subject.get("chain", ""))),
        subject_entity=escape(str(subject.get("entity", ""))),
        sanctions_match=escape(str(subject.get("sanctions_match", "false"))),
        risk_score=subject.get("risk_score", 0),
        activity_type=escape(str(payload.get("activity_type", ""))),
        narrative=escape(str(payload.get("narrative", ""))),
        total_usd=payload.get("total_usd", 0),
        tx_count=payload.get("tx_count", 0),
        counterparties_xml="\n".join(cp_lines),
        red_flags_xml="\n".join(rf_lines),
    )


# ── STIX 2.1 bundle ───────────────────────────────────────────────────────────

def export_stix(case_data: dict, addresses: list[dict], indicators: list[dict]) -> dict:
    """Produce a STIX 2.1 bundle of the case's IOCs for threat-intel sharing.

    Each address becomes a `cryptocurrency-wallet` SCO; each indicator becomes an
    `indicator` SDO; the case becomes an `report` SDO; relationships link them.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle_id = f"bundle--{uuid.uuid4()}"
    objects: list[dict] = []
    report_id = f"report--{uuid.uuid4()}"

    wallet_ids: list[str] = []
    for a in addresses:
        wid = f"cryptocurrency-wallet--{uuid.uuid4()}"
        wallet_ids.append(wid)
        chain = (a.get("chain") or "").lower()
        # STIX currency values
        symbol = {"btc": "Bitcoin", "eth": "Ethereum", "trx": "Tron", "sol": "Solana",
                  "ltc": "Litecoin", "xmr": "Monero"}.get(chain, chain.capitalize())
        objects.append({
            "type": "cryptocurrency-wallet", "id": wid,
            "spec_version": "2.1",
            "value": a.get("address", ""),
            "currency": symbol or "Bitcoin",
            "description": f"{a.get('label', '')} (risk {a.get('risk_score', -1)})".strip(),
        })

    indicator_ids: list[str] = []
    for ind in indicators[:100]:
        iid = f"indicator--{uuid.uuid4()}"
        indicator_ids.append(iid)
        objects.append({
            "type": "indicator", "id": iid, "spec_version": "2.1",
            "created": now, "modified": now,
            "name": ind.get("name", "Indicator"),
            "pattern": ind.get("pattern", "[cryptocurrency-wallet:value = '']"),
            "pattern_type": "stix",
            "valid_from": now,
            "labels": ind.get("labels", ["malicious-activity"]),
        })

    # Relationships: report refs wallets + indicators
    objects.append({
        "type": "report", "id": report_id, "spec_version": "2.1",
        "created": now, "modified": now,
        "name": case_data.get("name", "CrypTX Report"),
        "published": now,
        "object_refs": wallet_ids + indicator_ids,
        "report_types": ["threat-report"],
    })

    return {"type": "bundle", "id": bundle_id, "objects": objects}


# ── MISP event ────────────────────────────────────────────────────────────────

def export_misp(case_data: dict, addresses: list[dict], tags: list[str] | None = None) -> dict:
    """Produce a MISP event JSON with the case's addresses as attributes."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    attributes = []
    for a in addresses:
        chain = (a.get("chain") or "").lower()
        type_map = {"btc": "btc", "eth": "eth", "xmr": "xmr", "trx": "tron-address"}
        attr_type = type_map.get(chain, "other")
        attributes.append({
            "category": "Payload delivery" if chain == "btc" else "Network activity",
            "type": attr_type,
            "value": a.get("address", ""),
            "comment": f"{a.get('label', '')} risk={a.get('risk_score', -1)}",
            "to_ids": False,
        })
    return {
        "Event": {
            "info": case_data.get("name", "CrypTX export"),
            "date": now[:10],
            "threat_level_id": "2",
            "analysis": "1",
            "published": False,
            "Attribute": attributes,
            "Tag": [{"name": t} for t in (tags or ["cryptx", "cryptocurrency", "fraud"])],
        }
    }


# ── Unified export router helper ──────────────────────────────────────────────

def capabilities() -> dict:
    return {
        "pdf": pdf_engine() or "unavailable",
        "docx": docx_engine() or "unavailable",
        "fincen_xml": True,
        "stix": True,
        "misp": True,
    }


def save_export_artifact(
    case_id: str, subject: str, title: str, fmt: str, content_bytes: bytes,
    content_text: str = "",
) -> str:
    """Persist an export artifact in the report_artifacts table.

    Binary formats (pdf, docx) are stored as base64-encoded text with a `b64:` prefix
    so they survive the TEXT column and can be decoded on download.
    """
    import base64
    if content_bytes:
        stored = "b64:" + base64.b64encode(content_bytes).decode("ascii")
    else:
        stored = content_text
    return db.save_report_artifact(subject, title, stored, chain="", case_id=case_id, fmt=fmt)
