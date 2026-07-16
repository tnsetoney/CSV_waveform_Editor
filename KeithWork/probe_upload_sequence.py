import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
for cmd in ['*CLS', 'SYST:ERR?', 'SOURCE1:FUNC ARB', 'SYST:ERR?', 'SOURCE1:FUNC?']:
    if cmd.endswith('?'):
        print(cmd, '->', repr(inst.query(cmd)))
    else:
        print('write', cmd)
        inst.write(cmd)
        time.sleep(0.1)
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))

binary_data = bytes([0x00, 0x00, 0x40, 0x00])
byte_count = len(binary_data)
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
print('header', header)

print('\n=== send header only via write ===')
try:
    inst.write(header)
    time.sleep(0.1)
    print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
except Exception as e:
    print('error', e)
    try:
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e2:
        print('SYST:ERR? err', e2)

print('\n=== send header+binary via write_raw ===')
try:
    inst.write_raw(header.encode('ascii') + binary_data)
    time.sleep(0.1)
    print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
except Exception as e:
    print('error', e)
    try:
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e2:
        print('SYST:ERR? err', e2)

print('\n=== send header via write_raw and data separately ===')
try:
    inst.write_raw(header.encode('ascii'))
    time.sleep(0.1)
    print('after header SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    inst.write_raw(binary_data)
    time.sleep(0.1)
    print('after data SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
except Exception as e:
    print('error', e)
    try:
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e2:
        print('SYST:ERR? err', e2)

inst.close()
