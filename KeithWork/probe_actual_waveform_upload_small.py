import csv
import pyvisa
import time
from pathlib import Path

for n_samples in [10, 50, 100, 200, 500, 1000]:
    waveforms_dir = Path(__file__).parent / 'waveforms'
    csv_path = waveforms_dir / 'base.csv'

    values = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= n_samples:
                break
            values.append(float(row['CAN_H_V']))

    binary_data = bytearray()
    for v in values:
        scaled = int(max(0.0, min(5.0, v)) / 5.0 * 16383)
        binary_data.extend(scaled.to_bytes(2, 'little'))
    byte_count = len(binary_data)
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
    print('\n=== test', n_samples, 'samples,', byte_count, 'bytes ===')

    rm = pyvisa.ResourceManager()
    resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
    inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
    print('*IDN? ->', inst.query('*IDN?'))
    inst.write('*CLS')
    print('CLS err', inst.query('SYST:ERR?'))
    inst.write('SOURCE1:FUNC ARB')
    print('set func err', inst.query('SYST:ERR?'))
    print('func?', inst.query('SOURCE1:FUNC?'))
    print('send header')
    inst.write_raw(header.encode('ascii'))
    time.sleep(0.05)
    print('after header err', inst.query('SYST:ERR?'))
    print('send data')
    inst.write_raw(bytes(binary_data))
    time.sleep(0.2)
    print('after data err', inst.query('SYST:ERR?'))
    inst.close()
