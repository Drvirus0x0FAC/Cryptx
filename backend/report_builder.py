"""
[DEPRECATED] HTML report builder for reproducible forensic artifacts.

Consolidation note: the case-level report (build_case_report) is superseded by
mega_report.generate_report(), which produces richer, audience-tailored, branded
reports. This module is retained ONLY for build_address_report(), which renders
raw forensic-engine output (no mega_report equivalent exists for that input
contract yet). New code should use mega_report for case reports.

Both functions below remain functional for backward compatibility.
"""
from __future__ import annotations

import warnings
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, Iterable, List


def _pct(v: Any) -> str:
    try:
        return f"{float(v) * 100:.1f}%"
    except (TypeError, ValueError):
        return "0.0%"


def _cell(v: Any) -> str:
    if v is None:
        return "-"
    return escape(str(v))


def _rows(items: Iterable[Dict[str, Any]], fields: List[str]) -> str:
    html = []
    for item in items:
        html.append("<tr>" + "".join(f"<td>{_cell(item.get(f))}</td>" for f in fields) + "</tr>")
    return "\n".join(html)


def build_address_report(analysis: Dict[str, Any], risk: Dict[str, Any] | None = None) -> str:
    risk = risk or {}
    now = datetime.now(timezone.utc).isoformat()
    address = analysis.get("address", "")
    role = analysis.get("role") or {}
    features = analysis.get("features") or {}
    metrics = analysis.get("graph_metrics") or {}
    clusters = analysis.get("cluster_analysis") or {}
    taint = analysis.get("taint_flow") or {}
    labels = analysis.get("local_labels") or []
    motifs = analysis.get("motifs") or []
    signals = analysis.get("algorithm_signals") or []

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>CryptoOSINT Forensic Report - {_cell(address)}</title>
<style>
body {{ font-family: Arial, sans-serif; color:#111827; background:#fff; margin: 36px; }}
h1 {{ font-size: 22px; margin-bottom: 4px; }}
h2 {{ font-size: 15px; margin-top: 26px; border-left: 4px solid #0891b2; padding-left: 8px; }}
.meta {{ color:#4b5563; font-size: 12px; margin-bottom: 20px; }}
.grid {{ display:grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }}
.stat {{ border:1px solid #d1d5db; padding: 8px; border-radius: 6px; }}
.label {{ color:#6b7280; font-size:10px; text-transform:uppercase; letter-spacing:.08em; }}
.value {{ font-size:18px; font-weight:700; margin-top:3px; word-break:break-word; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th, td {{ border:1px solid #d1d5db; padding:6px 8px; text-align:left; vertical-align:top; word-break:break-word; }}
th {{ background:#f3f4f6; }}
.risk {{ font-size:28px; font-weight:800; }}
.note {{ color:#4b5563; font-size:12px; }}
</style>
</head>
<body>
<h1>CryptoOSINT Forensic Report</h1>
<div class="meta">
Generated {_cell(now)} · Algorithm {_cell(analysis.get("algorithm_version"))} · Confidence {_pct(analysis.get("confidence"))}
</div>
<p><strong>Subject:</strong> <code>{_cell(address)}</code> · <strong>Chain:</strong> {_cell(analysis.get("chain"))}</p>

<h2>Executive Assessment</h2>
<div class="grid">
  <div class="stat"><div class="label">Risk</div><div class="value">{_cell(risk.get("risk_level", "Not scored"))}</div></div>
  <div class="stat"><div class="label">Score</div><div class="value risk">{_cell(risk.get("score", "-"))}/100</div></div>
  <div class="stat"><div class="label">Role</div><div class="value">{_cell(role.get("role", "-")).replace("_", " ")}</div></div>
  <div class="stat"><div class="label">Anomaly</div><div class="value">{_cell(clusters.get("anomaly_level", "-"))}</div></div>
</div>
<p class="note">{_cell(role.get("reason", ""))}</p>

<h2>Behavioral Fingerprint</h2>
<div class="grid">
  <div class="stat"><div class="label">Flow Through</div><div class="value">{_pct(features.get("flow_through_ratio"))}</div></div>
  <div class="stat"><div class="label">Retention</div><div class="value">{_pct(features.get("retention_ratio"))}</div></div>
  <div class="stat"><div class="label">Counterparty Entropy</div><div class="value">{_cell(features.get("counterparty_entropy"))}</div></div>
  <div class="stat"><div class="label">Roundness</div><div class="value">{_pct(features.get("roundness_score"))}</div></div>
</div>

<h2>Graph Metrics</h2>
<div class="grid">
  <div class="stat"><div class="label">Nodes</div><div class="value">{_cell(metrics.get("nodes"))}</div></div>
  <div class="stat"><div class="label">Edges</div><div class="value">{_cell(metrics.get("edges"))}</div></div>
  <div class="stat"><div class="label">Core Number</div><div class="value">{_cell(clusters.get("core_number"))}</div></div>
  <div class="stat"><div class="label">Communities</div><div class="value">{_cell(len(clusters.get("communities") or []))}</div></div>
</div>

<h2>Local Labels</h2>
<table><tr><th>Label</th><th>Category</th><th>Risk Weight</th><th>Confidence</th><th>Source</th></tr>
{_rows(labels, ["label", "category", "risk_weight", "confidence", "source"]) or '<tr><td colspan="5">No local labels.</td></tr>'}
</table>

<h2>Detected Motifs</h2>
<table><tr><th>Pattern</th><th>Severity</th><th>Confidence</th><th>Evidence</th></tr>
{_rows(motifs, ["pattern", "severity", "confidence", "evidence"]) or '<tr><td colspan="4">No motifs detected.</td></tr>'}
</table>

<h2>Algorithm Signals</h2>
<table><tr><th>Type</th><th>Severity</th><th>Weight</th><th>Label</th><th>Detail</th></tr>
{_rows(signals, ["type", "severity", "weight", "label", "detail"]) or '<tr><td colspan="5">No algorithm signals.</td></tr>'}
</table>

<h2>Taint Flow</h2>
<table><tr><th>Address</th><th>Taint</th><th>Short</th></tr>
{_rows(taint.get("exposed_addresses") or [], ["address", "taint", "short"]) or '<tr><td colspan="3">No observed downstream taint.</td></tr>'}
</table>

<h2>Reproducibility</h2>
<p class="note">
This report is generated from locally stored evidence and algorithm outputs. Labels marked as local labels are investigator-owned
intelligence and should be reviewed with their source notes before external disclosure.
</p>
</body>
</html>"""


def build_case_report(case_data: Dict[str, Any], runs: List[Dict[str, Any]]) -> str:
    """Build an HTML case report.

    Consolidation: delegates to mega_report.generate_report() (the newer branded
    report engine) when possible, falling back to the legacy renderer below only
    if mega_report is unavailable or the case has no usable id.
    """
    case_id = case_data.get("id")
    if case_id:
        try:
            import asyncio
            import mega_report
            warnings.warn(
                "build_case_report is deprecated; use mega_report.generate_report() directly.",
                DeprecationWarning, stacklevel=2,
            )
            # mega_report.generate_report is async; run it synchronously here
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    raise RuntimeError("cannot run async mega_report from sync build_case_report in a running loop")
            except RuntimeError:
                loop = asyncio.new_event_loop()
            result = loop.run_until_complete(
                mega_report.generate_report(case_id, "technical", include_ai=False, save=False)
            )
            return result.get("html", "")
        except Exception:
            pass  # fall through to legacy renderer below

    now = datetime.now(timezone.utc).isoformat()
    addresses = case_data.get("addresses") or []
    notes = case_data.get("notes") or []
    run_rows = []
    for run in runs:
        summary = run.get("summary") or {}
        role = summary.get("role") or {}
        cluster = summary.get("cluster_analysis") or {}
        run_rows.append({
            "subject": run.get("subject"),
            "chain": run.get("chain"),
            "role": role.get("role", ""),
            "confidence": summary.get("confidence", ""),
            "anomaly": cluster.get("anomaly_level", ""),
            "created_at": run.get("created_at"),
        })

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8" />
<title>CryptoOSINT Case Report - {_cell(case_data.get("name"))}</title>
<style>
body {{ font-family: Arial, sans-serif; color:#111827; background:#fff; margin:36px; }}
h1 {{ font-size:22px; }} h2 {{ font-size:15px; margin-top:26px; border-left:4px solid #0891b2; padding-left:8px; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }} th,td {{ border:1px solid #d1d5db; padding:6px 8px; text-align:left; vertical-align:top; word-break:break-word; }}
th {{ background:#f3f4f6; }} .meta,.note {{ color:#4b5563; font-size:12px; }}
</style></head><body>
<h1>CryptoOSINT Case Report</h1>
<div class="meta">Generated {_cell(now)} · Case ID {_cell(case_data.get("id"))}</div>
<p><strong>Case:</strong> {_cell(case_data.get("name"))} · <strong>Status:</strong> {_cell(case_data.get("status"))}</p>
<p class="note">{_cell(case_data.get("description", ""))}</p>

<h2>Subject Addresses</h2>
<table><tr><th>Address</th><th>Chain</th><th>Label</th><th>Risk Score</th><th>Risk Level</th><th>Added</th></tr>
{_rows(addresses, ["address", "chain", "label", "risk_score", "risk_level", "added_at"]) or '<tr><td colspan="6">No addresses.</td></tr>'}
</table>

<h2>Latest Forensic Runs</h2>
<table><tr><th>Subject</th><th>Chain</th><th>Role</th><th>Confidence</th><th>Anomaly</th><th>Created</th></tr>
{_rows(run_rows, ["subject", "chain", "role", "confidence", "anomaly", "created_at"]) or '<tr><td colspan="6">No forensic runs.</td></tr>'}
</table>

<h2>Investigator Notes</h2>
<table><tr><th>Created</th><th>Note</th></tr>
{_rows(notes, ["created_at", "note"]) or '<tr><td colspan="2">No notes.</td></tr>'}
</table>
</body></html>"""
