"""Validate Wokwi Serial JSON lines against contract/schema.py Reading."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contract.schema import Reading  # noqa: E402

DEFAULTS = {
    "resting_hr_bpm": 60.0,
    "rmssd_ms": 55.0,
    "cabin_co2_mmhg": 2.2,
    "lymphocytes_per_ul": 2679.0,
    "il6_pg_ml": 3.7,
    "nk_activity_pct": 100.0,
    "viral_pcr_positive": 0.0,
}

RANGES = {
    "resting_hr_bpm": (30.0, 130.0),
    "rmssd_ms": (0.0, 200.0),
    "cabin_co2_mmhg": (0.0, 10.0),
    "lymphocytes_per_ul": (0.0, 6000.0),
    "il6_pg_ml": (0.0, 25.0),
    "nk_activity_pct": (0.0, 150.0),
    "viral_pcr_positive": (0.0, 1.0),
}

ALLOWED_SIGNALS = set(DEFAULTS.keys())
BOOT_PREFIXES = (
    "ets ",
    "rst:",
    "configsip:",
    "clk_drv:",
    "mode:",
    "load:",
    "ho ",
    "entry ",
)


def validate_lines(lines: list[str], expect_defaults: bool = False) -> tuple[int, list[str]]:
    passed = 0
    errors: list[str] = []
    seen_json = False

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not seen_json and line.startswith(BOOT_PREFIXES):
            continue
        seen_json = True
        try:
            payload = json.loads(line)
            reading = Reading(**payload)
        except Exception as exc:
            errors.append(f"Line {lineno}: schema/JSON error: {exc} | {line}")
            continue

        if reading.signal not in ALLOWED_SIGNALS:
            errors.append(f"Line {lineno}: unexpected signal {reading.signal!r}")
            continue
        if reading.source != "wokwi":
            errors.append(f"Line {lineno}: expected source='wokwi', got {reading.source!r}")
            continue
        if reading.provenance != "simulated":
            errors.append(
                f"Line {lineno}: expected provenance='simulated', got {reading.provenance!r}"
            )
            continue

        if expect_defaults:
            target = DEFAULTS[reading.signal]
            # Spec §4: "within ~1% of the defaults"
            rel_tol = 0.0 if target == 0.0 else 0.015 * abs(target)
            if target == 0.0:
                if reading.value != 0.0:
                    errors.append(
                        f"Line {lineno}: {reading.signal}={reading.value}, expected 0"
                    )
                    continue
            elif abs(reading.value - target) > rel_tol:
                errors.append(
                    f"Line {lineno}: {reading.signal}={reading.value}, expected ~{target} (±1.5%)"
                )
                continue

        passed += 1

    return passed, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Wokwi Serial output.")
    parser.add_argument(
        "file",
        nargs="?",
        help="Path to captured Serial text file (reads stdin if omitted).",
    )
    parser.add_argument(
        "--expect-defaults",
        action="store_true",
        help="Also verify values match defaults within ~1%%.",
    )
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()

    passed, errors = validate_lines(text.splitlines(), expect_defaults=args.expect_defaults)
    print(f"Passed: {passed}, Failed: {len(errors)}")
    for err in errors:
        print(f"  ERROR: {err}", file=sys.stderr)
    return 1 if errors or passed == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
