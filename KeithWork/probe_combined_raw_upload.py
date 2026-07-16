import pyvisa
import time

resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
rm = pyvisa.ResourceManager()
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)

try:
    print('*IDN? ->', inst.query('*IDN?'))
    inst.write('*CLS')
    print('CLS err ->', inst.query('SYST:ERR?'))
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC err ->', inst.query('SYST:ERR?'))
    print('FUNC? ->', inst.query('SOURCE1:FUNC?'))

    payload = b'\x00\x00\x40\x00'
    header = f':SOURCE1:TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(payload)))}{len(payload)}'
    print('header ->', header)
    inst.write_raw(header.encode('ascii') + payload)
    print('sent raw block')
    time.sleep(0.2)
    print('after err ->', inst.query('SYST:ERR?'))
except Exception as exc:
    print('EXCEPTION:', type(exc).__name__, exc)
    try:
        print('SYST:ERR? ->', inst.query('SYST:ERR?'))
    except Exception as exc2:
        print('SYST:ERR? EXC:', type(exc2).__name__, exc2)
finally:
    inst.close()
