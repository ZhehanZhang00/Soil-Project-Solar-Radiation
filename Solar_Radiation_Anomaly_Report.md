# Solar Radiation Anomaly QC: Prewashed Data Output Guide

This report is generated from `prewashed_met_data/*_met.csv`. Compared with the raw `.dat` files, these files are already cleaned, standardized, de-duplicated, gap-filled in time, and ready for downstream quality control. The solar radiation variable evaluated here is `Srad`.

## What the code does

**Pass one - load prewashed station files.** The script reads `Date`, `Srad`, precipitation, humidity, wind, ET, and clear-sky reference columns from the standardized CSV files.

**Pass two - verify data readiness.** It reports row counts, unique timestamps, duplicate rows, timestamp gaps, and missing `Srad` values. The current prewashed files have no duplicate timestamps and no hourly timestamp gaps.

**Pass three - daylight context.** Station latitude/longitude and `America/Chicago` sunrise/sunset times are used to separate daytime and night-time records with a 30-minute buffer.

**Pass four - anomaly marking.** The script marks night-time radiation, long daytime near-zero runs, sudden drops, possible weather-related low radiation, missing `Srad`, sudden spikes, and physical out-of-range values. No imputation is performed.

**Pass five - reporting.** It writes row-level marked files, station-level summary tables, a combined detailed table, and the anomaly distribution figure.

---

## Data Readiness Check

| Station | Rows | Unique timestamps | Exact duplicate rows | Timestamp gap records | Missing Srad | Min Srad | Max Srad |
| --- | --- | --- | --- | --- | --- | --- | --- |
| CB01 | 15,597 | 15,597 | 0 | 0 | 0 | 0 | 1.05e+03 |
| CB04 | 98,907 | 98,907 | 0 | 0 | 232 | 0 | 1.1e+03 |
| CB06 | 74,596 | 74,596 | 0 | 0 | 4 | 0 | 1.11e+03 |
| FD02 | 99,914 | 99,914 | 0 | 0 | 1 | 0 | 1.12e+03 |
| FD03 | 86,211 | 86,211 | 0 | 0 | 0 | 0 | 1.12e+03 |
| WC05 | 98,902 | 98,902 | 0 | 0 | 2,020 | 0 | 1.18e+03 |

## Anomaly Statistics

### Overall

- **Files scanned:** 6 prewashed met station files
- **Prewashed records across all files:** 474,127
- **Anomaly records logged:** 18,117 (**3.82%** of prewashed records)
- **Continuous anomaly periods logged:** 9,368
- **Stations with at least one anomaly:** 6 of 6

### Major anomaly categories

| Category | Included detailed types | Records | % of anomalies | Stations affected | Treatment |
| --- | --- | --- | --- | --- | --- |
| Daytime low-radiation anomaly | Long daytime zero/near-zero run; Sudden radiation drop; Possible weather-related low radiation | 13,420 | 74.1% | 6 / 6 | Flag for review. Do not impute weather-supported low radiation by default. |
| Night-time radiation anomaly | Night-time radiation anomaly | 2,198 | 12.1% | 6 / 6 | Flag for review. Candidate for setting to 0 or NA after confirmation. |
| Missing Srad/timestamp anomaly | Missing Srad value; Timestamp gap | 2,257 | 12.5% | 4 / 6 | Flag as missing. Candidate for solar-aware imputation after review. |
| Spike/out-of-range radiation anomaly | Sudden radiation spike; Out-of-range value | 242 | 1.3% | 6 / 6 | Flag for review. Candidate for replacement before imputation. |

### Detailed anomaly types

| Detailed anomaly type | Periods/runs | Records | Treatment |
| --- | --- | --- | --- |
| Possible weather-related low radiation | 6,008 | 11,440 | Flagged with precipitation or high-RH context; usually retain. |
| Missing Srad value | 300 | 2,257 | Flagged as missing; candidate for imputation. |
| Night-time radiation anomaly | 2,190 | 2,198 | Flagged; no imputation applied. |
| Long daytime zero/near-zero run | 394 | 1,788 | Flagged; retain if weather or sensor context supports it. |
| Sudden radiation spike | 242 | 242 | Flagged; candidate for replacement before imputation. |
| Sudden radiation drop | 234 | 234 | Flagged; no imputation applied. |

### Per-station

Stations are sorted by total anomaly records.

| Station | Prewashed rows | Total anomaly records | % records anomalous | Daytime low | Night-time | Missing Srad/gap | Spike/range | First anomaly | Last anomaly |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| WC05 | 98,902 | 5,364 | 5.424% | 2,743 | 549 | 2,020 | 52 | 2014-11-13 19:00:00 | 2026-02-23 19:00:00 |
| CB04 | 98,907 | 4,440 | 4.489% | 3,860 | 298 | 232 | 50 | 2014-11-13 19:00:00 | 2026-02-22 19:00:00 |
| FD02 | 99,914 | 3,836 | 3.839% | 3,335 | 452 | 1 | 48 | 2014-10-03 07:00:00 | 2026-02-23 19:00:00 |
| CB06 | 74,596 | 2,139 | 2.867% | 1,681 | 419 | 4 | 35 | 2017-02-04 08:00:00 | 2025-08-02 15:00:00 |
| FD03 | 86,211 | 1,842 | 2.137% | 1,410 | 381 | 0 | 51 | 2016-04-27 07:00:00 | 2026-02-23 19:00:00 |
| CB01 | 15,597 | 496 | 3.180% | 391 | 99 | 0 | 6 | 2022-06-09 06:00:00 | 2024-03-18 07:00:00 |

## Imputation Plan Not Yet Applied

The script only marks anomalous `Srad` values. Imputation should be a separate downstream step so the original prewashed observations and QC flags remain auditable.

| Anomaly class | Suggested imputation decision |
|---|---|
| Night-time radiation anomaly | If confirmed as sensor offset/noise, replace with 0 for radiation-balance workflows or set to NA for conservative analyses. Keep an imputation flag. |
| Missing Srad value or timestamp gap | For short gaps, use solar-aware interpolation constrained by hour-of-day and daylight/night status. For longer gaps, use seasonal/hourly climatology, nearby stations, or a model using `Rso`, `Tair`, `RH`, `Ppt`, and wind variables. |
| Spike/out-of-range radiation anomaly | Treat as invalid first, then impute using neighboring hours/stations or a clear-sky-constrained model. |
| Daytime low-radiation anomaly | Do not automatically impute if precipitation or high RH supports cloudy/rainy conditions. Only impute sustained zero/near-zero runs after sensor-failure review. |

Recommended safeguards for any later imputation:

- Preserve the original `Srad` column and write imputed values to a new column such as `Srad_imputed`.
- Add columns such as `Srad_imputed_flag` and `Srad_imputation_method`.
- Enforce physical bounds: `Srad_imputed >= 0` and a reasonable upper bound, such as the configured 1300 W/m^2 threshold or a clear-sky envelope after unit harmonization.
- Evaluate imputation quality by station, season, hour, and anomaly type before using the data in downstream analysis.

## Outputs generated

| Output | Path | Contents |
| --- | --- | --- |
| Marked prewashed data | prewashed_anomaly_outputs/marked_data/*_anomaly_marked.csv | Original columns plus Srad anomaly flags |
| Station summaries | prewashed_anomaly_outputs/tables/*_simplified_anomaly_summary.csv | One row per station and major anomaly category |
| Combined simplified summary | prewashed_anomaly_outputs/tables/combined_simplified_anomaly_summary.csv | 24 rows |
| Combined detailed summary | prewashed_anomaly_outputs/tables/combined_detailed_anomaly_summary.csv | 9,368 continuous anomaly periods |
| Distribution figure | prewashed_anomaly_outputs/anomaly_distribution_by_dataset.png | Stacked count/rate chart |
