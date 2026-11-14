"""Plain-text mission briefing generated only from backend status values."""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any


MAX_BYTES = 49_999
# Keep room for a deterministic omission footer even when the content is full.
_FOOTER_RESERVE = 1_024
_CREW_PREVIEW_LIMIT = 320
_ALERT_PREVIEW_LIMIT = 180
_MODEL_PREVIEW_LIMIT = 48

_BANDS = {"unknown": 0, "green": 1, "stale": 2, "amber": 3, "red": 4}


def _text(value: Any, limit: int = 240) -> str:
    """Render one scalar without allowing arbitrary structured input into the file."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (str, int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return ""
        text = str(value).replace("\r", " ").replace("\n", " ").replace("\t", " ")
        return " ".join(text.split())[:limit]
    return ""


def _number(value: Any) -> str:
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)) and math.isfinite(value):
        return str(value)
    return ""


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _crew_label(status: dict[str, Any], index: int) -> str:
    # These are the backend's crew identity fields; arbitrary display metadata is excluded.
    return _text(status.get("name") or status.get("crew_name") or status.get("crew_id")) or f"crew-{index + 1}"


def _crew_state(status: dict[str, Any]) -> str:
    systems = status.get("systems")
    if isinstance(systems, dict):
        values = [_text(v).lower() for v in systems.values() if _text(v)]
        if values:
            return max(values, key=lambda value: _BANDS.get(value, -1))
    state = status.get("status")
    if isinstance(state, str):
        return _text(state).lower() or "unknown"
    return "unknown"


def _is_active(alert: dict[str, Any]) -> bool:
    return bool(alert.get("active"))


def _alert_bucket(alert: dict[str, Any]) -> str:
    level = _text(alert.get("level")).lower()
    if _is_active(alert) and level == "red":
        return "red"
    if _is_active(alert) and level == "amber":
        return "amber"
    if _is_active(alert):
        return "other_active"
    return "resolved"


def _rules(alert: dict[str, Any]) -> list[dict[str, Any]]:
    rule = alert.get("rule")
    if isinstance(rule, dict):
        return [rule]
    return [item for item in _safe_list(rule) if isinstance(item, dict)]


def _reason(alert: dict[str, Any]) -> str:
    direct = _text(alert.get("reason"))
    if direct:
        return direct
    parts: list[str] = []
    basis = _text(alert.get("basis"))
    if basis:
        parts.append(f"basis={basis}")
    for rule in _rules(alert):
        details = []
        for key in ("kind", "direction", "basis"):
            value = _text(rule.get(key))
            if value and f"{key}={value}" not in parts and f"{key}={value}" not in details:
                details.append(f"{key}={value}")
        for key in ("amber", "red"):
            value = _number(rule.get(key))
            if value:
                details.append(f"{key}={value}")
        if details:
            parts.append("threshold " + ",".join(details))
    return "; ".join(parts)[:420]


def _citations(alert: dict[str, Any]) -> str:
    citations: list[str] = []
    for source in [alert, *_rules(alert)]:
        citation = _text(source.get("citation")) if isinstance(source, dict) else ""
        if citation and citation not in citations:
            citations.append(citation)
    return "; ".join(citations)[:420]


def _fired(alert: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    fired = alert.get("fired")
    if isinstance(fired, dict):
        return [(str(signal), value) for signal, value in sorted(fired.items(), key=lambda item: str(item[0]))
                if isinstance(value, dict)]
    return []


def _fired_text(alert: dict[str, Any]) -> str:
    values: list[str] = []
    for signal, detail in _fired(alert):
        bits = []
        for key in ("value", "band", "ts", "provenance"):
            value = _text(detail.get(key))
            if value:
                bits.append(f"{key}={value}")
        values.append(f"{_text(signal, 100)}({','.join(bits)})")
    return "; ".join(values)[:900]


def _crew_response(status: dict[str, Any], alert: dict[str, Any]) -> str:
    response = alert.get("response")
    if isinstance(response, dict):
        crew = _text(response.get("crew"))
        if crew:
            return crew
    crew = _text(alert.get("response_crew"))
    if crew:
        return crew
    signals = status.get("signals")
    if isinstance(signals, dict):
        for signal, _ in _fired(alert):
            entry = signals.get(signal)
            if isinstance(entry, dict) and isinstance(entry.get("response"), dict):
                crew = _text(entry["response"].get("crew"))
                if crew:
                    return crew
    return ""


def _alert_line(status: dict[str, Any], alert: dict[str, Any], index: int) -> str:
    level = _text(alert.get("level")).lower() or "unknown"
    name = _text(alert.get("name") or alert.get("id") or alert.get("signal")) or "unnamed alert"
    parts = [f"crew={_crew_label(status, index)}", f"level={level}", f"alert={name}"]
    reason = _reason(alert)
    if reason:
        parts.append(f"reason={reason}")
    fired = _fired_text(alert)
    if fired:
        parts.append(f"fired={fired}")
    response = _crew_response(status, alert)
    if response:
        parts.append(f"crew_response={response}")
    citation = _citations(alert)
    if citation:
        parts.append(f"citation={citation}")
    return "- " + " | ".join(parts)


def _mission_fields(mission: dict[str, Any]) -> tuple[str, str]:
    name = _text(mission.get("name") or mission.get("mission") or mission.get("preset")) or "unspecified"
    delay = mission.get("one_way_delay_s")
    if delay is None:
        delay = mission.get("comms_delay_s")
    if delay is None and isinstance(mission.get("preset"), dict):
        delay = mission["preset"].get("one_way_delay_s")
    return name, _number(delay) or "unspecified"


class _Writer:
    def __init__(self) -> None:
        self.data = bytearray()
        self.omitted_lines = 0

    def add(self, line: str) -> bool:
        encoded = (line + "\n").encode("utf-8")
        if len(self.data) + len(encoded) > MAX_BYTES - _FOOTER_RESERVE:
            self.omitted_lines += 1
            return False
        self.data.extend(encoded)
        return True

    def finish(self, footer: str) -> bytes:
        # The reserve makes this complete footer fit; the final guard is byte-based and UTF-8 safe.
        self.data.extend(footer.encode("utf-8"))
        return bytes(self.data[:MAX_BYTES])


def build_briefing(mission: dict, statuses: list[dict], reports: dict) -> bytes:
    """Build a UTF-8 plain-text briefing, strictly below 50,000 encoded bytes.

    Only fields from the core mission/status/report schemas are rendered. Unknown keys are ignored,
    including endpoint, authentication, VAPID, raw reading history, and game-session data.
    """
    statuses = statuses if isinstance(statuses, list) else []
    reports = reports if isinstance(reports, dict) else {}
    mission = mission if isinstance(mission, dict) else {}

    total_crew = len(statuses)
    crew_rows: list[tuple[int, dict[str, Any]]] = []
    alert_rows: dict[str, list[tuple[int, dict[str, Any], dict[str, Any]]]] = {
        "red": [], "amber": [], "other_active": [], "resolved": []
    }
    alert_counts = {key: 0 for key in alert_rows}
    model_rows: list[tuple[int, dict[str, Any]]] = []
    model_total = 0
    model_available = 0
    model_unavailable = 0
    state_counts: dict[str, int] = {}

    # One bounded aggregation pass preserves global counts without retaining the input payload.
    for index, status in enumerate(statuses):
        if not isinstance(status, dict):
            continue
        if len(crew_rows) < _CREW_PREVIEW_LIMIT:
            crew_rows.append((index, status))
        state = _crew_state(status)
        state_counts[state] = state_counts.get(state, 0) + 1
        anomaly = status.get("anomaly")
        immune = status.get("immune_risk")
        if isinstance(anomaly, dict) or isinstance(immune, dict):
            model_total += 1
            if isinstance(anomaly, dict) and anomaly.get("available") is True:
                model_available += 1
            elif isinstance(anomaly, dict):
                model_unavailable += 1
            if len(model_rows) < _MODEL_PREVIEW_LIMIT:
                model_rows.append((index, status))
        alerts = status.get("alerts")
        if not isinstance(alerts, list):
            continue
        for alert in alerts:
            if not isinstance(alert, dict):
                continue
            bucket = _alert_bucket(alert)
            alert_counts[bucket] += 1
            if len(alert_rows[bucket]) < _ALERT_PREVIEW_LIMIT:
                alert_rows[bucket].append((index, status, alert))

    released = _safe_list(reports.get("released"))
    pending = _safe_list(reports.get("pending"))
    pending_delays = []
    for report in pending:
        if isinstance(report, dict):
            value = report.get("release_in_s")
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                pending_delays.append(value)

    generation = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    mission_name, delay = _mission_fields(mission)
    writer = _Writer()
    writer.add("AURA-BIO MISSION BRIEFING")
    writer.add("Plain text; backend-generated; no language model used.")
    writer.add(f"generationUTC: {generation}")
    writer.add("SIMULATION: YES | MEDICAL DEVICE: NO")
    writer.add("Disclaimer: Not a medical device. Research concept; all crew data is simulated.")
    writer.add(f"Mission: {mission_name} | one-way delay seconds: {delay}")
    writer.add("")

    writer.add(f"CREW SUMMARY (total crew: {total_crew})")
    for index, status in crew_rows:
        state = _crew_state(status)
        label = _crew_label(status, index)
        last = _text(status.get("ts") or status.get("last_reading")) or "unknown"
        writer.add(f"- {label} | status={state} | lastreading={last}")
    crew_omitted = max(0, total_crew - len(crew_rows))
    if crew_omitted:
        writer.add(f"[crew summary preview omitted {crew_omitted}; total crew={total_crew}]")
    writer.add("Crew status counts: " + ", ".join(f"{key}={state_counts[key]}" for key in sorted(state_counts)))
    writer.add("")

    active_total = alert_counts["red"] + alert_counts["amber"] + alert_counts["other_active"]
    resolved_total = alert_counts["resolved"]
    writer.add(f"ALERT COUNTS: active={active_total} | resolved-to-review={resolved_total}")
    writer.add(f"Active urgency counts: red={alert_counts['red']} | amber={alert_counts['amber']} | other={alert_counts['other_active']}")
    writer.add("")

    alert_titles = (
        ("ACTIVE RED ALERTS", "red"),
        ("ACTIVE AMBER ALERTS", "amber"),
        ("OTHER ACTIVE ALERTS", "other_active"),
        ("RESOLVED TO REVIEW", "resolved"),
    )
    alert_omitted = 0
    for title, bucket in alert_titles:
        writer.add(f"{title} (total: {alert_counts[bucket]})")
        rows = alert_rows[bucket]
        for index, status, alert in rows:
            if not writer.add(_alert_line(status, alert, index)):
                alert_omitted += 1
        alert_omitted += max(0, alert_counts[bucket] - len(rows))
        writer.add("")

    writer.add("MODEL / RESEARCH CONTEXT")
    writer.add(f"Anomaly availability: available={model_available} | unavailable={model_unavailable}")
    model_omitted = 0
    for index, status in model_rows:
        parts = [f"crew={_crew_label(status, index)}"]
        anomaly = status.get("anomaly")
        if isinstance(anomaly, dict):
            if "available" in anomaly:
                parts.append(f"anomaly_available={_text(anomaly.get('available'))}")
            if _number(anomaly.get("score")):
                parts.append(f"anomaly_score={_number(anomaly.get('score'))}")
            reason = _text(anomaly.get("reason"))
            if reason:
                parts.append(f"anomaly_reason={reason}")
        immune = status.get("immune_risk")
        if isinstance(immune, dict):
            if _number(immune.get("score")):
                parts.append(f"immune_risk_score={_number(immune.get('score'))}")
            label = _text(immune.get("label"))
            if label:
                parts.append(f"immune_risk_label={label}")
        writer.add("- " + " | ".join(parts))
    model_omitted += max(0, model_total - len(model_rows))
    if model_omitted:
        writer.add(f"[model context omitted {model_omitted} crew entries]")
    writer.add("")

    writer.add("GROUND REPORTS")
    writer.add(f"Released reports: {len(released)} | pending reports: {len(pending)}")
    if pending_delays:
        writer.add(f"Pending release delay seconds: min={min(pending_delays):g} | max={max(pending_delays):g}")
    else:
        writer.add("Pending release delay seconds: none available")
    writer.add("Pending report payloads are intentionally not included before release.")
    writer.add("")

    footer = (
        "OMISSIONS / LIMITS\n"
        f"crew_summary_omitted={crew_omitted} | alert_details_omitted={alert_omitted} | "
        f"model_context_omitted={model_omitted} | writer_lines_omitted={writer.omitted_lines}\n"
        "Counts above cover all supplied backend statuses; previews are bounded for bandwidth.\n"
    )
    return writer.finish(footer)
