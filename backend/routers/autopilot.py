"""
One-click auto-investigation.

POST /api/auto/start          {address, chain?, case_id?}  → {job_id}
GET  /api/auto/jobs/{job_id}                               → progress + result

Pipeline (all local/existing engines, background task with staged progress):
  1. Address intel lookup
  2. Risk scoring
  3. Local forensics (motifs, taint, clusters)
  4. Threat intelligence (attribution hypotheses, typologies, pivots)
  5. Deterministic attribution record
  6. Draft investigation report (markdown) — optionally registered into the
     case evidence vault (chain-of-custody).
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["Auto Investigation"])

_JOBS: Dict[str, Dict[str, Any]] = {}
_MAX_JOBS = 200

STAGES = [
    "Address Intelligence",
    "Risk Scoring",
    "Local Forensics",
    "Threat Intelligence",
    "Attribution",
    "Exit-VASP Trace",
    "Drafting Report",
]


async def _exit_vasp_stage(address: str, chain: Optional[str]) -> Dict[str, Any]:
    """
    Trace outbound funds until they hit exchange/VASP deposit points, then enrich
    each terminal with the KYV directory so the report can say exactly where to
    serve legal process. Best-effort: returns partial data on any failure.
    """
    out: Dict[str, Any] = {"exit_vasps": [], "cashout_indicators": [], "trace_summary": None}
    try:
        import holistic_trace_engine as hte
        import vasp_directory

        trace = await asyncio.wait_for(
            hte.trace(address, chain=(chain or "eth"), direction="out", max_hops=2, max_nodes=60),
            timeout=150,
        )
        summary = trace.get("summary") or {}
        out["trace_summary"] = {
            "chains_touched": summary.get("chains_touched", []),
            "exchanges_reached": summary.get("exchanges_reached", []),
            "total_traced_value": summary.get("total_traced_value"),
        }

        nodes = (trace.get("graph") or {}).get("nodes") or []
        node_map = {n.get("id"): n for n in nodes}
        seen: set[str] = set()
        candidates = list(summary.get("cash_out_points") or [])
        for ex in summary.get("exchanges_reached") or []:
            if ex.get("id") not in {c.get("id") for c in candidates}:
                candidates.append(ex)

        for cand in candidates:
            node = node_map.get(cand.get("id")) or {}
            addr = node.get("address") or str(cand.get("id", "")).split(":")[-1]
            if not addr or addr.lower() in seen:
                continue
            seen.add(addr.lower())
            kyv = vasp_directory.identify_vasp(addr, node.get("chain"))
            vasp = kyv.get("vasp") or {}
            name = vasp.get("name") or node.get("vasp") or node.get("label") or "Unidentified VASP"
            jurisdiction = vasp.get("jurisdiction") or vasp.get("country") or "unknown jurisdiction"
            out["exit_vasps"].append({
                "address": addr,
                "chain": node.get("chain") or chain or "",
                "vasp_name": name,
                "vasp_type": vasp.get("type") or node.get("type") or "exchange",
                "jurisdiction": jurisdiction,
                "hop": cand.get("hop", node.get("hop")),
                "in_kyv_directory": bool(kyv.get("is_vasp")),
                "legal_process": (
                    f"Funds reached a deposit point controlled by {name} ({jurisdiction}). "
                    f"Serve legal process / freeze request on {name} referencing deposit address {addr}."
                ),
            })

        # Behavioral cash-out indicators on the traced graph
        try:
            from cashout_detector import detect_cashout
            edges = (trace.get("graph") or {}).get("edges") or []
            subject_id = f"{trace.get('subject_chain') or chain or 'eth'}:{trace.get('subject') or address}"
            det = detect_cashout(
                [{**n, "id": n.get("id"), "label": n.get("label", ""),
                  "role": n.get("type", ""), "risk_score": n.get("risk", 0)} for n in nodes],
                edges, subject_id,
            )
            out["cashout_indicators"] = (det.get("indicators") or [])[:8]
            out["cashout_risk"] = det.get("risk")
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)[:300]
    return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AutoStartRequest(BaseModel):
    address: str
    chain: Optional[str] = None
    case_id: str = ""
    analyst: str = "analyst"


def _set(job: Dict[str, Any], stage: str, progress: int, detail: str = "") -> None:
    job["stage"] = stage
    job["progress"] = progress
    job["detail"] = detail
    job["updated_at"] = _now()


async def _run(job_id: str, req: AutoStartRequest) -> None:
    job = _JOBS[job_id]
    address = req.address.strip()
    try:
        # 1. Intel
        _set(job, STAGES[0], 5, f"Looking up {address[:18]}…")
        from crypto_osint import lookup_crypto_address
        intel = await asyncio.wait_for(lookup_crypto_address(address), timeout=90)
        if not isinstance(intel, dict) or intel.get("error"):
            raise RuntimeError(str((intel or {}).get("error") or "address lookup failed"))
        job["partial"]["intel_summary"] = {
            "chain": intel.get("chain"), "balance": intel.get("balance"),
            "tx_count": intel.get("tx_count"), "sanctioned": bool((intel.get("sanctions") or {}).get("sanctioned")),
        }

        # 2. Risk
        _set(job, STAGES[1], 25, "Computing composite risk score")
        from risk_engine import compute_risk_score
        risk = await asyncio.to_thread(compute_risk_score, intel)
        job["partial"]["risk"] = {"score": risk.get("score"), "level": risk.get("risk_level"),
                                  "categories": risk.get("categories", [])}

        # 3. Forensics
        _set(job, STAGES[2], 40, "Running local forensic algorithms")
        from forensic_engine import analyze_forensics
        forensic = await asyncio.to_thread(analyze_forensics, intel)
        fsum = forensic.get("summary", forensic)
        job["partial"]["forensics"] = {
            "role": (fsum.get("role") or {}).get("role"),
            "motifs": len(fsum.get("motifs", [])),
            "confidence": fsum.get("confidence"),
        }

        # 4. Threat intel
        _set(job, STAGES[3], 60, "Generating attribution hypotheses and typologies")
        from threat_intel_engine import generate_intelligence
        ti = await asyncio.to_thread(generate_intelligence, intel)
        job["partial"]["threat_intel"] = {
            "threat_level": ti.get("threat_level"),
            "top_typology": ((ti.get("executive") or {}).get("top_typology") or {}).get("name"),
            "pivot_leads": len(ti.get("pivot_leads", [])),
        }

        # 5. Attribution
        _set(job, STAGES[4], 78, "Resolving deterministic attributions")
        import attribution_engine
        attribution = await asyncio.to_thread(attribution_engine.attribute, address, req.chain)

        # 6. Exit-VASP identification (where to serve legal process)
        _set(job, STAGES[5], 84, "Tracing funds to exit VASPs (exchange deposit points)")
        exit_vasp = await _exit_vasp_stage(address, req.chain)
        job["partial"]["exit_vasps"] = {
            "count": len(exit_vasp.get("exit_vasps", [])),
            "top": (exit_vasp.get("exit_vasps") or [{}])[0].get("vasp_name") if exit_vasp.get("exit_vasps") else None,
        }

        # 7. Report
        _set(job, STAGES[6], 92, "Drafting investigation report")
        from report_builder import build_address_report
        report_html = await asyncio.to_thread(build_address_report, fsum, risk)

        top_attr = (attribution.get("attributions") or [{}])[0]
        exec_summary = "\n".join([
            f"# Auto-Investigation — {address}",
            f"_Generated {_now()} by CrypTX autopilot (all-local pipeline)_",
            "",
            f"**Risk:** {risk.get('score')}/100 ({risk.get('risk_level')})",
            f"**Threat level:** {ti.get('threat_level')} ({ti.get('threat_score')}/100)",
            f"**Behavioral role:** {(fsum.get('role') or {}).get('role', 'unknown').replace('_', ' ')}",
            f"**Top attribution:** {top_attr.get('label') or top_attr.get('actor') or 'none'} "
            f"({top_attr.get('method_class', '-')}, confidence {top_attr.get('confidence', 0)})",
            f"**Court-defensible attribution:** {'YES' if attribution.get('court_defensible') else 'no'}",
            f"**Top typology:** {((ti.get('executive') or {}).get('top_typology') or {}).get('name', '-')}",
            f"**Pivot leads:** {len(ti.get('pivot_leads', []))}",
        ])
        ev_list = exit_vasp.get("exit_vasps") or []
        if ev_list:
            exec_summary += "\n\n## Exit VASPs — serve legal process here\n" + "\n".join(
                f"- **{v['vasp_name']}** ({v['jurisdiction']}, hop {v.get('hop', '?')}) — "
                f"deposit address `{v['address']}`. {v['legal_process']}"
                for v in ev_list
            )
        elif exit_vasp.get("error"):
            exec_summary += f"\n\n_Exit-VASP trace unavailable: {exit_vasp['error']}_"
        else:
            exec_summary += "\n\n_No exchange deposit points reached within 2 hops — funds may still be on-chain._"
        full_report = exec_summary

        result = {
            "address": address,
            "chain": intel.get("chain"),
            "intel": intel,
            "risk": risk,
            "forensics": fsum,
            "threat_intel": ti,
            "attribution": attribution,
            "exit_vasp": exit_vasp,
            "report_markdown": full_report,
            "report_html": report_html,
        }

        custody = None
        if req.case_id:
            try:
                import evidence_vault
                record = evidence_vault.register_export(
                    case_id=req.case_id, kind="report_export",
                    title=f"Auto-investigation — {address[:24]}",
                    content={"report_markdown": full_report, "risk": job["partial"]["risk"],
                             "threat_intel": job["partial"]["threat_intel"]},
                    subject=address, actor=req.analyst,
                )
                custody = {"evidence_id": record.get("id"), "chain_hash": record.get("chain_hash")}
            except Exception:  # noqa: BLE001
                custody = {"error": "custody registration failed"}
        result["custody"] = custody

        job["result"] = result
        job["status"] = "completed"
        _set(job, "Done", 100, "Investigation package ready")
    except Exception as exc:  # noqa: BLE001
        job["status"] = "failed"
        job["error"] = str(exc)
        _set(job, job.get("stage", "failed"), job.get("progress", 0), f"Failed: {exc}")


@router.post("/auto/start")
async def start_auto(req: AutoStartRequest):
    if not req.address.strip():
        raise HTTPException(status_code=400, detail="address is required")
    if len(_JOBS) >= _MAX_JOBS:
        oldest = sorted(_JOBS.items(), key=lambda kv: kv[1].get("created_at", ""))[: len(_JOBS) - _MAX_JOBS + 1]
        for k, _ in oldest:
            _JOBS.pop(k, None)
    jid = str(uuid.uuid4())
    _JOBS[jid] = {
        "job_id": jid,
        "address": req.address.strip(),
        "status": "running",
        "stage": "Queued",
        "progress": 0,
        "detail": "",
        "stages": STAGES,
        "partial": {},
        "result": None,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    asyncio.create_task(_run(jid, req))
    return {"job_id": jid, "status": "running", "stages": STAGES}


@router.get("/auto/jobs/{job_id}")
async def get_auto_job(job_id: str):
    job = _JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
