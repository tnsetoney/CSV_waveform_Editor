import pyvisa
import time

rm = pyvisa.ResourceManager()
resource = 'USB0::0x1AB1::0x0646::DG8Q273701992::0::INSTR'
print('opening', resource)
inst = rm.open_resource(resource, write_termination='\n', read_termination='\n', timeout=10000)
print('*IDN? ->', inst.query('*IDN?'))

# Set channel 1 to ARB and probe error state
for cmd in ['SOURCE1:FUNC ARB', 'SOURCE1:FUNCTION ARB']:
    print('write', cmd)
    inst.write(cmd)
    time.sleep(0.1)
    print('SYST:ERR? ->', inst.query('SYST:ERR?'))
    print('SOURCE1:FUNC? ->', inst.query('SOURCE1:FUNC?'))

# Minimal binary DAC16 upload via TRACE
binary_data = bytes([0x00, 0x00, 0x40, 0x00])
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(len(binary_data)))}{len(binary_data)}'
print('write header', header)
inst.write_raw(header.encode('ascii') + binary_data)
try:
    time.sleep(0.1)
    err = inst.query('SYST:ERR?')
    print('SYST:ERR? after upload ->', err)
except Exception as e:
    print('upload query error', type(e).__name__, e)

inst.close()
