# Solar Radiation Anomaly QC: Output Guide

This document explains the output from running `Solar Radiation Data Cleanup.py` on the six met-station solar radiation files.

## What the code does

The routine cleans and summarizes solar radiation anomalies in five passes. **The timestamps are a data column here**, and the code uses station latitude/longitude plus `America/Chicago` sunrise and sunset times to determine whether each record is daytime or night-time.

**Pass one - input parsing.** `load_raw_data()` locates the Campbell logger header row, parses `TIMESTAMP`, coerces numeric columns, sorts records by time, and keeps the original observations.

**Pass two - daylight window.** `add_daylight_columns()` calculates sunrise and sunset for each station/date and adds a 30-minute buffer around the daylight window.

**Pass three - night-time radiation anomaly.** `apply_night_qc()` flags night records where `SlrW_Avg > 5 W/m^2`. These records are the only anomaly class directly changed by the cleaning step: their `SlrW_Avg_clean` value is set to `NA`.

**Pass four - daytime anomaly detection.** `detect_anomalies()` flags long daytime zero/near-zero runs, sudden drops, sudden spikes, missing daytime solar values, and out-of-range physical values. `classify_anomalies()` also labels possible weather-related low-solar periods when low radiation coincides with rain or very high relative humidity.

**Pass five - summary outputs.** The code writes cleaned station CSVs, detailed continuous-period anomaly tables, and simplified station/category tables used for the report figure.

---

## Anomaly statistics

Generated from the combined anomaly summary CSVs in this report.

### Overall

- **Files scanned:** 6 met station files
- **Cleaned records across all files:** 495,983
- **Anomaly records logged:** 21,459 (**4.33%** of cleaned records)
- **Continuous anomaly periods logged:** 10,776
- **Cleaned output files:** 6
- **Stations with at least one anomaly:** 6 of 6

### Major anomaly categories

| Category | Included detailed types | Records | % of anomalies | Stations affected | Treatment |
| --- | --- | --- | --- | --- | --- |
| Daytime low-radiation anomaly | Long daytime zero/near-zero run; Sudden radiation drop; Possible weather-related drop | 16,741 | 78.0% | 6 / 6 | Flagged for review; retained unless night-time QC already set NA. |
| Night-time radiation anomaly | Night-time radiation anomaly | 2,274 | 10.6% | 6 / 6 | Cleaned to NA in SlrW_Avg_clean. |
| Missing data/timestamp-gap anomaly | Missing data run; Timestamp gap | 2,199 | 10.2% | 4 / 6 | Logged as missing values or estimated missing timestamps. |
| Spike/out-of-range radiation anomaly | Sudden radiation spike; Out-of-range value | 245 | 1.1% | 6 / 6 | Flagged for review; retained in cleaned output. |

### Detailed anomaly types

| Detailed anomaly type | Periods/runs | Records | Treatment |
| --- | --- | --- | --- |
| Possible weather-related drop | 7,007 | 13,322 | Flagged with rain or high-RH context; original value retained. |
| Long daytime zero/near-zero run | 859 | 3,239 | Flagged for review; original value retained in cleaned output. |
| Night-time radiation anomaly | 2,190 | 2,274 | Set SlrW_Avg_clean to NA for night records above 5 W/m^2. |
| Timestamp gap | 191 | 2,076 | Logged as estimated missing records between consecutive timestamps. |
| Sudden radiation spike | 245 | 245 | Flagged for review; original value retained in cleaned output. |
| Sudden radiation drop | 234 | 234 | Flagged for review; original value retained in cleaned output. |
| Missing data run | 50 | 123 | Flagged as missing daytime solar records. |

### Per-station

Stations are sorted by total anomaly records.

| Station | Cleaned rows | Total anomaly records | % records anomalous | Daytime low | Night-time | Missing/gap | Spike/range | First anomaly | Last anomaly |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CB04 | 99,010 | 5,992 | 6.052% | 5,451 | 298 | 192 | 51 | 2014-11-13 19:00:00 | 2026-02-24 08:00:00 |
| WC05 | 97,131 | 5,345 | 5.503% | 2,743 | 549 | 2,000 | 53 | 2014-11-13 19:00:00 | 2026-02-23 19:00:00 |
| FD02 | 100,117 | 3,841 | 3.837% | 3,340 | 452 | 1 | 48 | 2014-10-03 07:00:00 | 2026-02-23 19:00:00 |
| FD03 | 109,337 | 3,628 | 3.318% | 3,120 | 457 | 0 | 51 | 2016-04-27 07:00:00 | 2026-02-23 19:00:00 |
| CB06 | 74,790 | 2,157 | 2.884% | 1,696 | 419 | 6 | 36 | 2017-02-04 08:00:00 | 2025-08-02 15:00:00 |
| CB01 | 15,598 | 496 | 3.180% | 391 | 99 | 0 | 6 | 2022-06-09 06:00:00 | 2024-03-18 07:00:00 |

### Outputs generated

| Output | Path | Contents |
| --- | --- | --- |
| Cleaned station files | Cleaned_Data/*_met_cleaned.csv | 6 files |
| Station-level simplified summary | anomaly_tables/*_simplified_anomaly_summary.csv | One row per station and major anomaly category |
| Combined simplified summary | anomaly_tables/combined_simplified_anomaly_summary.csv | 24 rows |
| Detailed anomaly summary | anomaly_tables/combined_anomaly_summary.csv | 10,776 continuous anomaly periods |
| Distribution figure | Cleaned_Data/anomaly_distribution_by_dataset.png | Stacked count/rate chart |


<img width="2400" height="1350" alt="anomaly_distribution_by_dataset" src="https://github.com/user-attachments/assets/1724b62d-c578-48f2-bc42-50979e03e07c" />
