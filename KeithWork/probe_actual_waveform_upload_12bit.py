import csv
import pyvisa
import time
from pathlib import Path

waveforms_dir = Path(__file__).parent / 'waveforms'
csv_path = waveforms_dir / 'base.csv'

can_h_data = []
with open(csv_path, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        can_h_data.append(float(row['CAN_H_V']))

binary_data = bytearray()
for v in can_h_data:
    value = int(max(0.0, min(5.0, v)) / 5.0 * 4095)
    binary_data.extend(value.to_bytes(2, byteorder='little'))
byte_count = len(binary_data)
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
inst.write('*CLS')
print('SYST:ERR? ->', inst.query('SYST:ERR?'))
inst.write('SOURCE1:FUNC ARB')
print('SYST:ERR? ->', inst.query('SYST:ERR?'))
print('SOURCE1:FUNC? ->', inst.query('SOURCE1:FUNC?'))
print('header len', len(header), 'byte_count', byte_count)
print('first 20 bytes', list(binary_data[:20]))
print('send header')
inst.write_raw(header.encode('ascii'))
time.sleep(0.1)
print('after header err', inst.query('SYST:ERR?'))
print('send data')
inst.write_raw(bytes(binary_data))
time.sleep(0.5)
print('after data err', inst.query('SYST:ERR?'))
inst.close()
