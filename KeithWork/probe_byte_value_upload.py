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

for byte_value in [0, 1, 10, 13, 15, 16, 31, 32, 44, 127, 128, 255]:
    payload = bytes([byte_value]) * 40
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
    print('\n=== byte', byte_value, 'header', header, '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
    try:
        inst.write_raw(header.encode('ascii'))
        time.sleep(0.05)
        inst.write_raw(payload)
        time.sleep(0.2)
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e:
        print('error', type(e).__name__, e)
        try:
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e2:
            print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
