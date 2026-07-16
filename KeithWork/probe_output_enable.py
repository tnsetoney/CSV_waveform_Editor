import pyvisa
import time

rm = pyvisa.ResourceManager()
resources = rm.list_resources()
print('resources', resources)
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))

cmds = [
    'OUTP1:STAT ON',
    'OUTPUT1:STAT ON',
    'OUTPUT1:STATE ON',
    'OUTP1:STAT?',
    'OUTPUT1:STAT?',
    'OUTPUT1:STATE?',
    'OUTP2:STAT ON',
    'OUTPUT2:STAT ON',
    'OUTPUT2:STATE ON',
    'OUTP2:STAT?',
    'OUTPUT2:STAT?',
    'OUTPUT2:STATE?',
]

for c in cmds:
    print('---')
    try:
        if c.endswith('?'):
            print(c, '->', inst.query(c))
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
            err = inst.query('SYST:ERR?')
            print('SYST:ERR? ->', repr(err))
        except Exception as e2:
            print('SYST:ERR? ERR', type(e2).__name__, e2)

inst.close()
