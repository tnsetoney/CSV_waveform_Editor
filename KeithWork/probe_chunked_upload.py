import csv
import pyvisa
import time
from pathlib import Path

waveforms_dir = Path(__file__).parent / 'waveforms'
csv_path = waveforms_dir / 'base.csv'

values = []
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        values.append(float(row['CAN_H_V']))

payload = bytearray()
for v in values:
    scaled = int(max(0.0, min(5.0, v)) / 5.0 * 4095)
    payload.extend(scaled.to_bytes(2, 'little'))

byte_count = len(payload)
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
print('payload bytes', byte_count)
print('first 20 bytes', list(payload[:20]))

rm = pyvisa.ResourceManager()
inst = rm.open_resource('USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR', write_termination='\n', read_termination='\n', timeout=30000)
print('*IDN? ->', inst.query('*IDN?'))
inst.write('*CLS')
print('CLS err', inst.query('SYST:ERR?'))
inst.write('SOURCE1:FUNC ARB')
print('FUNC err', inst.query('SYST:ERR?'))
print('FUNC?', inst.query('SOURCE1:FUNC?'))
print('send header')
inst.write_raw(header.encode('ascii'))
time.sleep(0.1)
print('after header', inst.query('SYST:ERR?'))
print('send payload in chunks...')
chunk_size = 512
for i in range(0, len(payload), chunk_size):
    chunk = payload[i:i+chunk_size]
    print(' chunk', i, 'len', len(chunk))
    inst.write_raw(bytes(chunk))
    time.sleep(0.05)
print('done chunks, query error...')
print('SYST:ERR? ->', inst.query('SYST:ERR?'))
inst.close()
