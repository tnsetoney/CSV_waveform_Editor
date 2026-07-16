import pyvisa
import time

rm = pyvisa.ResourceManager()
resources = rm.list_resources()
print('resources', resources)
if not resources:
    raise SystemExit('No VISA resources found.')
resource = resources[0]
print('Using resource:', resource)
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=5000)
print('Opened instrument')

cmds = [
    '*CLS',
    '*RST',
    '*IDN?',
    'SYST:ERR?',
    'OUTPUT1:STAT?',
    'OUTPUT2:STAT?',
    'OUTP1:STAT?',
    'OUTP2:STAT?',
    'OUTPUT1:STAT ON',
    'OUTPUT2:STAT ON',
    'OUTP1:STAT ON',
    'OUTP2:STAT ON',
    'SOURCE1:FUNC?',
    'SOURCE2:FUNC?',
    'SOURCE1:FUNCTION?',
    'SOURCE2:FUNCTION?',
    'SOURCE1:FUNC ARB',
    'SOURCE1:FUNCTION ARB',
    'SOURCE1:FUNCTION USER',
]

def run_query(cmd):
    try:
        resp = inst.query(cmd)
        print(f'{cmd} -> {repr(resp)}')
    except Exception as e:
        print(f'{cmd} ERR {type(e).__name__}: {e}')


def run_write(cmd):
    try:
        inst.write(cmd)
        print(f'{cmd} OK')
        run_query('SYST:ERR?')
    except Exception as e:
        print(f'{cmd} ERR {type(e).__name__}: {e}')

# execute commands
for cmd in cmds:
    if cmd.endswith('?'):
        run_query(cmd)
    else:
        run_write(cmd)
    time.sleep(0.2)

inst.close()
print('Done')
