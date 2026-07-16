import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
print('set SOURCE1 to ARB')
inst.write('SOURCE1:FUNC ARB')
print('SYST:ERR? ->', inst.query('SYST:ERR?'))

for n_samples in [2, 50, 100, 500, 1000, 1958]:
    binary_data = bytearray()
    for i in range(n_samples):
        value = 0 if i % 2 == 0 else 4096
        binary_data.extend(value.to_bytes(2, byteorder='little'))
    byte_count = len(binary_data)
    header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
    print('\n=== test', n_samples, 'samples,', byte_count, 'bytes ===')
    try:
        inst.write_raw(header.encode('ascii'))
        time.sleep(0.05)
        inst.write_raw(bytes(binary_data))
        time.sleep(0.2)
        err = inst.query('SYST:ERR?')
        print('SYST:ERR? ->', repr(err))
    except Exception as e:
        print('exception', type(e).__name__, e)
        try:
            err = inst.query('SYST:ERR?')
            print('SYST:ERR? ->', repr(err))
        except Exception as e2:
            print('SYST:ERR? exception', type(e2).__name__, e2)

inst.close()
