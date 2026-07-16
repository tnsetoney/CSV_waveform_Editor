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

payload = bytes([0xCC, 0x2C, 0xFF, 0x1F])
length = len(payload)
headers = [
    f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE,END#{len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE END,#{len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE END#{len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE,END #{len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE,END,# {len(str(length))}{length}',
    f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(length))}{length}\n',
]

for hdr in headers:
    print('\n=== header:', hdr, '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC', inst.query('SOURCE1:FUNC?'))
    try:
        if hdr.endswith('\n'):
            inst.write_raw(hdr.encode('ascii'))
            time.sleep(0.05)
            inst.write_raw(payload)
        else:
            inst.write_raw(hdr.encode('ascii'))
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
