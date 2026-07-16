import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
inst.write('*CLS')
print('CLS', inst.query('SYST:ERR?'))
inst.write('SOURCE1:FUNC ARB')
print('FUNC', inst.query('SOURCE1:FUNC?'))

cases = [
    ('first safe then bad', [0, 11468]),
    ('first bad then safe', [11468, 0]),
    ('first safe then bad2', [0, 8191]),
    ('first bad2 then safe', [8191, 0]),
]

for name, values in cases:
    payload = bytearray()
    for v in values:
        payload.extend(int(v).to_bytes(2, 'little'))
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
    print('\n===', name, 'values', values, 'header', header, '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC', inst.query('SOURCE1:FUNC?'))
    try:
        inst.write(header)
        time.sleep(0.05)
        inst.write_raw(bytes(payload))
        time.sleep(0.2)
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e:
        print('error', type(e).__name__, e)
        try:
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e2:
            print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
