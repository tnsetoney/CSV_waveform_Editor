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
    ('binary 0000', b'\x00\x00\x40\x00'),
    ('ascii digits 0,0,16383,0', b'0,0,16383,0'),
    ('ascii hex 0x0000,0x4000', b'0x0000,0x4000'),
    ('ascii hex no prefix 0000,4000', b'0000,4000'),
    ('ascii space delim 0 0 16383 0', b'0 0 16383 0'),
    ('ascii bytes 32 space 44 comma 32', b'32 44 32 32'),
]

for name, payload in cases:
    length = len(payload)
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(length))}{length}'
    print('\n===', name, '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC', inst.query('SOURCE1:FUNC?'))
    try:
        inst.write_raw(header.encode('ascii'))
        time.sleep(0.05)
        inst.write_raw(payload)
        time.sleep(0.2)
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e:
        print('exception', type(e).__name__, e)
        try:
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e2:
            print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
