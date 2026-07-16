from rigol_can_waveform_generator import RigolWaveformManager
import traceback

m = RigolWaveformManager()
print('Detecting...')
try:
    found = m.detect_rigol()
    print('detect->', found)
except Exception as e:
    print('detect exception', e)
    traceback.print_exc()
    found = False

if not found:
    print('No Rigol detected; aborting')
else:
    try:
        print('*IDN? ->', m.rigol.query('*IDN?'))
    except Exception as e:
        print('IDN query failed:', e)
    try:
        ok = m.transfer_to_rigol('base')
        print('transfer_to_rigol ->', ok)
    except Exception as e:
        print('transfer_to_rigol exception:', e)
        traceback.print_exc()
    try:
        print('OUTPUT1:STAT? ->', repr(m.rigol.query('OUTPUT1:STAT?')))
    except Exception as e:
        print('OUTPUT1 query failed:', e)
    try:
        print('OUTPUT2:STAT? ->', repr(m.rigol.query('OUTPUT2:STAT?')))
    except Exception as e:
        print('OUTPUT2 query failed:', e)
    try:
        print('SYST:ERR? ->', m.rigol.query('SYST:ERR?'))
    except Exception as e:
        print('SYST:ERR? failed:', e)
    try:
        m.rigol.close()
    except Exception:
        pass
