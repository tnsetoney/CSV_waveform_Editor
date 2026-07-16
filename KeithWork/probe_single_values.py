import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))

values = [0, 1, 15, 16, 31, 32, 40, 63, 64, 127, 128, 255, 256, 512, 1023, 1024, 2047, 2048, 4095, 4096, 8191, 11468, 16383]
for v in values:
    payload = v.to_bytes(2, 'little')
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
    print('\n=== value', v, 'bytes', list(payload), '===')
    inst.write('*CLS')
    inst.write('SOURCE1:FUNC ARB')
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
