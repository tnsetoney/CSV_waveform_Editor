import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination=None, read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
inst.write('*CLS')
print('CLS', inst.query('SYST:ERR?'))
inst.write('SOURCE1:FUNC ARB')
print('FUNC', inst.query('SOURCE1:FUNC?'))

for prefix in ['TRACE', 'SOURCE1:TRACE', 'SOURCE1:DATA', 'DATA']:
    for payload in [b'\x00\x00\x40\x00', b'\x20\x20\x20\x20', b'\xCC\x2C\xFF\x1F']:
        header = f'{prefix}:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
        print('\n=== prefix', prefix, 'payload first bytes', list(payload[:4]), '===')
        try:
            inst.write_raw(header.encode('ascii'))
            time.sleep(0.05)
            inst.write_raw(payload)
            time.sleep(0.2)
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e:
            print('EXC', type(e).__name__, e)
            try:
                print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
            except Exception as e2:
                print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
