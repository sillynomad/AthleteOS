#!/usr/bin/env python3
"""Inspect a user-exported Garmin Connect pool swim .FIT file locally.

Install: python -m pip install fitparse
Run: python tools/inspect_garmin_fit.py /path/to/activity.fit
No Garmin credentials or network requests; no data is uploaded.
"""
import argparse
import csv
import pathlib
import sys


def extract(path):
    from fitparse import FitFile
    fit = FitFile(str(path))
    fit.parse()
    sessions = list(fit.get_messages("session"))
    pool_length = None
    if sessions:
        session = {field.name: field.value for field in sessions[0]}
        pool_length = session.get("pool_length")
    lengths = []
    for msg in fit.get_messages("length"):
        data = {field.name: field.value for field in msg}
        if data.get("length_type") == "idle":
            continue
        duration = data.get("total_timer_time") or data.get("total_elapsed_time")
        strokes = data.get("total_strokes")
        # FIT length messages normally do not contain total_distance; pool length is in session.
        distance = data.get("total_distance") or pool_length
        if not isinstance(distance, (float, int)) or distance <= 0:
            continue
        if not isinstance(duration, (float, int)) or duration <= 0:
            continue
        pace = round(100 * duration / distance, 1)
        swolf = round(duration + strokes, 1) if isinstance(strokes, (float, int)) else None
        lengths.append({
            "length": len(lengths) + 1,
            "start_time": data.get("start_time"),
            "distance_m": distance,
            "duration_s": round(duration, 2),
            "pace_s_per_100m": pace,
            "strokes": strokes,
            "swolf_estimate": swolf,
            "stroke_type": data.get("swim_stroke"),
            "avg_hr": data.get("avg_heart_rate"),
        })
    return lengths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fit_file", type=pathlib.Path)
    parser.add_argument("--csv", type=pathlib.Path, help="Optional CSV output path")
    args = parser.parse_args()
    if not args.fit_file.is_file():
        parser.error("FIT file not found")
    try:
        lengths = extract(args.fit_file)
    except ImportError:
        parser.error("Install fitparse first: python -m pip install fitparse")
    except Exception as exc:
        parser.error("Could not parse FIT file: " + str(exc))
    if not lengths:
        print("No pool-length records found. This FIT file may be an open-water swim or omit length messages.")
        return
    print("Pool lengths:", len(lengths), "| total distance:", round(sum(x["distance_m"] for x in lengths)), "m")
    for x in lengths:
        print("#{length}: {distance_m:g}m, {duration_s:.1f}s, {pace_s_per_100m:.1f}s/100m, strokes={strokes}, SWOLF≈{swolf_estimate}".format(**x))
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(lengths[0]))
            writer.writeheader()
            writer.writerows(lengths)
        print("Wrote", args.csv)


if __name__ == "__main__":
    main()
