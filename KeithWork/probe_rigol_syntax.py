import pyvisa
import time

rm = pyvisa.ResourceManager()
resources = rm.list_resources()
print('resources', resources)
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
print('opening', resource)
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=5000)
print('*IDN? ->', inst.query('*IDN?'))

candidates = [
    'SOURCE1:FUNC ARB',
    'SOURCE1:FUNCTION ARB',
    'SOURCE1:FUNC USER',
    'SOURCE1:FUNCTION USER',
    'SOURCE1:FUNC?','SOURCE1:FUNCTION?','SOURCE1:FUNC ARB?','SOURCE1:FUNCTION ARB?',
    'SOURCE1:FUNC ARB',
    'SOUR1:FUNC ARB',
    'SOURCE1:FUNC?',
    'SOURCE1:FUNCTION?',
    'DATA:POINts VOLATILE,1958',
    'TRACE:DATA:POINts VOLATILE,1958',
    'SOURCE1:TRACE:DATA:POINts VOLATILE,1958',
    'DATA:POINts 1958',
    'SOURCE1:DATA:POINts 1958',
    'TRACE:DATA:POINts 1958',
    'SOURCE1:TRACE:DATA:DAC16 VOLATILE,END,#4',
    'DATA:DAC16 VOLATILE,END,#4',
    'TRACE:DATA:DAC16 VOLATILE,END,#4',
    'SOURCE1:DATA:DAC16 VOLATILE,END,#4',
    'SOURCE1:ARB:MODE PLAY',
    'FUNCTION:ARB ON',
    'FUNC:ARB ON',
    'SOURCE1:FUNCTION USER',
    'SOURCE1:FUNCTION ARB',
    'SOURCE1:FUNCTION:ARB?',
    'SOURCE1:FUNC:ARB?',
]

for c in candidates:
    print('---')
    try:
        if c.endswith('?'):
            print(c, '->', repr(inst.query(c)))
        else:
            print('write', c)
            inst.write(c)
            time.sleep(0.1)
            try:
                err = inst.query('SYST:ERR?')
            except Exception as e:
                err = f'ERR QUERY {type(e).__name__} {e}'
            print('SYST:ERR? ->', repr(err))
    except Exception as e:
        print('ERR', c, type(e).__name__, e)
        try:
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e2:
            print('SYST:ERR? ERR', type(e2).__name__, e2)

inst.close()
