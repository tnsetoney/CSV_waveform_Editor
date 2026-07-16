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

binary_data = bytes([0x00, 0x00, 0x40, 0x00])
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(binary_data)))}{len(binary_data)}'
print('header', header)
try:
    inst.write_raw(header.encode('ascii') + binary_data)
    time.sleep(0.2)
    print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
except Exception as e:
    print('error', type(e).__name__, e)
    try:
        print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
    except Exception as e2:
        print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
