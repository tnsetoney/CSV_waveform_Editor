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

binary_data = bytes([0x00, 0x00, 0x40, 0x00])
byte_count = len(binary_data)
header = f'TRACE:DATA:DAC16 VOLATILE,END,#{len(str(byte_count))}{byte_count}'
print('header', header)

variants = [
    ('header+data single write', header.encode('ascii') + binary_data),
    ('header+LF then data', header.encode('ascii') + b'\n' + binary_data),
    ('header+CRLF then data', header.encode('ascii') + b'\r\n' + binary_data),
    ('header raw then data raw', None),
    ('header raw with LF then data raw', None),
]

for name, payload in variants:
    print('\n===', name, '===')
    inst.write('*CLS')
    print('CLS', inst.query('SYST:ERR?'))
    inst.write('SOURCE1:FUNC ARB')
    print('FUNC', inst.query('SOURCE1:FUNC?'))

    if payload is not None:
        try:
            inst.write_raw(payload)
            time.sleep(0.2)
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e:
            print('error', type(e).__name__, e)
            try:
                print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
            except Exception as e2:
                print('SYST:ERR? err', type(e2).__name__, e2)
    else:
        try:
            if name == 'header raw then data raw':
                inst.write_raw(header.encode('ascii'))
                time.sleep(0.05)
                inst.write_raw(binary_data)
            elif name == 'header raw with LF then data raw':
                inst.write_raw(header.encode('ascii') + b'\n')
                time.sleep(0.05)
                inst.write_raw(binary_data)
            time.sleep(0.2)
            print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
        except Exception as e:
            print('error', type(e).__name__, e)
            try:
                print('SYST:ERR? ->', repr(inst.query('SYST:ERR?')))
            except Exception as e2:
                print('SYST:ERR? err', type(e2).__name__, e2)

inst.close()
