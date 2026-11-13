"""Domain layer (plan 3.5): all health logic. No network or database code, so it tests alone."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from statistics import mean, stdev

ORDER = ("unknown", "green", "stale", "amber", "red")  # a system shows the worst of its signals
log = logging.getLogger("aura.core")
DISCLAIMER = "Not a medical device. Research concept; all crew data is simulated."


def baseline(values: list[float]) -> tuple[float, float] | None:
    return (mean(values), stdev(values)) if len(values) >= 2 else None


def band(rule: dict | list[dict], value: float, base_mean: float | None = None) -> str | None:
    """green/amber/red for one reading; None while a baseline-relative rule has no baseline.
    A list of rules gives the worst band of those that can be evaluated."""
    if isinstance(rule, list):
        bands = [b for r in rule if (b := band(r, value, base_mean))]
        return max(bands, key=ORDER.index) if bands else None
    sign = 1 if rule["direction"] == "above" else -1
    relative = rule["kind"] != "abs"
    x = value
    if relative:
        if not base_mean:
            return None
        x = value - base_mean
        if rule["kind"] == "pct":
            x = x / base_mean * 100

    def crossed(t):
        return t is not None and sign * x > (t if relative else sign * t)

    return "red" if crossed(rule.get("red")) else "amber" if crossed(rule.get("amber")) else "green"


def pattern_hit(p: dict, signals: dict[str, dict]) -> bool:
    """Every signal amber or red, and at least its min_band where the pattern sets one."""
    need = p.get("min_band", {})
    return all(ORDER.index(signals[s]["band"]) >= ORDER.index(need.get(s, "amber")) for s in p["signals"])


def match_patterns(signals: dict[str, dict], patterns: list[dict], history: list[dict] = ()) -> list[dict]:
    """One alert per pattern that matches now and on each of its previous `days` - 1 days (history[0] = yesterday);
    red if any signal is red now (FR-5, FR-6)."""
    alerts = []
    for p in patterns:
        try:  # NFR-2: a broken pattern must not stop the others
            days = p.get("days", 1)
            if pattern_hit(p, signals) and len(history) >= days - 1 and all(
                    pattern_hit(p, h) for h in history[:days - 1]):
                bands = [signals[s]["band"] for s in p["signals"]]
                alerts.append(p | {"level": "red" if "red" in bands else "amber",
                                   "fired": {s: {k: signals[s].get(k) for k in ("band", "value", "ts", "provenance")}
                                             for s in p["signals"]}})
        except Exception:  # noqa: BLE001
            log.exception("pattern %s failed", p.get("id"))
    return alerts


def signal_bands(latest: dict[str, dict], baselines: dict[str, tuple[float, float]], cfg: dict,
                 signals: list[dict], now: datetime) -> dict[str, dict]:
    out = {}
    for s in signals:
        name, r = s["name"], latest.get(s["name"])
        entry = {"system": s["system"], "band": "unknown"}
        if r:
            rule, base = cfg["thresholds"].get(name), baselines.get(name)
            limit = timedelta(days=s.get("interval_days", 1) * cfg["stale_after_intervals"])
            if now - datetime.fromisoformat(r["ts"]) > limit:
                entry["band"] = "stale"  # FR-8: never green when the data is late
            elif rule:
                entry["band"] = band(rule, r["value"], base and base[0]) or "unknown"
            entry |= {"value": r["value"], "ts": r["ts"], "provenance": r["provenance"], "rule": rule,
                      "baseline_mean": base and base[0], "baseline_sd": base and base[1],
                      "z": (r["value"] - base[0]) / base[1] if base and base[1] else None}
        out[name] = entry
    return out


def history_days(cfg: dict) -> int:
    """How many earlier daily snapshots the patterns need."""
    return max((p.get("days", 1) for p in cfg.get("patterns", [])), default=1) - 1


def status(crew_id: str, latest: dict[str, dict], baselines: dict[str, tuple[float, float]],
           cfg: dict, signals: list[dict], history: list[dict[str, dict]] = ()) -> dict:
    """latest: newest stored reading per signal. history[k]: the same as of k + 1 days before now.
    'Now' is the newest reading of this crew member, so staleness also works when a scenario is
    replayed faster than real time."""
    now = max(datetime.fromisoformat(r["ts"]) for r in latest.values())
    out = signal_bands(latest, baselines, cfg, signals, now)
    past = [signal_bands(h, baselines, cfg, signals, now - timedelta(days=k + 1)) for k, h in enumerate(history)]
    systems = {}
    for e in out.values():
        systems[e["system"]] = max(systems.get(e["system"], "unknown"), e["band"], key=ORDER.index)
    return {"crew_id": crew_id, "ts": now.isoformat(), "baseline_ready": bool(baselines),
            "systems": systems, "signals": out,
            "alerts": match_patterns(out, cfg.get("patterns", []), past), "disclaimer": DISCLAIMER}
