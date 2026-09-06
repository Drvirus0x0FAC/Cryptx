"""
AI-fraud infrastructure forensics — "Scam Network Atlas" (Next-Horizon 3.3).

The 2026 scam economy is AI-industrialized (AI personas, deepfake KYC,
fraud-as-a-service kits). The countermeasure is cross-case INFRASTRUCTURE
clustering: turn individual victim reports into named scam networks.

What it does (deterministic, evidence-cited, offline):
  * artifact extraction — deposit addresses, domains, emails, @handles pulled
    from every victim report (description/tags/fields);
  * union-find clustering — reports sharing a deposit address, domain, email,
    or handle collapse into one network;
  * kit fingerprinting — address-reuse, multi-scam-type reuse, and burst
    (creation-window) signals that indicate an industrialized kit;
  * deepfake-KYC signal — many short-lived, low-reuse deposit addresses across
    chains ≈ industrialized account creation consistent with synthetic KYC;
  * attribution promotion — one click registers the network's addresses as
    provenance-tracked leads in the attribution engine.

Additive: derives everything from the existing victim_reports table; own
scam_networks cache table.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import config as _config
DB_PATH = _config.DB_PATH

_DOMAIN_RE = re.compile(r"\b((?:[a-z0-9-]+\.)+(?:com|net|org|io|co|app|xyz|top|vip|cc|pro|live|site|online|finance|exchange|trade|capital|fund|invest))\b", re.I)
_EMAIL_RE = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.I)
_HANDLE_RE = re.compile(r"(?:^|\s)@([a-z0-9_]{4,32})\b", re.I)
# Domains too generic to be linking evidence
_DOMAIN_STOPLIST = {"gmail.com", "outlook.com", "yahoo.com", "hotmail.com", "proton.me",
                    "protonmail.com", "icloud.com", "telegram.org", "t.me", "whatsapp.com",
                    "binance.com", "coinbase.com", "etherscan.io", "tronscan.org"}

BURST_WINDOW_HOURS = 72
SHORT_LIVED_DAYS = 7


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_tables() -> None:
    con = _conn()
    try:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS scam_networks (
                id            TEXT PRIMARY KEY,
                built_at      TEXT,
                network_json  TEXT
            );
        """)
        con.commit()
    finally:
        con.close()


# ── Artifact extraction ──────────────────────────────────────────────────────

def _extract_artifacts(report: dict[str, Any]) -> dict[str, set[str]]:
    text_parts = [report.get("description") or "", report.get("analyst_notes") or ""]
    try:
        tags = json.loads(report.get("tags") or "[]")
    except (ValueError, TypeError):
        tags = []
    text_parts.extend(str(t) for t in tags)
    text = " ".join(text_parts)

    domains = {d.lower() for d in _DOMAIN_RE.findall(text)} - _DOMAIN_STOPLIST
    emails = {e.lower() for e in _EMAIL_RE.findall(text)}
    handles = {h.lower() for h in _HANDLE_RE.findall(text)}
    addresses = set()
    if report.get("scammer_address"):
        addresses.add(report["scammer_address"].strip().lower())
    return {"addresses": addresses, "domains": domains, "emails": emails, "handles": handles}


# ── Union-find over reports ──────────────────────────────────────────────────

class _UF:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _load_reports() -> list[dict[str, Any]]:
    con = _conn()
    try:
        try:
            rows = con.execute("SELECT * FROM victim_reports ORDER BY created_at").fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        con.close()
    return [dict(r) for r in rows]


def build_networks(min_reports: int = 1) -> dict[str, Any]:
    """Cluster all victim reports into scam networks. Persists the result."""
    init_tables()
    reports = _load_reports()
    artifacts = [_extract_artifacts(r) for r in reports]

    # Invert: artifact value → report indices (typed keys so 'a@b.com' the email
    # never collides with a domain of the same string)
    index: dict[str, list[int]] = {}
    for i, art in enumerate(artifacts):
        for kind, values in art.items():
            for v in values:
                index.setdefault(f"{kind}:{v}", []).append(i)

    uf = _UF(len(reports))
    link_evidence: dict[int, set[str]] = {}
    for key, idxs in index.items():
        if len(idxs) < 2:
            continue
        first = idxs[0]
        for j in idxs[1:]:
            uf.union(first, j)
        for j in idxs:
            link_evidence.setdefault(j, set()).add(key)

    groups: dict[int, list[int]] = {}
    for i in range(len(reports)):
        groups.setdefault(uf.find(i), []).append(i)

    networks = []
    for members in groups.values():
        if len(members) < min_reports:
            continue
        net = _summarize_network([reports[i] for i in members],
                                 [artifacts[i] for i in members],
                                 sorted({k for i in members for k in link_evidence.get(i, set())}))
        networks.append(net)
    networks.sort(key=lambda n: -n["total_damage_usd"])

    payload = {"built_at": _now(), "report_count": len(reports), "network_count": len(networks),
               "networks": networks}
    con = _conn()
    try:
        con.execute("DELETE FROM scam_networks")
        con.execute("INSERT INTO scam_networks (id, built_at, network_json) VALUES (?,?,?)",
                    ("latest", payload["built_at"], json.dumps(payload)))
        con.commit()
    finally:
        con.close()
    return payload


def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _summarize_network(reports: list[dict[str, Any]], arts: list[dict[str, set[str]]],
                       links: list[str]) -> dict[str, Any]:
    addresses = sorted({a for art in arts for a in art["addresses"]})
    domains = sorted({d for art in arts for d in art["domains"]})
    emails = sorted({e for art in arts for e in art["emails"]})
    handles = sorted({h for art in arts for h in art["handles"]})
    scam_types = sorted({r.get("scam_type") or "?" for r in reports})
    chains = sorted({(r.get("chain") or "?").upper() for r in reports})
    damage = sum(float(r.get("amount_usd") or 0) for r in reports)
    dates = sorted(d for d in (_parse_dt(r.get("incident_date") or r.get("report_date") or "") for r in reports) if d)

    nid = hashlib.sha256(("|".join(addresses) + "|".join(domains)).encode()).hexdigest()[:12]

    # ── Kit fingerprint signals (deterministic, each with cited basis) ──
    signals: list[dict[str, Any]] = []
    addr_use: dict[str, int] = {}
    for r in reports:
        a = (r.get("scammer_address") or "").lower()
        if a:
            addr_use[a] = addr_use.get(a, 0) + 1
    heavy_reuse = [a for a, c in addr_use.items() if c >= 3]
    if heavy_reuse:
        signals.append({"signal": "address_reuse", "severity": "high",
                        "detail": f"{len(heavy_reuse)} deposit address(es) named by ≥3 victims each — "
                                  "central kit/collector wallets.",
                        "basis": f"victim reports naming {', '.join(x[:12] + '…' for x in heavy_reuse[:3])}"})
    if len(scam_types) >= 2 and (domains or heavy_reuse):
        signals.append({"signal": "multi_typology_kit", "severity": "high",
                        "detail": f"Same infrastructure spans {len(scam_types)} scam typologies "
                                  f"({', '.join(scam_types[:4])}) — fraud-as-a-service kit behavior.",
                        "basis": "shared addresses/domains across typologies"})
    if len(dates) >= 3:
        bursts = 0
        for i in range(len(dates) - 2):
            if (dates[i + 2] - dates[i]).total_seconds() <= BURST_WINDOW_HOURS * 3600:
                bursts += 1
        if bursts:
            signals.append({"signal": "burst_targeting", "severity": "medium",
                            "detail": f"≥3 victims hit within a {BURST_WINDOW_HOURS}h window "
                                      f"({bursts} burst(s)) — coordinated campaign waves.",
                            "basis": "incident-date clustering"})

    # ── Deepfake-KYC / industrialized account-creation signal ──
    short_lived = 0
    for a in addresses:
        a_dates = sorted(d for d in (_parse_dt(r.get("incident_date") or r.get("report_date") or "")
                                     for r in reports if (r.get("scammer_address") or "").lower() == a) if d)
        if a_dates and (a_dates[-1] - a_dates[0]).days <= SHORT_LIVED_DAYS and addr_use.get(a, 0) <= 2:
            short_lived += 1
    if len(addresses) >= 5 and short_lived / max(len(addresses), 1) >= 0.6:
        signals.append({
            "signal": "synthetic_kyc_pattern", "severity": "high",
            "detail": f"{short_lived}/{len(addresses)} deposit addresses are short-lived (≤{SHORT_LIVED_DAYS} days) "
                      "and low-reuse across multiple chains — consistent with industrialized account creation "
                      "(AI/deepfake-KYC-enabled). LEAD: request KYC media + device data from receiving VASPs.",
            "basis": "address-lifespan and reuse statistics from victim reports"})
    if len(chains) >= 3:
        signals.append({"signal": "multi_chain_placement", "severity": "medium",
                        "detail": f"Victim deposits across {len(chains)} chains ({', '.join(chains[:5])}) — "
                                  "chain-hopping placement layer.",
                        "basis": "chains named in victim reports"})

    return {
        "id": nid,
        "name": f"Scam network {nid}",
        "victim_count": len(reports),
        "total_damage_usd": round(damage, 2),
        "scam_types": scam_types,
        "chains": chains,
        "addresses": addresses,
        "domains": domains,
        "emails": emails,
        "handles": handles,
        "first_seen": dates[0].isoformat() if dates else None,
        "last_seen": dates[-1].isoformat() if dates else None,
        "report_ids": [r.get("id") for r in reports],
        "linking_artifacts": links[:40],
        "signals": signals,
    }


# ── Read APIs ────────────────────────────────────────────────────────────────

def get_atlas(rebuild: bool = False, min_reports: int = 1) -> dict[str, Any]:
    init_tables()
    if not rebuild:
        con = _conn()
        try:
            row = con.execute("SELECT network_json FROM scam_networks WHERE id='latest'").fetchone()
        finally:
            con.close()
        if row and row["network_json"]:
            try:
                return json.loads(row["network_json"])
            except (ValueError, TypeError):
                pass
    return build_networks(min_reports)


def get_network(nid: str) -> Optional[dict[str, Any]]:
    atlas = get_atlas()
    for n in atlas.get("networks", []):
        if n["id"] == nid:
            # attach member reports for the detail view
            reports = [r for r in _load_reports() if r.get("id") in set(n.get("report_ids") or [])]
            for r in reports:
                for k in ("tags", "tx_hashes", "evidence_hashes"):
                    try:
                        r[k] = json.loads(r.get(k) or "[]")
                    except (ValueError, TypeError):
                        r[k] = []
            return {**n, "reports": reports}
    return None


def promote_to_attribution(nid: str, assigned_by: str = "scam-atlas") -> dict[str, Any]:
    """Register every network address as a provenance-tracked attribution lead."""
    net = get_network(nid)
    if not net:
        raise ValueError("network not found")
    added, errors = 0, 0
    try:
        import attribution_engine
    except Exception as e:
        raise RuntimeError(f"attribution engine unavailable: {e}")
    for addr in net.get("addresses", []):
        try:
            attribution_engine.add_attribution(
                address=addr, category="scam",
                actor=net["name"], label=f"{net['name']} deposit address",
                source=f"scam_network:{nid} ({net['victim_count']} victim reports, "
                       f"${net['total_damage_usd']:,.0f} damage)",
                confidence=min(0.9, 0.5 + 0.1 * min(net["victim_count"], 4)),
                evidence=[{"type": "victim_reports", "report_ids": net.get("report_ids", [])[:50]},
                          {"type": "linking_artifacts", "items": net.get("linking_artifacts", [])[:20]}],
                assigned_by=assigned_by, method="scam_network_clustering",
                note="Auto-promoted from Scam Network Atlas — lead, not claim.")
            added += 1
        except Exception:
            errors += 1
    return {"network_id": nid, "attributions_added": added, "errors": errors}


def summary() -> dict[str, Any]:
    atlas = get_atlas()
    nets = atlas.get("networks", [])
    return {
        "built_at": atlas.get("built_at"),
        "report_count": atlas.get("report_count", 0),
        "network_count": len(nets),
        "multi_victim_networks": sum(1 for n in nets if n["victim_count"] >= 2),
        "total_damage_usd": round(sum(n["total_damage_usd"] for n in nets), 2),
        "synthetic_kyc_flags": sum(1 for n in nets
                                   if any(s["signal"] == "synthetic_kyc_pattern" for s in n["signals"])),
        "top_networks": [{k: n[k] for k in ("id", "name", "victim_count", "total_damage_usd",
                                            "scam_types", "chains")} for n in nets[:10]],
    }
