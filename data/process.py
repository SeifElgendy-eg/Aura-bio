"""Turn data/raw/ into small tables in data/processed/ (see SOURCES.md for what each is for).

    uv run python data/process.py            # everything
    uv run python data/process.py radlab     # one source
"""
from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAW = Path(__file__).parent / "raw"
OUT = Path(__file__).parent / "processed"
PPM_PER_MMHG = 1e6 / 760  # CO2 partial pressure at 1 atm cabin pressure


# --- RadLab: daily absorbed dose per detector ---------------------------------------------
def daily_dose(df: pd.DataFrame) -> pd.DataFrame:
    """Time-weighted daily dose. Samples come every ~20 s in the South Atlantic Anomaly and ~90 s
    elsewhere, so a plain mean of the rate over-weights the high-dose passes."""
    out = []
    for inst, d in df.sort_values("timestamp").groupby("instrument_id"):
        dt = d["timestamp"].diff().dt.total_seconds().shift(-1).clip(upper=300).fillna(0)  # each rate holds until the next sample; cap gaps at 5 min
        dose_ugy = d["absorbed_dose_rate"] * dt / 3600
        g = pd.DataFrame({"date": d["timestamp"].dt.date, "dose": dose_ugy, "dt": dt})
        day = g.groupby("date").agg(covered_h=("dt", lambda s: s.sum() / 3600), dose_ugy=("dose", "sum"))
        day["absorbed_ugy_per_day"] = day["dose_ugy"] / day["covered_h"] * 24  # scale up partial days
        day["instrument_id"] = inst
        out.append(day.reset_index())
    res = pd.concat(out)
    return res[res["covered_h"] >= 20][["date", "instrument_id", "absorbed_ugy_per_day", "covered_h"]]


def radlab() -> pd.DataFrame:
    df = pd.concat(pd.read_csv(f) for f in sorted(glob.glob(str(RAW / "radlab/*.csv"))))
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return daily_dose(df.drop_duplicates(["timestamp", "instrument_id"]))


# --- EDA: daily ISS CO2 in mmHg --------------------------------------------------------------
def clean_co2(v: pd.Series, flat_run: int = 12) -> pd.Series:
    """NaN-out readings that are not real measurements: below 1000 ppm (under ~0.8 mmHg, never seen
    in the ISS cabin; outdoor air is ~420) or above 10000, and runs of >= flat_run identical values
    (1 h at 5-min cadence), which are gap fill, not sensor output."""
    run_len = v.groupby((v != v.shift()).cumsum()).transform("size")
    return v.where(v.between(1000, 10000) & (run_len < flat_run))


def eda() -> pd.DataFrame:
    out = []
    for f in sorted(glob.glob(str(RAW / "eda/*_co2_iss.json"))):
        d = pd.DataFrame(json.loads(Path(f).read_text()))
        if d.empty:
            continue
        d["co2"] = clean_co2(d["co2_iss"]) / PPM_PER_MMHG
        d["date"] = pd.to_datetime(d["time"]).dt.date
        day = d.groupby("date")["co2"].agg(co2_mmhg_mean="mean", co2_mmhg_min="min",
                                           co2_mmhg_max="max", n="count").reset_index()
        day["mission"] = Path(f).name.removesuffix("_co2_iss.json")
        out.append(day[day["n"] >= 72])  # >= 6 h of clean 5-min samples
    return pd.concat(out)[["mission", "date", "co2_mmhg_mean", "co2_mmhg_min", "co2_mmhg_max", "n"]]


# --- Inspiration4: one tidy table of every lab value ----------------------------------------
FLIGHT_DAYS = 3  # Inspiration4 flew 2021-09-15 to 2021-09-18
VALUE_COL = re.compile(r"^(?P<analyte>.+?)_(?:value|concentration)_?(?P<unit>.*)$")


def timepoint_day(tp: str) -> int:
    """'L-92' -> -92 (days before launch); 'R+1' -> 4 (days after launch, return is day 3)."""
    n = int(tp[1:])
    return n if tp[0] == "L" else FLIGHT_DAYS + n


def inspiration4() -> pd.DataFrame:
    out = []
    for f in sorted(glob.glob(str(RAW / "inspiration4/*/*_TRANSFORMED.csv"))):
        d = pd.read_csv(f, encoding="utf-8-sig")
        sample = d.columns[0]  # "Sample Name" or "Sample ID"
        panel = re.sub(r"^LSDS-\d+_|_TRANSFORMED\.csv$", "", Path(f).name)
        for col in d.columns:
            m = VALUE_COL.match(col)
            if not m:
                continue
            rmin = col.replace("_value_", "_range_min_")
            rmax = col.replace("_value_", "_range_max_")
            part = pd.DataFrame({
                "crew": d[sample].str.split("_").str[0],
                "timepoint": d[sample].str.extract(r"_([LR][+-]\d+)", expand=False),
                "panel": panel, "analyte": m["analyte"], "unit": m["unit"] or "ratio",
                "value": pd.to_numeric(d[col], errors="coerce"),
                "ref_min": pd.to_numeric(d[rmin], errors="coerce") if rmin in d else np.nan,
                "ref_max": pd.to_numeric(d[rmax], errors="coerce") if rmax in d else np.nan,
            })
            out.append(part)
    res = pd.concat(out).dropna(subset=["value"])
    res["day"] = res["timepoint"].map(timepoint_day)
    return res


def inspiration4_change(labs: pd.DataFrame) -> pd.DataFrame:
    """Per analyte: pre-flight mean (all L- samples) vs first post-flight sample (R+1), averaged
    over crew. Gives the direction and size of spaceflight change for the immune scenarios."""
    pre = labs[labs["day"] < 0].groupby(["panel", "analyte", "unit", "crew"])["value"].mean()
    post = labs[labs["timepoint"] == "R+1"].groupby(["panel", "analyte", "unit", "crew"])["value"].mean()
    pct = ((post - pre) / pre * 100).replace([np.inf, -np.inf], np.nan).dropna()
    g = pct.groupby(["panel", "analyte", "unit"])
    return pd.DataFrame({"pct_change_mean": g.mean(), "pct_change_min": g.min(),
                         "pct_change_max": g.max(), "n_crew": g.size(),
                         "preflight_mean": pre.groupby(["panel", "analyte", "unit"]).mean()}
                        ).dropna(subset=["pct_change_mean"]).reset_index()


# --- BIDSleep: per-night sleep metrics, then calibration for the simulator -------------------
EPOCH_S = 30
WAKE, UNKNOWN = 0, 5
SLEEP = (1, 2, 3, 4)  # N1, N2, N3, REM


def night_metrics(stages: np.ndarray, hr: pd.DataFrame, rec_start: float) -> dict:
    """stages: expert label per 30-s epoch from rec_start (unix s); hr: columns t (unix s), hr (bpm).
    Sleep efficiency = total sleep time / time in bed x 100 (standard PSG definition); time in bed is
    the whole recording minus Unknown epochs (signal lost, so neither asleep nor awake is known).
    Resting HR = lowest 30-min rolling mean of HR during sleep epochs (Garmin-style: averaging over
    30 min avoids the single-lowest-reading noise of Oura's method)."""
    asleep = np.isin(stages, SLEEP)
    tib_h = (stages != UNKNOWN).sum() * EPOCH_S / 3600
    k = ((hr["t"] - rec_start) // EPOCH_S).astype(int)
    in_sleep = (k >= 0) & (k < len(stages)) & asleep[k.clip(0, len(stages) - 1)]
    s = hr[in_sleep].set_index(pd.to_datetime(hr["t"][in_sleep], unit="s"))["hr"]
    roll = s.rolling("30min", min_periods=180).mean()  # >= 180 samples = ~15 min of 5-s HR in the window
    return {"sleep_duration_h": asleep.sum() * EPOCH_S / 3600,
            "sleep_efficiency_pct": 100 * asleep.sum() * EPOCH_S / 3600 / tib_h if tib_h else np.nan,
            "resting_hr_bpm": roll.min(),
            "time_in_bed_h": tib_h}


def bidsleep() -> pd.DataFrame:
    import scipy.io as sio
    rows = []
    for d in sorted((RAW / "bidsleep").glob("Bidslab*/*")):
        m = sio.loadmat(d / "labels.mat")
        # recStart is stored as human-readable US Eastern time (dataset README)
        start = pd.Timestamp(str(m["recStart"][0])).tz_localize("America/New_York").timestamp()
        hr = pd.read_csv(d / "hr.csv", header=None, names=["t", "hr"])
        rows.append({"subject": d.parent.name, "night": int(d.name),
                     **night_metrics(m["expert_label"].ravel(), hr, start)})
    return pd.DataFrame(rows)


def calibration(nights: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    """sim_mean = mean of subject means; sim_sd = pooled night-to-night SD within a subject;
    person_sd = SD of subject means (how much people differ from each other)."""
    g = nights.groupby("subject")[signals]
    return pd.DataFrame({"sim_mean": g.mean().mean(), "sim_sd": np.sqrt(g.var().mean()),
                         "person_sd": g.mean().std(), "n_subjects": g.ngroups,
                         "n_nights": len(nights)}).rename_axis("signal").reset_index()


BIDS_SIGNALS = ["resting_hr_bpm", "sleep_duration_h", "sleep_efficiency_pct"]


def bidsleep_outputs() -> dict:
    nights = bidsleep()
    return {"bidsleep_nights.csv": nights,
            "bidsleep_calibration.csv": calibration(nights.dropna(subset=BIDS_SIGNALS), BIDS_SIGNALS)}


SOURCES = {
    "bidsleep": bidsleep_outputs,
    "radlab": lambda: {"radlab_daily_dose.csv": radlab()},
    "eda": lambda: {"eda_co2_daily.csv": eda()},
    "inspiration4": lambda: (lambda labs: {"inspiration4_labs.csv": labs,
                                           "inspiration4_change.csv": inspiration4_change(labs)})(inspiration4()),
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for n in sys.argv[1:] or list(SOURCES):
        for name, df in SOURCES[n]().items():
            df.to_csv(OUT / name, index=False, float_format="%.4g")
            print(f"{name}: {len(df)} rows")


if __name__ == "__main__":
    main()
