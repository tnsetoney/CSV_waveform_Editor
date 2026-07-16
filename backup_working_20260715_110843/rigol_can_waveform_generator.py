#!/usr/bin/env python3
"""
Rigol CAN Waveform Generator and USB Transfer Tool
Generates and transfers CAN-H/CAN-L waveforms to Rigol DG822 Pro signal generator.
"""

import os
import json
import csv
import sys
import time
import threading
from pathlib import Path

# Force UTF-8 output in Windows consoles to avoid emoji encoding failures.
if sys.platform.startswith('win'):
    try:
        import io
        if sys.stdout.encoding is None or sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import pyvisa
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False
    print("Warning: pyvisa not installed. USB transfer disabled.")
    print("Install with: python -m pip install pyvisa")


class RigolWaveformManager:
    """Manages waveform generation and transfer to Rigol signal generator."""
    
    def __init__(self):
        self.waveforms_dir = Path(__file__).parent / "waveforms"
        self.rigol = None
        self.rigol_resource = None
        self._resource_manager = None
        self._operation_lock = threading.Lock()
        self.io_logger = None
        self.waveform_scenarios = [
            "base",
            "timing_glitch",
            "slow_edges",
            "ringing",
            "dropped_bits",
            "voltage_spikes",
            "noise_overlay"
        ]

    def set_io_logger(self, callback):
        """Set callback used to emit SCPI I/O logs."""
        self.io_logger = callback

    def _log_io(self, level, message):
        if self.io_logger is None:
            return
        try:
            self.io_logger(f"[{level}] {message}")
        except Exception:
            pass

    def _write(self, command):
        self._log_io("TX", command)
        with self._operation_lock:
            self.rigol.write(command)

    def _write_raw(self, payload):
        preview = payload[:48]
        hex_preview = preview.hex()
        if len(payload) > 48:
            hex_preview += "..."
        self._log_io("TX-RAW", f"len={len(payload)} bytes hex={hex_preview}")
        with self._operation_lock:
            self.rigol.write_raw(payload)

    def _query(self, command):
        self._log_io("TX?", command)
        with self._operation_lock:
            response = self.rigol.query(command)
        self._log_io("RX", response.strip())
        return response

    def list_resources(self):
        """Return VISA resources visible to the system."""
        if not PYVISA_AVAILABLE:
            return []
        if self._resource_manager is None:
            self._resource_manager = pyvisa.ResourceManager()
        return list(self._resource_manager.list_resources())

    def connect_resource(self, resource, timeout_ms=5000, verify_idn=True):
        """Connect to a specific VISA resource string.

        When verify_idn is True, query *IDN? for validation. If that query times out,
        keep the session open and return a status message so callers can proceed.
        """
        if not PYVISA_AVAILABLE:
            raise RuntimeError("PyVISA not available")
        if self._resource_manager is None:
            self._resource_manager = pyvisa.ResourceManager()

        if self.rigol:
            try:
                self.rigol.close()
            except Exception:
                pass

        self.rigol = self._resource_manager.open_resource(
            resource,
            write_termination='\n',
            read_termination='\n',
            timeout=int(timeout_ms),
        )
        self.rigol_resource = resource
        self._log_io("INFO", f"Opened resource: {resource}")

        if not verify_idn:
            return "CONNECTED (IDN skipped)"

        try:
            return self._query("*IDN?").strip()
        except Exception as e:
            # Keep the resource open; some paths still work for writes/uploads.
            self._log_io("ERR", f"*IDN? failed: {e}")
            return f"CONNECTED (IDN timeout: {e})"
        
    def detect_rigol(self):
        """Detect and connect to Rigol device via USB."""
        if not PYVISA_AVAILABLE:
            print("❌ PyVISA not available. Cannot detect Rigol device.")
            return False
            
        try:
            resources = self.list_resources()
            
            if not resources:
                print("❌ No USB instruments detected.")
                return False
            
            print(f"\n📊 Found {len(resources)} USB instrument(s):")
            for i, resource in enumerate(resources, 1):
                print(f"  {i}. {resource}")
            
            # Try to connect to first Rigol device
            for resource in resources:
                if "RIGOL" in resource.upper() or "DG8" in resource:
                    try:
                        idn = self.connect_resource(resource)
                        print(f"✅ Connected: {idn}")
                        return True
                    except Exception as e:
                        print(f"⚠️ Failed to connect to {resource}: {e}")
                        continue
            
            # If no Rigol found explicitly, try the first device
            if not self.rigol:
                try:
                    idn = self.connect_resource(resources[0])
                    print(f"✅ Connected to: {idn}")
                    return True
                except Exception as e:
                    print(f"❌ Failed to connect: {e}")
                    return False
                    
        except Exception as e:
            print(f"❌ Error detecting Rigol: {e}")
            return False
    
    def load_waveform_csv(self, scenario_name):
        """Load waveform data from CSV file."""
        csv_path = self.waveforms_dir / f"{scenario_name}.csv"
        
        if not csv_path.exists():
            print(f"❌ Waveform file not found: {csv_path}")
            return None, None
        
        try:
            can_h_data = []
            can_l_data = []
            
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    can_h_data.append(float(row['CAN_H_V']))
                    can_l_data.append(float(row['CAN_L_V']))
            
            print(f"✅ Loaded {len(can_h_data)} samples from {scenario_name}.csv")
            return can_h_data, can_l_data
            
        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return None, None

    def load_waveform_csv_path(self, csv_path):
        """Load waveform data from an explicit CSV path."""
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV not found: {path}")

        can_h_data = []
        can_l_data = []
        with open(path, 'r', newline='') as f:
            reader = csv.reader(f)
            rows = list(reader)

        if not rows:
            raise ValueError("CSV is empty")

        header = [h.strip() for h in rows[0]]
        header_lower = [h.lower() for h in header]

        dual_header_pairs = [
            ("can_h_v", "can_l_v"),
            ("ch1_voltage", "ch2_voltage"),
            ("ch1_v", "ch2_v"),
            ("voltage_ch1", "voltage_ch2"),
        ]

        selected_pair = None
        for left, right in dual_header_pairs:
            if left in header_lower and right in header_lower:
                selected_pair = (left, right)
                break

        if selected_pair is not None:
            h_idx = header_lower.index(selected_pair[0])
            l_idx = header_lower.index(selected_pair[1])
            data_rows = rows[1:]
            for row in data_rows:
                if len(row) <= max(h_idx, l_idx):
                    continue
                can_h_data.append(float(row[h_idx]))
                can_l_data.append(float(row[l_idx]))
        else:
            # Accept a single numeric column CSV and mirror to both channels.
            data_rows = rows
            # If first row is not numeric, treat it as header.
            try:
                float(rows[0][0])
            except Exception:
                data_rows = rows[1:]
            for row in data_rows:
                if not row:
                    continue
                value = float(row[0])
                can_h_data.append(value)
                can_l_data.append(value)

        if not can_h_data or not can_l_data:
            raise ValueError("No numeric samples parsed from CSV")

        return can_h_data, can_l_data
    
    def voltage_to_rigol_dac(self, voltage, v_min=0.0, v_max=5.0):
        """
        Convert voltage to Rigol DAC value (0-255 or 0-4095 depending on model).
        Rigol DG822 uses 12-bit DAC (0-4095).
        """
        # Clamp voltage to valid range
        voltage = max(v_min, min(v_max, voltage))
        
        # Convert to 0-16383 range for DG800-series binary DAC16 uploads
        dac_value = int((voltage - v_min) / (v_max - v_min) * 16383)
        return dac_value
    
    def prepare_rigol_waveform(self, voltage_data, name="ARB"):
        """
        Prepare waveform data for Rigol arbitrary waveform format.
        Returns waveform as integer array compatible with Rigol.
        """
        # Convert voltages to DAC values
        dac_values = [self.voltage_to_rigol_dac(v, v_min=0, v_max=5.0)
                      for v in voltage_data]
        
        # Rigol DG822 expects 0-4095 for 12-bit waveforms
        return dac_values

    def prepare_voltage_waveform(self, voltage_data, v_min=0.0, v_max=5.0):
        """Clamp and format raw voltage waveform points for VOLTAGE transfer mode."""
        return [max(v_min, min(v_max, float(v))) for v in voltage_data]
    
    def query_system_error(self):
        """Query the Rigol system error queue for diagnostics."""
        try:
            return self._query("SYST:ERR?")
        except Exception as e:
            self._log_io("ERR", f"SYST:ERR? unreadable: {e}")
            return None

    def clear_error_queue(self, max_drains=10):
        """Drain any pending errors from the Rigol error queue."""
        for _ in range(max_drains):
            error_text = self.query_system_error()
            if error_text is None:
                break
            if not error_text or error_text.strip().startswith("0"):
                break

    def send_scpi(self, command, retries=3, backoff=0.1, check_error=False):
        """Send a SCPI command, retrying on queue overflow and checking new errors."""
        last_error = None
        for attempt in range(retries):
            try:
                if isinstance(command, (bytes, bytearray)):
                    self._write_raw(command)
                else:
                    self._write(command)
                time.sleep(0.02)

                if check_error:
                    error_text = self.query_system_error()
                    # If SYST:ERR? itself is unreadable, do not treat as command failure.
                    if error_text is None:
                        return
                    if error_text and not error_text.strip().startswith("0"):
                        last_error = error_text
                        if "Queue overflow" in error_text or "-350" in error_text:
                            time.sleep(backoff * (attempt + 1))
                            continue
                        raise RuntimeError(
                            f"SCPI command returned error: {command!r} | SYST:ERR? {error_text}"
                        )
                return
            except Exception as e:
                if isinstance(e, RuntimeError) and last_error is not None:
                    error_text = last_error
                else:
                    error_text = self.query_system_error()
                if error_text is None:
                    raise RuntimeError(f"SCPI command failed: {command!r}: {e} | SYST:ERR? unreadable")
                if error_text and ("Queue overflow" in error_text or "-350" in error_text):
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise RuntimeError(f"SCPI command failed: {command!r}: {e} | SYST:ERR? {error_text}")
        raise RuntimeError(
            f"SCPI command failed after retries: {command!r}: {last_error} | SYST:ERR? {error_text}"
        )
    
    def configure_arb_channel(self, channel, sample_rate=None):
        """Configure a channel for arbitrary waveform playback."""
        candidates = [
            f"SOURCE{channel}:FUNC ARB",
            f"SOURCE{channel}:FUNCTION ARB",
        ]
        last_error = None
        for command in candidates:
            try:
                self.send_scpi(command)
                last_error = None
                break
            except RuntimeError as e:
                last_error = e
        if last_error:
            raise RuntimeError(f"Unable to select ARB function for channel {channel}: {last_error}")
        # Skip ARB:SRAT style commands in download phase; they can trigger
        # front-panel remote command error on this DG822 firmware.
    
    def set_waveform_point_count(self, channel, length):
        """Set the number of arbitrary waveform points before upload."""
        # Skip explicit point-count commands; upload works without them and
        # unsupported variants can raise remote command error on device.
        print("⚠️ Skipping DATA:POINts command for DG822 compatibility.")
        return False
    
    def _send_trace_data_voltage_block(self, channel, block_flag, values):
        """Send one TRACE:DATA:DAC16 VOLTAGE block in readable ASCII mode."""
        value_text = ",".join(f"{v:.6f}" for v in values)
        command = f"SOURCE{channel}:TRACE:DATA:DAC16 VOLTAGE,{block_flag},{value_text}"
        self._write(command)
        time.sleep(0.03)

    def send_waveform_voltage(self, channel, waveform):
        """Send waveform in VOLTAGE mode using readable ASCII chunks."""
        self.clear_error_queue()
        try:
            chunk_points = 128
            total = len(waveform)
            original_timeout = None
            try:
                original_timeout = self.rigol.timeout
                # VOLTAGE ASCII mode is slower than binary mode.
                self.rigol.timeout = max(int(self.rigol.timeout or 0), 20000)
            except Exception:
                pass

            if total <= chunk_points:
                self._send_trace_data_voltage_block(channel, "END", waveform)
            else:
                index = 0
                first = True
                while index < total:
                    chunk = waveform[index:index + chunk_points]
                    index += len(chunk)
                    if index >= total:
                        flag = "END"
                    elif first:
                        flag = "HEAD"
                    else:
                        flag = "CONT"
                    self._send_trace_data_voltage_block(channel, flag, chunk)
                    first = False

            error_text = self.query_system_error()
            if error_text and not error_text.strip().startswith("0"):
                raise RuntimeError(f"VOLTAGE waveform transfer returned error: {error_text}")
            return
        except Exception as e:
            raise RuntimeError(f"VOLTAGE waveform transfer failed for channel {channel}: {e}")
        finally:
            if original_timeout is not None:
                try:
                    self.rigol.timeout = original_timeout
                except Exception:
                    pass
    
    def transfer_to_rigol(self, scenario_name, channel=1):
        """Send waveform to specified Rigol channel."""
        if not self.rigol:
            print("❌ Not connected to Rigol. Run detect_rigol() first.")
            return False
        
        can_h_data, can_l_data = self.load_waveform_csv(scenario_name)
        if can_h_data is None:
            return False

        return self.transfer_arrays_to_rigol(can_h_data, can_l_data)

    def transfer_csv_path_to_rigol(self, csv_path):
        """Load a CSV file path and transfer it to CH1/CH2."""
        if not self.rigol:
            raise RuntimeError("Not connected to Rigol")
        can_h_data, can_l_data = self.load_waveform_csv_path(csv_path)
        return self.transfer_arrays_to_rigol(can_h_data, can_l_data)

    def download_arrays_to_rigol(self, can_h_data, can_l_data, sample_rate=1000000):
        """Download waveform arrays to CH1/CH2 volatile memory without enabling outputs."""
        if not self.rigol:
            print("❌ Not connected to Rigol")
            return False

        try:
            print("\n📥 Preparing CSV waveform download (no output enable)...")

            h_waveform = self.prepare_voltage_waveform(can_h_data)
            l_waveform = self.prepare_voltage_waveform(can_l_data)

            max_samples = 32768
            if len(h_waveform) > max_samples:
                print(f"⚠️ Waveform too long ({len(h_waveform)} > {max_samples}). Truncating...")
                h_waveform = h_waveform[:max_samples]
                l_waveform = l_waveform[:max_samples]

            print(f"  - CAN_H waveform: {len(h_waveform)} samples")
            print(f"  - CAN_L waveform: {len(l_waveform)} samples")

            self.send_scpi("*CLS")
            self.clear_error_queue()
            time.sleep(0.2)

            # Configure both channels first, then send trace data blocks.
            # This avoids changing channel settings after one channel has
            # entered TRACE mode on firmwares that reject such updates.
            print("  - Configuring CH1/CH2 for ARB download...")
            self.configure_arb_channel(1, sample_rate=sample_rate)
            self.set_waveform_point_count(1, len(h_waveform))
            self.configure_arb_channel(2, sample_rate=sample_rate)
            self.set_waveform_point_count(2, len(l_waveform))

            print("  - Downloading CH1 data...")
            self.send_waveform_voltage(1, h_waveform)

            print("  - Downloading CH2 data...")
            self.send_waveform_voltage(2, l_waveform)

            if not self.verify_channel_upload(1):
                print("⚠️ Rigol reported a command error after CH1 download.")
                return False
            if not self.verify_channel_upload(2):
                print("⚠️ Rigol reported a command error after CH2 download.")
                return False

            # Skip *OPC? readback to avoid protocol-layer query violations seen
            # on this setup after binary transfers.
            print("  - *OPC? skipped for compatibility.")

            print("✅ CSV waveform download completed. Outputs are still OFF.")
            return True
        except Exception as e:
            print(f"❌ Download error: {e}")
            return False

    def activate_downloaded_waveform(self, sample_rate=1000000, amplitude=None, offset=None):
        """Switch channels to sequence-ARB playback for downloaded trace data."""
        if not self.rigol:
            raise RuntimeError("Not connected to Rigol")

        print("  - Activating downloaded waveform (sequence ARB mode)...")
        for ch in (1, 2):
            # Manual/UltraStation-like activation path.
            for cmd in [
                f"SOURCE{ch}:FUNCTION:SEQUENCE ON",
                f"SOURCE{ch}:FUNCTION:SEQUENCE:STATE ON",
                f"SOURCE{ch}:FUNCTION:SEQUENCE:TYPE ARB",
                f"SOURCE{ch}:FUNC:SEQ:ARB:SRAT {float(sample_rate)}",
                f"SOURCE{ch}:FUNCTION:SEQUENCE:ARB:SRATE {float(sample_rate)}",
            ]:
                try:
                    self.send_scpi(cmd)
                except Exception:
                    continue

            if amplitude is not None:
                for cmd in [
                    f"SOURCE{ch}:VOLT {float(amplitude)}",
                    f"SOUR{ch}:VOLT {float(amplitude)}",
                ]:
                    try:
                        self.send_scpi(cmd)
                        break
                    except Exception:
                        continue

            if offset is not None:
                for cmd in [
                    f"SOURCE{ch}:VOLT:OFFSET {float(offset)}",
                    f"SOUR{ch}:VOLT:OFFSET {float(offset)}",
                ]:
                    try:
                        self.send_scpi(cmd)
                        break
                    except Exception:
                        continue

        # Best-effort status queries for visibility in log.
        for ch in (1, 2):
            for q in [
                f"SOURCE{ch}:FUNCTION?",
                f"SOURCE{ch}:FUNC?",
                f"SOURCE{ch}:FUNCTION:SEQUENCE:STATE?",
            ]:
                try:
                    resp = self._query(q).strip()
                    print(f"    CH{ch} {q} -> {resp}")
                    break
                except Exception:
                    continue

            # Do not query burst status here; it can be flaky on this setup.

    def transfer_arrays_to_rigol(self, can_h_data, can_l_data, sample_rate=1000000, amplitude=2.0, offset=2.5):
        """Transfer numeric sample arrays to Rigol CH1/CH2."""
        
        try:
            # Configure output levels before entering trace/ARB download mode.
            print("  - Pre-configuring output voltage levels...")
            try:
                self.send_scpi(f"SOURCE1:VOLT {float(amplitude)}")
                self.send_scpi(f"SOURCE1:VOLT:OFFSET {float(offset)}")
                self.send_scpi(f"SOURCE2:VOLT {float(amplitude)}")
                self.send_scpi(f"SOURCE2:VOLT:OFFSET {float(offset)}")
                time.sleep(0.05)
            except Exception as e:
                print(f"⚠️ Voltage pre-configuration skipped: {e}")

            if not self.download_arrays_to_rigol(can_h_data, can_l_data, sample_rate=sample_rate):
                return False

            self.activate_downloaded_waveform(sample_rate=sample_rate, amplitude=amplitude, offset=offset)
            
            # Verify upload success before claiming success.
            if not self.verify_channel_upload(1):
                print("⚠️ Rigol reported a command error after CH1 upload.")
                return False
            if not self.verify_channel_upload(2):
                print("⚠️ Rigol reported a command error after CH2 upload.")
                return False

            # Enable outputs (use robust helper that tries multiple command variants)
            try:
                self.ensure_outputs_on()
            except Exception as e:
                print(f"⚠️ Failed to enable outputs: {e}")
            
            print("✅ Successfully transferred waveform data to Rigol!")
            print(f"   CH1 (CAN_H) and CH2 (CAN_L) are now outputting the waveform")
            return True
            
        except Exception as e:
            print(f"❌ Error transferring waveform: {e}")
            return False
    
    def display_menu(self):
        """Display interactive menu."""
        print("\n" + "="*60)
        print("🌊 RIGOL CAN WAVEFORM GENERATOR & TRANSFER")
        print("="*60)
        print("\n1. Detect Rigol Device")
        print("2. Transfer Waveform to Rigol (Live Output)")
        print("3. Stop Output")
        print("4. List Available Waveforms")
        print("5. Show Waveform Info")
        print("6. Exit")
        print("\n" + "="*60)
    
    def list_waveforms(self):
        """List all available waveform scenarios."""
        print("\n📋 Available Waveform Scenarios:")
        for i, scenario in enumerate(self.waveform_scenarios, 1):
            csv_file = self.waveforms_dir / f"{scenario}.csv"
            if csv_file.exists():
                # Count rows to get sample count
                with open(csv_file, 'r') as f:
                    count = sum(1 for line in f) - 1  # Subtract header
                print(f"  {i}. {scenario:20} ({count} samples)")
            else:
                print(f"  {i}. {scenario:20} ❌ NOT FOUND")
    
    def show_waveform_info(self, scenario_name):
        """Display information about a specific waveform."""
        csv_path = self.waveforms_dir / f"{scenario_name}.csv"
        
        if not csv_path.exists():
            print(f"❌ Waveform {scenario_name} not found")
            return
        
        try:
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                h_values = []
                l_values = []
                for row in reader:
                    h_values.append(float(row['CAN_H_V']))
                    l_values.append(float(row['CAN_L_V']))
            
            print(f"\n📊 Waveform Info: {scenario_name}")
            print(f"  Samples: {len(h_values)}")
            print(f"  CAN_H - Min: {min(h_values):.2f}V, Max: {max(h_values):.2f}V, Avg: {sum(h_values)/len(h_values):.2f}V")
            print(f"  CAN_L - Min: {min(l_values):.2f}V, Max: {max(l_values):.2f}V, Avg: {sum(l_values)/len(l_values):.2f}V")
            
        except Exception as e:
            print(f"❌ Error reading waveform info: {e}")

    def ensure_outputs_on(self, timeout=2.0):
        """Attempt several SCPI variants to enable outputs and verify state."""
        if not self.rigol:
            raise RuntimeError("Not connected to instrument")

        write_variants = [
            "OUTPUT{ch}:STATE ON",
            "OUTPUT{ch}:STAT ON",
            "OUTP{ch}:STAT ON",
            "OUTP{ch}:STAT ON",
        ]
        query_variants = [
            "OUTPUT{ch}:STAT?",
            "OUTP{ch}:STAT?",
            "OUTPUT{ch}:STATE?",
        ]

        def _is_on(resp):
            if resp is None:
                return False
            s = str(resp).strip().upper()
            return s in ("1", "ON", "TRUE")

        for ch in (1, 2):
            # Try writing each variant and then poll for state
            for w in write_variants:
                cmd = w.format(ch=ch)
                try:
                    self.send_scpi(cmd)
                except Exception:
                    continue
                # poll queries
                deadline = time.time() + timeout
                while time.time() < deadline:
                    for q in query_variants:
                        try:
                            resp = self._query(q.format(ch=ch))
                            if _is_on(resp):
                                break
                        except Exception:
                            continue
                    else:
                        time.sleep(0.1)
                        continue
                    break
                # final check
                ok = False
                for q in query_variants:
                    try:
                        resp = self._query(q.format(ch=ch))
                        if _is_on(resp):
                            ok = True
                            break
                    except Exception:
                        continue
                if not ok:
                    raise RuntimeError(f"Channel {ch} did not enable (checked variants)")
        return True
    
    def verify_channel_upload(self, channel):
        """Check the Rigol error queue after upload to confirm the waveform was accepted."""
        try:
            err = self.query_system_error()
            if err and not err.strip().startswith("0"):
                print(f"⚠️ Channel {channel} upload error: {err}")
                return False
            return True
        except Exception:
            return False

    def stop_output(self):
        """Stop output on both channels."""
        if not self.rigol:
            print("❌ Not connected to Rigol")
            return False
        
        try:
            self._write("OUTPUT1:STATE OFF")
            self._write("OUTPUT2:STATE OFF")
            print("✅ Output stopped on CH1 and CH2")
            return True
        except Exception as e:
            print(f"❌ Error stopping output: {e}")
            return False

    def set_channel_output(self, channel, enabled):
        """Set output state for a single channel."""
        if not self.rigol:
            print("❌ Not connected to Rigol")
            return False
        if channel not in (1, 2):
            raise ValueError("channel must be 1 or 2")

        state = "ON" if enabled else "OFF"
        commands = [
            f"OUTPUT{channel}:STATE {state}",
            f"OUTPUT{channel}:STAT {state}",
            f"OUTP{channel}:STAT {state}",
            f"OUTP{channel} {state}",
        ]

        for cmd in commands:
            try:
                self.send_scpi(cmd)
                print(f"✅ CH{channel} output {state}")
                return True
            except Exception:
                continue

        print(f"❌ Failed to set CH{channel} output {state}")
        return False
    
    def run_interactive(self):
        """Run interactive menu loop."""
        while True:
            self.display_menu()
            choice = input("Select option (1-6): ").strip()
            
            if choice == "1":
                self.detect_rigol()
            
            elif choice == "2":
                if not self.rigol:
                    print("❌ Must detect Rigol first (option 1)")
                    continue
                
                self.list_waveforms()
                scenario = input("\nEnter scenario name: ").strip()
                
                if scenario in self.waveform_scenarios:
                    self.transfer_to_rigol(scenario)
                else:
                    print(f"❌ Unknown scenario: {scenario}")
            
            elif choice == "3":
                self.stop_output()
            
            elif choice == "4":
                self.list_waveforms()
            
            elif choice == "5":
                self.list_waveforms()
                scenario = input("Enter scenario name: ").strip()
                self.show_waveform_info(scenario)
            
            elif choice == "6":
                print("👋 Exiting...")
                if self.rigol:
                    self.rigol.close()
                break
            
            else:
                print("❌ Invalid option")
            
            input("\nPress Enter to continue...")


def main():
    """Main entry point."""
    manager = RigolWaveformManager()
    
    # Check if waveforms directory exists
    if not manager.waveforms_dir.exists():
        print(f"❌ Waveforms directory not found: {manager.waveforms_dir}")
        print("Please generate waveforms first or check the directory path.")
        sys.exit(1)
    
    # Run interactive menu
    manager.run_interactive()


if __name__ == "__main__":
    main()
