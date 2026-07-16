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
for name,payload in [
    ('safe first then bad', bytes([0x00,0x00,0xCC,0x2C])),
    ('space first then bad', bytes([0x20,0x20,0xCC,0x2C])),
    ('safe sequence only', bytes([0x00,0x00,0x40,0x00])),
    ('actual starts bad', bytes([0xCC,0x2C,0xFF,0x1F])),
]:
    hdr = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
    print('\n===', name, '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC', inst.query('SOURCE1:FUNC?'))
    inst.write_raw(hdr.encode('ascii'))
    time.sleep(0.05)
    inst.write_raw(payload)
    time.sleep(0.2)
    print('err', repr(inst.query('SYST:ERR?')))
inst.close()
