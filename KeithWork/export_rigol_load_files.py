#!/usr/bin/env python3
"""Export per-channel Rigol load files from the generated CAN waveform CSVs."""

import argparse
import csv
import json
from pathlib import Path


DEFAULT_SAMPLE_RATE = 4_000_000
DEFAULT_OFFSET_VOLTS = 2.5
DEFAULT_AMPLITUDE_VOLTS = 1.0


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def load_dual_channel_waveform(csv_path):
    can_h = []
    can_l = []

    with csv_path.open("r", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            can_h.append(float(row["CAN_H_V"]))
            can_l.append(float(row["CAN_L_V"]))

    return can_h, can_l


def voltage_to_normalized(voltage, offset_volts, amplitude_volts):
    normalized = (voltage - offset_volts) / amplitude_volts
    return clamp(normalized, -1.0, 1.0)


def write_single_column_csv(csv_path, header, values, precision=6):
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([header])
        for value in values:
            writer.writerow([f"{value:.{precision}f}"])


def build_channel_metadata(channel_name, source_values, normalized_values, output_file_name):
    return {
        "channel": channel_name,
        "file": output_file_name,
        "samples": len(source_values),
        "voltage_min": min(source_values),
        "voltage_max": max(source_values),
        "recommended_import": {
            "sample_rate_hz": DEFAULT_SAMPLE_RATE,
            "waveform_amplitude_v": DEFAULT_AMPLITUDE_VOLTS,
            "waveform_offset_v": DEFAULT_OFFSET_VOLTS,
            "data_format": "normalized_single_column_csv"
        },
        "normalized_min": min(normalized_values),
        "normalized_max": max(normalized_values)
    }


def export_scenario(scenario_name, waveforms_dir, output_dir):
    source_csv = waveforms_dir / f"{scenario_name}.csv"
    if not source_csv.exists():
        raise FileNotFoundError(f"Waveform source not found: {source_csv}")

    can_h_volts, can_l_volts = load_dual_channel_waveform(source_csv)
    if not can_h_volts:
        raise ValueError(f"No samples found in {source_csv}")

    output_dir.mkdir(parents=True, exist_ok=True)

    can_h_normalized = [
        voltage_to_normalized(value, DEFAULT_OFFSET_VOLTS, DEFAULT_AMPLITUDE_VOLTS)
        for value in can_h_volts
    ]
    can_l_normalized = [
        voltage_to_normalized(value, DEFAULT_OFFSET_VOLTS, DEFAULT_AMPLITUDE_VOLTS)
        for value in can_l_volts
    ]

    ch1_csv = output_dir / f"{scenario_name}_CH1_CAN_H_normalized.csv"
    ch2_csv = output_dir / f"{scenario_name}_CH2_CAN_L_normalized.csv"
    write_single_column_csv(ch1_csv, "Amplitude", can_h_normalized)
    write_single_column_csv(ch2_csv, "Amplitude", can_l_normalized)

    metadata = {
        "scenario": scenario_name,
        "source_waveform": source_csv.name,
        "sample_rate_hz": DEFAULT_SAMPLE_RATE,
        "recommended_generator_setup": {
            "channel_1_file": ch1_csv.name,
            "channel_2_file": ch2_csv.name,
            "amplitude_v": DEFAULT_AMPLITUDE_VOLTS,
            "offset_v": DEFAULT_OFFSET_VOLTS,
            "loop": True
        },
        "channels": [
            build_channel_metadata("CH1_CAN_H", can_h_volts, can_h_normalized, ch1_csv.name),
            build_channel_metadata("CH2_CAN_L", can_l_volts, can_l_normalized, ch2_csv.name)
        ]
    }

    metadata_path = output_dir / f"{scenario_name}_rigol_load_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "scenario": scenario_name,
        "source": source_csv,
        "channel_1": ch1_csv,
        "channel_2": ch2_csv,
        "metadata": metadata_path,
        "samples": len(can_h_volts)
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Export per-channel Rigol load files from generated waveform CSVs."
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        default="noise_overlay",
        help="Waveform scenario name to export (default: noise_overlay)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    root_dir = Path(__file__).parent
    waveforms_dir = root_dir / "waveforms"
    output_dir = waveforms_dir / "rigol_load"

    result = export_scenario(args.scenario, waveforms_dir, output_dir)
    print(f"Exported {result['scenario']} with {result['samples']} samples")
    print(f"CH1 file: {result['channel_1']}")
    print(f"CH2 file: {result['channel_2']}")
    print(f"Metadata: {result['metadata']}")


if __name__ == "__main__":
    main()