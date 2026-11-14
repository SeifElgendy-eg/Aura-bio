from __future__ import annotations

from core.briefing import build_briefing


def _without_generation(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("generationUTC:"))


def test_empty_briefing_is_valid_and_labeled():
    output = build_briefing({}, [], {})
    text = output.decode("utf-8")

    assert len(output) < 50_000
    assert "generationUTC:" in text
    assert "total crew: 0" in text
    assert "active=0 | resolved-to-review=0" in text
    assert "Released reports: 0 | pending reports: 0" in text
    assert "MEDICAL DEVICE: NO" in text
    assert "Not a medical device" in text


def test_normal_multicrew_includes_alert_values_response_citation_and_safe_report_counts():
    mission = {
        "name": "mars_transit",
        "one_way_delay_s": 750,
        "endpoint": "https://secret.invalid/api",
        "auth": "Bearer secret",
        "vapid_private_key": "do-not-print",
    }
    statuses = [
        {
            "crew_id": "alice",
            "name": "Alice",
            "ts": "2026-11-28T10:00:00+00:00",
            "systems": {"environment": "red", "neurocognitive": "amber"},
            "alerts": [
                {
                    "id": "co2_performance",
                    "name": "CO₂-associated performance impairment",
                    "level": "red",
                    "active": True,
                    "rule": {"kind": "abs", "direction": "above", "red": 3, "basis": "published",
                             "citation": "Research doc 4.6"},
                    "fired": {"cabin_co2_mmhg": {"value": 3.4, "band": "red", "ts": "2026-11-28T10:00:00Z",
                                                    "provenance": "simulated"}},
                    "response": {"system": "inspect", "crew": "Report headaches and follow ventilation procedures."},
                    "citation": "Research doc 7",
                    "endpoint": "https://secret.invalid/alert",
                    "vapid": "secret-vapid",
                }
            ],
            "anomaly": {"available": False, "reason": "model service unavailable", "endpoint": "secret"},
        },
        {
            "crew_id": "bob",
            "name": "Bob",
            "ts": "2026-11-27T09:00:00+00:00",
            "systems": {"environment": "green"},
            "alerts": [{"name": "Old alert", "level": "amber", "active": False,
                        "fired": {"sleep_duration_h": {"value": 4.5, "band": "red"}}}],
            "immune_risk": {"score": 12.5, "label": "research concept"},
        },
    ]
    reports = {
        "released": [{"report_id": 1, "crew_id": "alice", "body": "released details"}],
        "pending": [{"report_id": 2, "crew_id": "alice", "release_in_s": 743.2,
                      "body": "UNRELEASED SENSITIVE PAYLOAD"}],
    }

    text = build_briefing(mission, statuses, reports).decode("utf-8")

    assert "Mission: mars_transit | one-way delay seconds: 750" in text
    assert "Alice | status=red | lastreading=2026-11-28T10:00:00+00:00" in text
    assert "Bob | status=green | lastreading=2026-11-27T09:00:00+00:00" in text
    assert "active=1 | resolved-to-review=1" in text
    assert "fired=cabin_co2_mmhg(value=3.4,band=red,ts=2026-11-28T10:00:00Z,provenance=simulated)" in text
    assert "crew_response=Report headaches and follow ventilation procedures." in text
    assert "citation=Research doc 7; Research doc 4.6" in text
    assert "Released reports: 1 | pending reports: 1" in text
    assert "Pending release delay seconds: min=743.2 | max=743.2" in text
    assert "UNRELEASED SENSITIVE PAYLOAD" not in text
    assert "secret.invalid" not in text
    assert "secret-vapid" not in text
    assert "Bearer secret" not in text


def test_counts_are_stable_even_when_alert_details_have_extra_fields():
    base = [{"crew_id": "c1", "ts": "t", "systems": {"x": "amber"},
             "alerts": [{"level": "amber", "active": True, "fired": {"x": {"value": 1}}}]}]
    noisy = [{**base[0], "untrusted": {"endpoint": "secret", "auth": "secret"},
              "alerts": [{**base[0]["alerts"][0], "history": ["secret"], "vapid": "secret"}]}]

    first = _without_generation(build_briefing({"name": "station", "comms_delay_s": 2}, base, {}).decode())
    second = _without_generation(build_briefing({"name": "station", "comms_delay_s": 2}, noisy, {}).decode())

    assert "active=1 | resolved-to-review=0" in first
    assert "active=1 | resolved-to-review=0" in second
    assert "secret" not in second


def test_large_unicode_input_is_bounded_valid_utf8_and_reports_omissions():
    statuses = []
    for index in range(1_000):
        statuses.append({
            "crew_id": f"crew-{index}-长",
            "name": "Astronaut 🚀 " + ("界" * 400),
            "ts": f"2026-11-{(index % 28) + 1:02d}T00:00:00Z",
            "systems": {"environment": "red" if index % 2 == 0 else "amber"},
            "alerts": [{
                "name": "Long alert 🚨",
                "level": "red" if index % 2 == 0 else "amber",
                "active": True,
                "fired": {"signal-长": {"value": "值" * 400, "band": "red", "provenance": "simulated"}},
                "response": {"crew": "保持安全程序" * 200},
            }],
        })

    output = build_briefing({"name": "long mission", "one_way_delay_s": 1}, statuses,
                            {"released": [], "pending": []})
    text = output.decode("utf-8")

    assert len(output) < 50_000
    assert "total crew: 1000" in text
    assert "active=1000 | resolved-to-review=0" in text
    assert "crew_summary_omitted=680" in text
    assert "alert_details_omitted=" in text
    assert "Counts above cover all supplied backend statuses" in text
    assert "Astronaut 🚀" in text
