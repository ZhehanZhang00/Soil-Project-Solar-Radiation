from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from astral import Observer
from astral.sun import sun


TIMESTAMP_COL = "TIMESTAMP"
SOLAR_COL = "SlrW_Avg"
TIMEZONE = "America/Chicago"

STATION_LOCATIONS = {
    "CB01": {"latitude": 30.4193, "longitude": -98.8046},
    "CB04": {"latitude": 30.4600, "longitude": -98.9407},
    "CB06": {"latitude": 30.4421, "longitude": -98.8427},
    "FD02": {"latitude": 30.2456, "longitude": -98.6988},
    "FD03": {"latitude": 30.4175, "longitude": -98.8542},
    "WC05": {"latitude": 30.4319, "longitude": -98.8133},
}


@dataclass(frozen=True)
class QCConfig:
    night_threshold: float = 5.0
    sunrise_sunset_buffer_minutes: int = 30
    near_zero_threshold: float = 5.0
    sudden_near_zero_threshold: float = 20.0
    high_radiation_threshold: float = 200.0
    sudden_jump_threshold: float = 500.0
    physical_min: float = 0.0
    physical_max: float = 1300.0
    min_zero_run_records: int = 3
    min_missing_run_records: int = 2
    weather_low_solar_threshold: float = 50.0
    weather_high_rh_threshold: float = 95.0
    write_detailed_summary: bool = True


ANOMALY_FLAGS = {
    "night_qc_flag": "Night-time radiation anomaly",
    "long_zero_run_flag": "Long daytime zero/near-zero run",
    "sudden_drop_flag": "Sudden radiation drop",
    "sudden_spike_flag": "Sudden radiation spike",
    "missing_run_flag": "Missing data run",
    "out_of_range_flag": "Out-of-range value",
}

OUTPUT_COLUMNS = [
    "file_name",
    "station_id",
    "anomaly_type",
    "start_time",
    "end_time",
    "duration",
    "number_of_records",
    f"min_{SOLAR_COL}",
    f"max_{SOLAR_COL}",
    f"mean_{SOLAR_COL}",
    "notes",
]

SIMPLIFIED_OUTPUT_COLUMNS = [
    "file_name",
    "station_id",
    "major_anomaly_category",
    "included_anomaly_types",
    "number_of_anomaly_records",
    "first_occurrence",
    "last_occurrence",
    "percentage_of_total_records",
    "notes",
]

MAJOR_ANOMALY_CATEGORIES = {
    "Night-time radiation anomaly": {
        "flag_columns": ["night_qc_flag"],
        "anomaly_types": ["Night-time radiation anomaly"],
        "notes": "Night-time solar radiation above the QC threshold.",
    },
    "Daytime low-radiation anomaly": {
        "flag_columns": ["long_zero_run_flag", "sudden_drop_flag"],
        "anomaly_types": [
            "Long daytime zero/near-zero run",
            "Sudden radiation drop",
            "Possible weather-related drop",
        ],
        "notes": "Daytime records with sustained low radiation, sudden drops, or likely weather-related low radiation.",
    },
    "Spike/out-of-range radiation anomaly": {
        "flag_columns": ["sudden_spike_flag", "out_of_range_flag"],
        "anomaly_types": ["Sudden radiation spike", "Out-of-range value"],
        "notes": "Daytime records with abrupt positive jumps or values outside the configured physical range.",
    },
    "Missing data/timestamp-gap anomaly": {
        "flag_columns": ["missing_run_flag"],
        "anomaly_types": ["Missing data run", "Timestamp gap"],
        "notes": "Missing daytime sensor values or missing timestamps between consecutive records.",
    },
}


# Locate the true CSV header after the station metadata preamble.
def find_header_row(file_path: Path) -> int:
    """Find the Campbell logger header row so metadata above the CSV is ignored."""
    with file_path.open("r", encoding="utf-8", errors="replace") as file:
        for row_number, line in enumerate(file):
            if TIMESTAMP_COL in line and SOLAR_COL in line:
                return row_number
    raise ValueError(f"Could not find {TIMESTAMP_COL}/{SOLAR_COL} header in {file_path}")


# Extract the monitoring station id from the input file name.
def station_id_from_file(file_path: Path) -> str:
    """Use the station prefix in names such as CB01_met.dat as the station id."""
    return file_path.stem.split("_")[0].split("-")[0]


# Load raw station data, clean metadata rows, parse time, and sort records.
def load_raw_data(file_path: Path) -> pd.DataFrame:
    """Read one station file, parse timestamps, coerce numeric columns, and sort by time."""
    header_row = find_header_row(file_path)
    df = pd.read_csv(file_path, skiprows=header_row, on_bad_lines="skip", low_memory=False)

    df[TIMESTAMP_COL] = pd.to_datetime(
        df[TIMESTAMP_COL], format="%Y-%m-%d %H:%M:%S", errors="coerce"
    )
    df = df.dropna(subset=[TIMESTAMP_COL]).copy()

    for column in df.columns:
        if column != TIMESTAMP_COL:
            df[column] = pd.to_numeric(df[column], errors="coerce")

    return df.sort_values(TIMESTAMP_COL).reset_index(drop=True)


# Estimate the expected time interval between sensor records.
def infer_sampling_interval(df: pd.DataFrame) -> pd.Timedelta:
    """Estimate the normal record spacing for duration and timestamp-gap summaries."""
    intervals = df[TIMESTAMP_COL].diff().dropna()
    if intervals.empty:
        return pd.Timedelta(0)
    return intervals.median()


# Add sunrise/sunset-based daylight flags with the configured buffer.
def add_daylight_columns(df: pd.DataFrame, station_id: str, config: QCConfig) -> pd.DataFrame:
    """Calculate sunrise/sunset once per date and mark whether each record is inside the QC daylight window."""
    location = STATION_LOCATIONS[station_id]
    observer = Observer(latitude=location["latitude"], longitude=location["longitude"])
    timezone = ZoneInfo(TIMEZONE)
    out = df.copy()
    dates = out[TIMESTAMP_COL].dt.date

    sunrise_by_date = {}
    sunset_by_date = {}
    for date_value in dates.drop_duplicates():
        sun_times = sun(observer, date=date_value, tzinfo=timezone)
        sunrise_by_date[date_value] = sun_times["sunrise"].replace(tzinfo=None)
        sunset_by_date[date_value] = sun_times["sunset"].replace(tzinfo=None)

    out["_sunrise"] = pd.to_datetime(dates.map(sunrise_by_date))
    out["_sunset"] = pd.to_datetime(dates.map(sunset_by_date))
    buffer = pd.Timedelta(minutes=config.sunrise_sunset_buffer_minutes)
    out["_is_daytime"] = (
        (out[TIMESTAMP_COL] >= out["_sunrise"] - buffer)
        & (out[TIMESTAMP_COL] <= out["_sunset"] + buffer)
    )
    return out


# Identify continuous anomaly runs that are long enough to flag.
def flag_long_runs(mask: pd.Series, min_records: int) -> pd.Series:
    """Return True only for continuous True runs that meet the minimum run length."""
    mask = mask.fillna(False)
    run_id = mask.ne(mask.shift(fill_value=False)).cumsum()
    run_length = mask.groupby(run_id).transform("sum")
    return mask & (run_length >= min_records)


# Apply night-time QC and set flagged solar radiation values to missing.
def apply_night_qc(df: pd.DataFrame, config: QCConfig) -> pd.DataFrame:
    """Mark night records with non-trivial radiation and set those cleaned values to NA."""
    out = df.copy()
    out[f"{SOLAR_COL}_clean"] = out[SOLAR_COL]
    is_night = ~out["_is_daytime"]
    out["night_qc_flag"] = is_night & (out[SOLAR_COL] > config.night_threshold)
    out.loc[out["night_qc_flag"], f"{SOLAR_COL}_clean"] = np.nan
    return out


# Detect daytime solar radiation anomalies using rule-based checks.
def detect_anomalies(df: pd.DataFrame, config: QCConfig) -> pd.DataFrame:
    """Apply rule-based daytime checks after night-time QC has been applied."""
    out = df.copy()
    solar_clean = out[f"{SOLAR_COL}_clean"]
    solar_raw = out[SOLAR_COL]
    daytime = out["_is_daytime"]
    valid_daytime = daytime & solar_clean.notna()

    near_zero_day = valid_daytime & (solar_clean <= config.near_zero_threshold)
    out["long_zero_run_flag"] = flag_long_runs(
        near_zero_day, min_records=config.min_zero_run_records
    )

    previous_solar = solar_clean.shift(1)
    previous_daytime = daytime.shift(1, fill_value=False)
    out["sudden_drop_flag"] = (
        daytime
        & previous_daytime
        & previous_solar.ge(config.high_radiation_threshold)
        & solar_clean.le(config.sudden_near_zero_threshold)
        & (previous_solar - solar_clean).ge(config.high_radiation_threshold)
    )

    out["sudden_spike_flag"] = (
        valid_daytime
        & previous_daytime
        & previous_solar.notna()
        & (solar_clean - previous_solar).ge(config.sudden_jump_threshold)
    )

    missing_daytime = daytime & solar_raw.isna()
    out["missing_run_flag"] = flag_long_runs(
        missing_daytime, min_records=config.min_missing_run_records
    )

    out["out_of_range_flag"] = daytime & (
        solar_raw.lt(config.physical_min) | solar_raw.gt(config.physical_max)
    )
    return out


# Mark low daytime radiation that may be explained by rain or high humidity.
def weather_related_drop_mask(df: pd.DataFrame, config: QCConfig) -> pd.Series:
    """Use rain or very high relative humidity to label low-solar daytime drops as weather-related."""
    rain = pd.Series(0.0, index=df.index)
    humidity = pd.Series(np.nan, index=df.index)
    if "Rain_mm_Tot" in df.columns:
        rain = df["Rain_mm_Tot"].fillna(0)
    if "RH" in df.columns:
        humidity = df["RH"]

    weather_context = rain.gt(0) | humidity.ge(config.weather_high_rh_threshold)
    return (
        df["_is_daytime"]
        & df[f"{SOLAR_COL}_clean"].notna()
        & df[f"{SOLAR_COL}_clean"].le(config.weather_low_solar_threshold)
        & weather_context
        & ~df["long_zero_run_flag"]
    )


# Combine detailed anomaly flags into a readable classification column.
def classify_anomalies(df: pd.DataFrame, config: QCConfig) -> pd.DataFrame:
    """Build a readable anomaly classification column without deleting daytime anomalies."""
    out = df.copy()
    labels = pd.Series("", index=out.index, dtype="object")

    for flag_column, anomaly_type in ANOMALY_FLAGS.items():
        mask = out[flag_column].fillna(False)
        labels.loc[mask] = labels.loc[mask].where(
            labels.loc[mask].eq(""), labels.loc[mask] + "; "
        ) + anomaly_type

    weather_mask = weather_related_drop_mask(out, config)
    labels.loc[weather_mask] = labels.loc[weather_mask].where(
        labels.loc[weather_mask].eq(""), labels.loc[weather_mask] + "; "
    ) + "Possible weather-related drop"

    out["anomaly_classification"] = labels.replace("", pd.NA)
    return out


# Convert anomaly start/end times into an inclusive duration string.
def duration_text(start_time: pd.Timestamp, end_time: pd.Timestamp, interval: pd.Timedelta) -> str:
    """Represent each anomaly period as an inclusive duration based on the sampling interval."""
    duration = end_time - start_time
    if interval > pd.Timedelta(0):
        duration += interval
    return str(duration)


# Generate threshold notes for each detailed anomaly type.
def anomaly_notes(anomaly_type: str, config: QCConfig) -> str:
    """Attach short threshold notes so the summary table is self-documenting."""
    notes = {
        "Night-time radiation anomaly": f"Night record with {SOLAR_COL} > {config.night_threshold} W/m^2; cleaned value set to NA.",
        "Long daytime zero/near-zero run": f"At least {config.min_zero_run_records} daytime records <= {config.near_zero_threshold} W/m^2.",
        "Sudden radiation drop": f"Previous daytime record >= {config.high_radiation_threshold} W/m^2 and current record <= {config.sudden_near_zero_threshold} W/m^2.",
        "Sudden radiation spike": f"Increase from previous daytime record >= {config.sudden_jump_threshold} W/m^2.",
        "Missing data run": f"At least {config.min_missing_run_records} consecutive daytime missing {SOLAR_COL} records.",
        "Out-of-range value": f"Daytime value outside {config.physical_min}-{config.physical_max} W/m^2.",
        "Possible weather-related drop": f"Daytime {SOLAR_COL} <= {config.weather_low_solar_threshold} W/m^2 with rain or RH >= {config.weather_high_rh_threshold}%.",
    }
    return notes[anomaly_type]


# Convert a row-level anomaly mask into detailed continuous-period summary rows.
def summarize_mask(
    df: pd.DataFrame,
    mask: pd.Series,
    anomaly_type: str,
    file_name: str,
    station_id: str,
    interval: pd.Timedelta,
    config: QCConfig,
) -> list[dict]:
    """Collapse each continuous anomaly mask into one summary-table row."""
    rows = []
    mask = mask.fillna(False)
    if not mask.any():
        return rows

    gap_break = df[TIMESTAMP_COL].diff().gt(interval * 1.5) if interval > pd.Timedelta(0) else False
    run_id = (mask.ne(mask.shift(fill_value=False)) | gap_break).cumsum()

    for _, group in df.loc[mask].groupby(run_id[mask]):
        solar_values = group[SOLAR_COL]
        start_time = group[TIMESTAMP_COL].iloc[0]
        end_time = group[TIMESTAMP_COL].iloc[-1]
        rows.append(
            {
                "file_name": file_name,
                "station_id": station_id,
                "anomaly_type": anomaly_type,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration_text(start_time, end_time, interval),
                "number_of_records": len(group),
                f"min_{SOLAR_COL}": solar_values.min(skipna=True),
                f"max_{SOLAR_COL}": solar_values.max(skipna=True),
                f"mean_{SOLAR_COL}": solar_values.mean(skipna=True),
                "notes": anomaly_notes(anomaly_type, config),
            }
        )
    return rows


# Summarize missing timestamp gaps as detailed missing-data anomaly rows.
def summarize_timestamp_gaps(
    df: pd.DataFrame,
    file_name: str,
    station_id: str,
    interval: pd.Timedelta,
) -> list[dict]:
    """Add summary rows for missing timestamps that cannot be represented by row-level flags."""
    if interval <= pd.Timedelta(0):
        return []

    rows = []
    for gap in timestamp_gap_periods(df, interval):
        rows.append(
            {
                "file_name": file_name,
                "station_id": station_id,
                "anomaly_type": "Timestamp gap",
                "start_time": gap["start_time"],
                "end_time": gap["end_time"],
                "duration": str(gap["duration"]),
                "number_of_records": gap["missing_records"],
                f"min_{SOLAR_COL}": np.nan,
                f"max_{SOLAR_COL}": np.nan,
                f"mean_{SOLAR_COL}": np.nan,
                "notes": "Timestamp gap detected between consecutive records.",
            }
        )
    return rows


# Find periods where expected timestamps are absent from the data.
def timestamp_gap_periods(df: pd.DataFrame, interval: pd.Timedelta) -> list[dict]:
    """Estimate missing timestamp periods from gaps larger than the normal sampling interval."""
    if interval <= pd.Timedelta(0):
        return []

    periods = []
    gaps = df[TIMESTAMP_COL].diff()
    gap_mask = gaps.gt(interval * 1.5)
    for index in df.index[gap_mask]:
        previous_time = df.loc[index - 1, TIMESTAMP_COL]
        current_time = df.loc[index, TIMESTAMP_COL]
        missing_start = previous_time + interval
        missing_end = current_time - interval
        if missing_start > missing_end:
            missing_start = previous_time
            missing_end = current_time
        missing_records = max(int(round(gaps.loc[index] / interval)) - 1, 1)
        periods.append(
            {
                "start_time": missing_start,
                "end_time": missing_end,
                "duration": current_time - previous_time - interval,
                "missing_records": missing_records,
            }
        )
    return periods


# Build the optional detailed anomaly summary for one station file.
def build_anomaly_summary(
    df: pd.DataFrame,
    file_name: str,
    station_id: str,
    config: QCConfig,
) -> pd.DataFrame:
    """Create one station-level anomaly summary with one row per continuous period."""
    interval = infer_sampling_interval(df)
    rows = []

    for flag_column, anomaly_type in ANOMALY_FLAGS.items():
        rows.extend(
            summarize_mask(
                df=df,
                mask=df[flag_column],
                anomaly_type=anomaly_type,
                file_name=file_name,
                station_id=station_id,
                interval=interval,
                config=config,
            )
        )

    weather_mask = df["anomaly_classification"].fillna("").str.contains(
        "Possible weather-related drop", regex=False
    )
    rows.extend(
        summarize_mask(
            df=df,
            mask=weather_mask,
            anomaly_type="Possible weather-related drop",
            file_name=file_name,
            station_id=station_id,
            interval=interval,
            config=config,
        )
    )
    rows.extend(summarize_timestamp_gaps(df, file_name, station_id, interval))

    summary = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not summary.empty:
        summary = summary.sort_values(["station_id", "start_time", "anomaly_type"]).reset_index(
            drop=True
        )
    return summary


# Merge detailed flags into one mask for a major anomaly category.
def major_category_mask(
    df: pd.DataFrame,
    category_name: str,
    category_info: dict,
    config: QCConfig,
) -> pd.Series:
    """Combine detailed flags into one row-level mask for a major anomaly category."""
    mask = pd.Series(False, index=df.index)
    for flag_column in category_info["flag_columns"]:
        mask = mask | df[flag_column].fillna(False)

    if category_name == "Daytime low-radiation anomaly":
        mask = mask | weather_related_drop_mask(df, config)

    return mask


# Build the main simplified summary with one row per station/category.
def build_simplified_anomaly_summary(
    df: pd.DataFrame,
    file_name: str,
    station_id: str,
    config: QCConfig,
) -> pd.DataFrame:
    """Summarize anomalies as one row per station and broad anomaly category."""
    interval = infer_sampling_interval(df)
    total_records = len(df)
    gap_periods = timestamp_gap_periods(df, interval)
    rows = []

    for category_name, category_info in MAJOR_ANOMALY_CATEGORIES.items():
        mask = major_category_mask(df, category_name, category_info, config)
        record_count = int(mask.sum())
        occurrence_starts = []
        occurrence_ends = []

        if record_count:
            occurrence_starts.append(df.loc[mask, TIMESTAMP_COL].min())
            occurrence_ends.append(df.loc[mask, TIMESTAMP_COL].max())

        if category_name == "Missing data/timestamp-gap anomaly":
            gap_records = sum(gap["missing_records"] for gap in gap_periods)
            record_count += gap_records
            occurrence_starts.extend(gap["start_time"] for gap in gap_periods)
            occurrence_ends.extend(gap["end_time"] for gap in gap_periods)

        first_occurrence = min(occurrence_starts) if occurrence_starts else pd.NaT
        last_occurrence = max(occurrence_ends) if occurrence_ends else pd.NaT
        percentage = (record_count / total_records * 100) if total_records else 0.0
        notes = category_info["notes"]
        if record_count == 0:
            notes = f"No records found. {notes}"

        rows.append(
            {
                "file_name": file_name,
                "station_id": station_id,
                "major_anomaly_category": category_name,
                "included_anomaly_types": "; ".join(category_info["anomaly_types"]),
                "number_of_anomaly_records": record_count,
                "first_occurrence": first_occurrence,
                "last_occurrence": last_occurrence,
                "percentage_of_total_records": round(percentage, 3),
                "notes": notes,
            }
        )

    return pd.DataFrame(rows, columns=SIMPLIFIED_OUTPUT_COLUMNS)


# Order cleaned output columns with original data first and QC fields last.
def cleaned_output_columns(df: pd.DataFrame) -> list[str]:
    """Keep original columns first, followed by cleaned solar data, flags, and classification."""
    helper_columns = {"_sunrise", "_sunset", "_is_daytime"}
    original_columns = [
        column
        for column in df.columns
        if column not in helper_columns
        and column != f"{SOLAR_COL}_clean"
        and column not in ANOMALY_FLAGS
        and column != "anomaly_classification"
    ]
    return (
        original_columns
        + [f"{SOLAR_COL}_clean"]
        + list(ANOMALY_FLAGS)
        + ["anomaly_classification"]
    )


# Run the full QC workflow for one station file and write its outputs.
def process_file(
    file_path: Path,
    cleaned_dir: Path,
    anomaly_dir: Path,
    config: QCConfig,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run the full raw-data to clean-data workflow for one station file."""
    station_id = station_id_from_file(file_path)
    if station_id not in STATION_LOCATIONS:
        raise ValueError(f"No latitude/longitude configured for station {station_id}")

    df = load_raw_data(file_path)
    df = add_daylight_columns(df, station_id, config)
    df = apply_night_qc(df, config)
    df = detect_anomalies(df, config)
    df = classify_anomalies(df, config)

    cleaned_file = cleaned_dir / f"{file_path.stem}_cleaned.csv"
    df.loc[:, cleaned_output_columns(df)].to_csv(cleaned_file, index=False)

    simplified_summary = build_simplified_anomaly_summary(df, file_path.name, station_id, config)
    simplified_file = anomaly_dir / f"{file_path.stem}_simplified_anomaly_summary.csv"
    simplified_summary.to_csv(simplified_file, index=False)

    detailed_summary = pd.DataFrame(columns=OUTPUT_COLUMNS)
    if config.write_detailed_summary:
        detailed_summary = build_anomaly_summary(df, file_path.name, station_id, config)
        detailed_file = anomaly_dir / f"{file_path.stem}_anomaly_summary.csv"
        detailed_summary.to_csv(detailed_file, index=False)

    return simplified_summary, detailed_summary


# Find all configured station input files in the selected folder.
def find_input_files(input_dir: Path) -> list[Path]:
    """Collect station input files from the input folder without recursing into outputs."""
    files = sorted(input_dir.glob("*_met.dat")) + sorted(input_dir.glob("*_met.csv"))
    return [file_path for file_path in files if station_id_from_file(file_path) in STATION_LOCATIONS]


# Process all station files and write combined cleaned/QC summary outputs.
def run_pipeline(input_dir: Path = Path("."), config: QCConfig = QCConfig()) -> pd.DataFrame:
    """Process all station files and write cleaned files plus simplified and optional detailed summaries."""
    cleaned_dir = input_dir / "cleaned_data"
    anomaly_dir = input_dir / "anomaly_tables"
    cleaned_dir.mkdir(exist_ok=True)
    anomaly_dir.mkdir(exist_ok=True)

    simplified_summaries = []
    detailed_summaries = []
    for file_path in find_input_files(input_dir):
        print(f"Processing {file_path.name}...")
        simplified_summary, detailed_summary = process_file(
            file_path, cleaned_dir, anomaly_dir, config
        )
        simplified_summaries.append(simplified_summary)
        if config.write_detailed_summary:
            detailed_summaries.append(detailed_summary)

    combined_simplified = (
        pd.concat(simplified_summaries, ignore_index=True)
        if simplified_summaries
        else pd.DataFrame(columns=SIMPLIFIED_OUTPUT_COLUMNS)
    )
    combined_simplified.to_csv(anomaly_dir / "simplified_anomaly_summary.csv", index=False)
    combined_simplified.to_csv(
        anomaly_dir / "combined_simplified_anomaly_summary.csv", index=False
    )

    if config.write_detailed_summary:
        combined_detailed = (
            pd.concat(detailed_summaries, ignore_index=True)
            if detailed_summaries
            else pd.DataFrame(columns=OUTPUT_COLUMNS)
        )
        combined_detailed.to_csv(anomaly_dir / "combined_anomaly_summary.csv", index=False)

    print(f"Processed {len(simplified_summaries)} station files.")
    print(f"Cleaned data: {cleaned_dir}")
    print(f"Anomaly tables: {anomaly_dir}")
    return combined_simplified


if __name__ == "__main__":
    run_pipeline()
