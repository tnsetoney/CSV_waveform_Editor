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

payloads = {
    'safe': bytes([0x00, 0x00, 0x40, 0x00]),
    'bad1': bytes([0xCC, 0x2C, 0xFF, 0x1F]),
    'bad2': bytes([0xFF, 0x1F, 0xCC, 0x2C]),
}
commands = [
    'TRACE:DATA:DAC16 VOLATILE,END,#{len}',
    'TRACE:DATA:BYTE VOLATILE,END,#{len}',
    'TRACE:DATA:INT VOLATILE,END,#{len}',
    'TRACE:DATA:WORD VOLATILE,END,#{len}',
    'TRACE:DATA:UWORD VOLATILE,END,#{len}',
    'TRACE:DATA:DAC VOLATILE,END,#{len}',
    'SOURCE1:TRACE:DATA:DAC16 VOLATILE,END,#{len}',
    'SOURCE1:TRACE:DATA:BYTE VOLATILE,END,#{len}',
    'SOURCE1:TRACE:DATA:INT VOLATILE,END,#{len}',
]

for name, payload in payloads.items():
    print('\n=== payload', name, '===')
    for cmd_template in commands:
        cmd = cmd_template.format(len=len(payload))
        print('cmd', cmd)
        inst.write('*CLS')
        inst.write('SOURCE1:FUNC ARB')
        try:
            inst.write_raw(cmd.encode('ascii'))
            time.sleep(0.05)
            inst.write_raw(payload)
            time.sleep(0.2)
            print('.. err', repr(inst.query('SYST:ERR?')))
        except Exception as e:
            print('.. exception', type(e).__name__, e)
            try:
                print('.. err', repr(inst.query('SYST:ERR?')))
            except Exception as e2:
                print('.. err exception', type(e2).__name__, e2)

inst.close()
