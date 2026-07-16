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
for pattern in [ [8191,11468], [11468,8191,11468,8191,11468], [0,4096,8192,12288,16383] ]:
    binary_data = bytearray()
    for v in pattern:
        binary_data.extend(v.to_bytes(2, 'little'))
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(binary_data)))}{len(binary_data)}'
    print('\npattern', pattern)
    print('header', header)
    inst.write_raw(header.encode('ascii'))
    time.sleep(0.05)
    inst.write_raw(bytes(binary_data))
    time.sleep(0.2)
    print('err', inst.query('SYST:ERR?'))
inst.close()
