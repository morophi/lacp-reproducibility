#!/usr/bin/env python3
"""Print CPU/GPU temperature readings for an LACP inference node."""

from __future__ import annotations

import glob
import os
from datetime import datetime
from pathlib import Path


def read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def read_temp_c(path: str) -> float | None:
    raw = read_text(path)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value / 1000.0 if value > 1000 else value


def hwmon_name(hwmon_dir: str) -> str:
    name = read_text(os.path.join(hwmon_dir, "name"))
    return name or Path(hwmon_dir).name


def label_for_input(temp_input: str) -> str:
    label_path = temp_input.replace("_input", "_label")
    label = read_text(label_path)
    if label:
        return label
    return Path(temp_input).stem.replace("_input", "")


def collect_gpu_temps() -> list[tuple[str, float, str]]:
    readings: list[tuple[str, float, str]] = []
    patterns = [
        "/sys/class/drm/card*/device/hwmon/hwmon*/temp*_input",
        "/sys/class/drm/renderD*/device/hwmon/hwmon*/temp*_input",
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for temp_input in sorted(glob.glob(pattern)):
            real = os.path.realpath(temp_input)
            if real in seen:
                continue
            seen.add(real)
            temp_c = read_temp_c(temp_input)
            if temp_c is None:
                continue
            hwmon_dir = str(Path(temp_input).parent)
            label = label_for_input(temp_input)
            readings.append((f"GPU/{hwmon_name(hwmon_dir)}/{label}", temp_c, temp_input))
    return readings


def collect_hwmon_temps() -> list[tuple[str, float, str]]:
    readings: list[tuple[str, float, str]] = []
    for temp_input in sorted(glob.glob("/sys/class/hwmon/hwmon*/temp*_input")):
        temp_c = read_temp_c(temp_input)
        if temp_c is None:
            continue
        hwmon_dir = str(Path(temp_input).parent)
        label = label_for_input(temp_input)
        readings.append((f"{hwmon_name(hwmon_dir)}/{label}", temp_c, temp_input))
    return readings


def main() -> int:
    host = os.uname().nodename
    print(f"LACP node temperature report")
    print(f"host: {host}")
    print(f"time: {datetime.now().isoformat(timespec='seconds')}")
    print()

    gpu_readings = collect_gpu_temps()
    if gpu_readings:
        print("[GPU]")
        for name, temp_c, source in gpu_readings:
            print(f"{name}: {temp_c:.1f} C  ({source})")
        print()
    else:
        print("[GPU]")
        print("no GPU temperature sensor found")
        print()

    hwmon_readings = collect_hwmon_temps()
    if hwmon_readings:
        print("[All hwmon sensors]")
        for name, temp_c, source in hwmon_readings:
            print(f"{name}: {temp_c:.1f} C  ({source})")
    else:
        print("[All hwmon sensors]")
        print("no hwmon temperature sensor found")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
