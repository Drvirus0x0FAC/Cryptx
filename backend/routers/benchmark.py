"""
Benchmark harness router — /api/benchmark

  GET /api/benchmark/run   run all detector benchmarks, return Daubert error rates
"""
from __future__ import annotations

from fastapi import APIRouter

import benchmark_harness

router = APIRouter(prefix="/benchmark", tags=["Benchmark"])


@router.get("/run")
def run_benchmarks():
    """Run all registered detector benchmarks. Returns precision/recall/FPR/FNR
    for each detector — the 'known error rates' the Daubert standard requires."""
    return benchmark_harness.run_all_benchmarks()
