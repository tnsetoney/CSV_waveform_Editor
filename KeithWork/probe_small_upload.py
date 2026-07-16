import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))
print('set func arb')
inst.write('SOURCE1:FUNC ARB')
print('err', inst.query('SYST:ERR?'))

wave = [0, 4096, 8192, 12288, 16383, 12288, 8192, 4096, 0, 2048]
# convert to 2-byte little endian
binary_data = bytearray()
for value in wave:
    binary_data.extend(int(value).to_bytes(2, byteorder='little'))
byte_count = len(binary_data)
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
print('header', header)
inst.write_raw(header.encode('ascii') + bytes(binary_data))
time.sleep(0.2)
print('err after upload', inst.query('SYST:ERR?'))
inst.close()
