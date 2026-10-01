"""Shared helpers for structure-detection tracking logs."""

from __future__ import annotations

import logging
import time
from collections import Counter
from contextlib import contextmanager
from typing import Any, Iterator


def region_summary(regions: list[dict] | None) -> dict[str, Any]:
    regions = regions or []
    by_type = Counter(str(r.get("region_type") or "unknown") for r in regions)
    by_source = Counter(str(r.get("source") or "unknown") for r in regions)
    return {
        "total": len(regions),
        "by_type": dict(by_type),
        "by_source": dict(by_source),
        "windows": by_type.get("window", 0),
        "walls": by_type.get("main_wall", 0),
        "doors": by_type.get("gate", 0),
    }


def format_summary(regions: list[dict] | None) -> str:
    s = region_summary(regions)
    types = ", ".join(f"{k}={v}" for k, v in sorted(s["by_type"].items())) or "none"
    sources = ", ".join(f"{k}={v}" for k, v in sorted(s["by_source"].items())) or "none"
    return f"total={s['total']} types=[{types}] sources=[{sources}]"


@contextmanager
def timed_step(logger: logging.Logger, step: str, **fields: Any) -> Iterator[dict[str, Any]]:
    """Log start/end of a detect step with elapsed ms."""
    extra = {k: v for k, v in fields.items() if v is not None}
    meta = ", ".join(f"{k}={v}" for k, v in extra.items())
    suffix = f" ({meta})" if meta else ""
    logger.info("DETECT start %s%s", step, suffix)
    t0 = time.perf_counter()
    ctx: dict[str, Any] = {"ok": True}
    try:
        yield ctx
    except Exception as exc:
        ms = int((time.perf_counter() - t0) * 1000)
        logger.error("DETECT fail %s%s ms=%s err=%s", step, suffix, ms, exc)
        raise
    else:
        ms = int((time.perf_counter() - t0) * 1000)
        result = ctx.get("summary")
        if result:
            logger.info("DETECT done %s%s ms=%s %s", step, suffix, ms, result)
        else:
            logger.info("DETECT done %s%s ms=%s", step, suffix, ms)
