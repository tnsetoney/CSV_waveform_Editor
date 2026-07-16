#!/usr/bin/env python3
"""Download CSV waveform data to DG822 volatile memory without enabling output."""

import argparse
import csv
from pathlib import Path
import time

import pyvisa


def parse_dual_csv(csv_path: Path):
    can_h = []
    can_l = []
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            can_h.append(float(row["CAN_H_V"]))
            can_l.append(float(row["CAN_L_V"]))
    if not can_h:
        raise ValueError("CSV has no samples")
    return can_h, can_l


def to_dac16(values):
    out = bytearray()
    for v in values:
        vv = max(0.0, min(5.0, float(v)))
        dac = int(vv / 5.0 * 16383)
        out.extend(dac.to_bytes(2, byteorder="little"))
    return bytes(out)


def qerr(inst):
    try:
        return inst.query("SYST:ERR?").strip()
    except Exception as exc:
        return f"<query failed: {exc}>"


def upload_one_channel(inst, ch: int, payload: bytes):
    print(f"\n[CH{ch}] configure ARB")
    inst.write(f"SOURCE{ch}:FUNC ARB")
    print("  err after FUNC:", qerr(inst))

    headers = [
        f"SOURCE{ch}:TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}",
        f"TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}",
        f"SOURCE{ch}:TRACE:DATA:DAC16 BIN,END,#{len(str(len(payload)))}{len(payload)}",
    ]

    for idx, header in enumerate(headers, start=1):
        print(f"  try header {idx}: {header[:70]}...")
        inst.write("*CLS")
        inst.write(f"SOURCE{ch}:FUNC ARB")
        try:
            inst.write_raw(header.encode("ascii") + payload)
            time.sleep(0.15)
            err = qerr(inst)
            print("    err:", err)
            if err.startswith("0"):
                try:
                    print("    *OPC?:", inst.query("*OPC?").strip())
                except Exception as exc:
                    print("    *OPC? failed:", exc)
                return True, header
        except Exception as exc:
            print("    send exception:", exc)
            print("    err:", qerr(inst))

    return False, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="sample_csv/dual_flat.csv")
    parser.add_argument("--resource", default="")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    can_h, can_l = parse_dual_csv(csv_path)
    print(f"Loaded {len(can_h)} samples from {csv_path}")

    payload_h = to_dac16(can_h)
    payload_l = to_dac16(can_l)

    rm = pyvisa.ResourceManager()
    resources = rm.list_resources()
    print("Resources:", resources)
    if not resources:
        raise RuntimeError("No VISA resource found")

    resource = args.resource or resources[0]
    print("Using:", resource)
    inst = rm.open_resource(resource, write_termination="\n", read_termination="\n", timeout=5000)

    try:
        try:
            print("*IDN?:", inst.query("*IDN?").strip())
        except Exception as exc:
            print("*IDN? timeout, continue test:", exc)
        inst.write("*CLS")
        print("Initial err:", qerr(inst))

        ok1, h1 = upload_one_channel(inst, 1, payload_h)
        ok2, h2 = upload_one_channel(inst, 2, payload_l)

        print("\n=== SUMMARY ===")
        print("CH1 download:", "OK" if ok1 else "FAILED", "| header:", h1)
        print("CH2 download:", "OK" if ok2 else "FAILED", "| header:", h2)
        print("Final err:", qerr(inst))
        print("Note: This script does NOT enable output.")
    finally:
        inst.close()


if __name__ == "__main__":
    main()
