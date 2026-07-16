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

cmds = [
    'TRACE:DATA:BINARY VOLATILE,END,#{len}',
    'TRACE:DATA:BYTE VOLATILE,END,#{len}',
    'TRACE:DATA:WORD VOLATILE,END,#{len}',
    'TRACE:DATA:DWORD VOLATILE,END,#{len}',
    'TRACE:DATA:UINT VOLATILE,END,#{len}',
    'TRACE:DATA:INT VOLATILE,END,#{len}',
    'TRACE:DATA:UWORD VOLATILE,END,#{len}',
    'TRACE:DATA:LONG VOLATILE,END,#{len}',
    'TRACE:DATA:DAC VOLATILE,END,#{len}',
    'TRACE:DATA:DAC16 VOLATILE,END,#{len}',
]
payloads = {
    'bytes_0000': bytes([0x00, 0x00, 0x40, 0x00]),
    'bytes_20202020': bytes([0x20, 0x20, 0x20, 0x20]),
    'bytes_cc2cff1f': bytes([0xCC, 0x2C, 0xFF, 0x1F]),
}

for name, payload in payloads.items():
    print('\n===== payload', name, '======')
    for cmd in cmds:
        size = len(payload)
        header = cmd.format(len=size)
        print('\ncmd', header)
        inst.write('*CLS')
        inst.write('SOURCE1:FUNC ARB')
        try:
            inst.write_raw(header.encode('ascii'))
            time.sleep(0.05)
            inst.write_raw(payload)
            time.sleep(0.2)
            err = inst.query('SYST:ERR?')
            print('err', repr(err))
        except Exception as e:
            print('exception', type(e).__name__, e)
            try:
                err = inst.query('SYST:ERR?')
                print('err', repr(err))
            except Exception as e2:
                print('err_exception', type(e2).__name__, e2)
inst.close()
