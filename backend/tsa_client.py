"""
RFC-3161 Trusted Timestamp Authority client.

Submits a content hash to an external TSA and returns a verified timestamp
token — a tamper-evident, third-party-datable proof that the content existed at
a specific time. This is what converts a "local hash-chain record" into
"court-admissible evidence" (the Daubert gap flagged in CRYPTX_ENHANCEMENT_RESEARCH).

rfc3161ng is lazy-imported so the app runs without it; timestamping only
activates when TSA_URL is set AND the library is installed.

For air-gapped deployments, point TSA_URL at a self-hosted TSA on the local
network (e.g. a tiny OpenSSL-based TSA or a FreeTSA container).
"""
from __future__ import annotations

import base64
import hashlib
from typing import Any, Optional

import config as _config


def _digest_for_tsa(raw: bytes) -> tuple[str, bytes]:
    """Return (hash_algorithm_name, digest_bytes) for the TSA request.

    TSAs accept a pre-computed digest + algorithm. We use SHA-256.
    """
    digest = hashlib.sha256(raw).digest()
    return "sha256", digest


def request_timestamp(raw: bytes, tsa_url: Optional[str] = None) -> dict[str, Any]:
    """Submit `raw` bytes to a TSA and return a token record.

    Returns a dict with:
      * `tsa_verified` (bool)     — whether the token was verified successfully.
      * `tsa_token_b64` (str)     — the RFC-3161 token, base64-encoded for storage.
      * `tsa_issuer` (str)        — the TSA's identity (from the token).
      * `tsa_timestamp` (str)     — the trusted UTC timestamp from the token.
      * `tsa_error` (str|None)    — error message if timestamping failed.

    Never raises — on any failure it returns tsa_verified=False with tsa_error
    set, so callers can fall back to the local timestamp without blocking the
    export (a TSA outage must never prevent an investigator from exporting).
    """
    url = (tsa_url or _config.TSA_URL or "").strip()
    if not url:
        return {"tsa_verified": False, "tsa_error": "TSA_URL not configured", "tsa_token_b64": "",
                "tsa_issuer": "", "tsa_timestamp": ""}

    try:
        import rfc3161ng  # type: ignore
    except ImportError:
        return {"tsa_verified": False, "tsa_error": "rfc3161ng not installed (pip install rfc3161ng)",
                "tsa_token_b64": "", "tsa_issuer": "", "tsa_timestamp": ""}

    algo, digest = _digest_for_tsa(raw)
    try:
        token = rfc3161ng.get_timestamp_token(digest, algo, url)
    except Exception as exc:
        return {"tsa_verified": False, "tsa_error": f"TSA request failed: {exc}",
                "tsa_token_b64": "", "tsa_issuer": "", "tsa_timestamp": ""}

    # Verify the token against our digest before trusting it.
    try:
        signed = rfc3161ng.verify_timestamp(token, digest=digest, hashalgorithm=hashlib.sha256)
        # rfc3161ng returns a TimestampTokenInfo-like object.
        try:
            ts = signed.tsa_info.timestamp
            tsa_timestamp = ts.strftime("%Y-%m-%dT%H:%M:%SZ") if hasattr(ts, "strftime") else str(ts)
        except Exception:
            tsa_timestamp = ""
        issuer = ""
        try:
            # The TSA's certificate subject is in the signed attributes; rfc3161ng
            # exposes it differently across versions — best-effort extraction.
            attrs = getattr(signed, "signed_attrs", None) or getattr(signed, "content", None)
            issuer = str(getattr(attrs, "tsa", "") or "")
        except Exception:
            pass
        return {
            "tsa_verified": True,
            "tsa_token_b64": base64.b64encode(token).decode("ascii"),
            "tsa_issuer": issuer or _config.TSA_URL,
            "tsa_timestamp": tsa_timestamp,
            "tsa_error": None,
        }
    except Exception as exc:
        # Token returned but failed verification — suspicious; don't trust it.
        return {"tsa_verified": False, "tsa_error": f"token verification failed: {exc}",
                "tsa_token_b64": base64.b64encode(token).decode("ascii") if token else "",
                "tsa_issuer": "", "tsa_timestamp": ""}
