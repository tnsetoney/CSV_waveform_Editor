import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
print('setting SOURCE1 to ARB')
inst.write('SOURCE1:FUNC ARB')
print('SYST:ERR? ->', inst.query('SYST:ERR?'))
print('SOURCE1:FUNC? ->', inst.query('SOURCE1:FUNC?'))

binary_data = bytes([0x00, 0x00, 0x40, 0x00])
byte_count = len(binary_data)
variants = [
    f'SOURCE1:TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}',
    f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}',
    f'SOURCE1:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}',
    f'DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}',
    f'SOURCE1:TRACE:DATA:DAC16 @VOLATILE,END,#{len(str(byte_count))}{byte_count}',
    f'SOURCE1:TRACE:DATA:INT xVOLATILE,END,#{len(str(byte_count))}{byte_count}',
]

for cmd in variants:
    print('---')
    print('header', cmd)
    try:
        inst.write_raw(cmd.encode('ascii') + binary_data)
        time.sleep(0.2)
        err = inst.query('SYST:ERR?')
        print('SYST:ERR? ->', repr(err))
    except Exception as e:
        print('write_raw exception', type(e).__name__, e)
        try:
            err = inst.query('SYST:ERR?')
            print('SYST:ERR? ->', repr(err))
        except Exception as e2:
            print('SYST:ERR? exception', type(e2).__name__, e2)

inst.close()
