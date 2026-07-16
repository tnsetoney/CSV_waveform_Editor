import pyvisa
import time

rm = pyvisa.ResourceManager()
resources = rm.list_resources()
print('resources', resources)
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
print('opening', resource)
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=5000)
print('*IDN? ->', inst.query('*IDN?'))

cmds = [
    'SOURCE1:ARB:SRAT 1000000',
    'SOURCE1:ARB:SRATE 1000000',
    'SOURCE1:ARB:MODE PLAY',
    'SOURCE1:ARB:MODE?',
    'SOURCE1:FUNC?',
    'SOURCE1:FUNCTION?',
    'SOURCE1:FUNC USER',
    'SOURCE1:FUNCTION USER',
    'SOURCE1:FUNC ARB',
    'SOURCE1:FUNCTION ARB',
    'SOURCE1:ARB:SRAT?',
    'SOURCE1:ARB:SRATE?',
    'SOURCE1:DATA:POINts VOLATILE,1958',
    'SOURCE1:DATA:POINts VOLATILE,2000',
]

for c in cmds:
    print('---')
    try:
        if c.endswith('?'):
            print(c, '->', repr(inst.query(c)))
        else:
            print('write', c)
            inst.write(c)
            time.sleep(0.1)
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e:
        print('ERR', c, type(e).__name__, e)
        try:
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e2:
            print('SYST:ERR? ERR', type(e2).__name__, e2)

inst.close()
