import csv
from pathlib import Path

waveforms_dir = Path(__file__).parent / 'waveforms'
csv_path = waveforms_dir / 'base.csv'

values = []
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        values.append(float(row['CAN_H_V']))

scaled = [int(max(0.0, min(5.0, v)) / 5.0 * 16383) for v in values]
print('samples', len(scaled))
print('min', min(scaled), 'max', max(scaled))
for i, v in enumerate(scaled[:20]):
    b = v.to_bytes(2, 'little')
    print(i, v, list(b))

byte_arr = bytearray()
for v in scaled:
    byte_arr.extend(v.to_bytes(2, 'little'))

print('total bytes', len(byte_arr))
print('LF count', byte_arr.count(0x0a), 'CR count', byte_arr.count(0x0d))
print('first LF indices', [i for i,b in enumerate(byte_arr) if b in (0x0a,0x0d)][:20])
print('distinct bytes > 16 and < 32', sorted({b for b in byte_arr if 16 < b < 32}))
print('distinct bytes >= 128 and < 160', sorted({b for b in byte_arr if 128 <= b < 160}))
print('unique bytes sample', sorted(set(byte_arr))[:20], sorted(set(byte_arr))[-20:])
