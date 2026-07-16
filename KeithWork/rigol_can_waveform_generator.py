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
        self.waveform_scenarios = [
            "base",
            "timing_glitch",
            "slow_edges",
            "ringing",
            "dropped_bits",
            "voltage_spikes",
            "noise_overlay"
        ]

    def list_resources(self):
        """Return VISA resources visible to the system."""
        if not PYVISA_AVAILABLE:
            return []
        if self._resource_manager is None:
            self._resource_manager = pyvisa.ResourceManager()
        return list(self._resource_manager.list_resources())

    def connect_resource(self, resource):
        """Connect to a specific VISA resource string."""
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
            timeout=10000,
        )
        self.rigol_resource = resource
        return self.rigol.query("*IDN?")
        
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

        if 'can_h_v' in header_lower and 'can_l_v' in header_lower:
            h_idx = header_lower.index('can_h_v')
            l_idx = header_lower.index('can_l_v')
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
    
    def query_system_error(self):
        """Query the Rigol system error queue for diagnostics."""
        try:
            return self.rigol.query("SYST:ERR?")
        except Exception:
            return "<failed to query SYST:ERR?>"

    def clear_error_queue(self, max_drains=10):
        """Drain any pending errors from the Rigol error queue."""
        for _ in range(max_drains):
            error_text = self.query_system_error()
            if not error_text or error_text.strip().startswith("0"):
                break

    def send_scpi(self, command, retries=3, backoff=0.1, check_error=True):
        """Send a SCPI command, retrying on queue overflow and checking new errors."""
        last_error = None
        for attempt in range(retries):
            try:
                if isinstance(command, (bytes, bytearray)):
                    self.rigol.write_raw(command)
                else:
                    self.rigol.write(command)
                time.sleep(0.02)

                if check_error:
                    error_text = self.query_system_error()
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

        # DG822 does not support DG5000-style ARB sample-rate commands.
        if sample_rate is not None:
            for command in [
                f"SOURCE{channel}:ARB:SRAT {sample_rate}",
                f"SOURCE{channel}:ARB:SRATE {sample_rate}",
            ]:
                try:
                    self.send_scpi(command)
                    break
                except RuntimeError:
                    continue
    
    def set_waveform_point_count(self, channel, length):
        """Set the number of arbitrary waveform points before upload."""
        candidates = [
            f"DATA:POINts VOLATILE,{length}",
            f"SOURCE{channel}:DATA:POINts VOLATILE,{length}",
            f"DATA:POINts {length}",
            f"SOURCE{channel}:DATA:POINts {length}",
        ]
        for command in candidates:
            try:
                self.send_scpi(command)
                return True
            except RuntimeError:
                continue
        print(f"⚠️ Warning: point count command unsupported by this Rigol model. Continuing without explicit point count.")
        return False
    
    def _send_trace_data_block(self, channel, block_type, payload_bytes):
        """Send a single TRACE:DATA:DAC16 block with the given block type and payload."""
        header = f":SOURCE{channel}:TRACE:DATA:DAC16 VOLATILE,{block_type},#{len(str(len(payload_bytes)))}{len(payload_bytes)}"
        self.rigol.write_raw(header.encode('ascii') + payload_bytes)
        time.sleep(0.05)

    def send_waveform_binary(self, channel, waveform):
        """Send waveform data using a binary block to avoid command length limits."""
        binary_data = bytearray()
        for value in waveform:
            binary_data.extend(int(value).to_bytes(2, byteorder='little'))
        byte_count = len(binary_data)

        self.clear_error_queue()
        try:
            # Send the data as one or more TRACE:DATA:DAC16 blocks.
            max_chunk = 65536
            if byte_count <= max_chunk:
                self._send_trace_data_block(channel, "END", bytes(binary_data))
            else:
                offset = 0
                while offset + max_chunk < byte_count:
                    self._send_trace_data_block(channel, "CON", bytes(binary_data[offset:offset + max_chunk]))
                    offset += max_chunk
                self._send_trace_data_block(channel, "END", bytes(binary_data[offset:]))

            error_text = self.query_system_error()
            if error_text and not error_text.strip().startswith("0"):
                raise RuntimeError(f"Binary waveform upload returned error: {error_text}")
            return
        except Exception as e:
            raise RuntimeError(f"Binary waveform upload failed for channel {channel}: {e}")
    
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

    def transfer_arrays_to_rigol(self, can_h_data, can_l_data, sample_rate=1000000, amplitude=2.0, offset=2.5):
        """Transfer numeric sample arrays to Rigol CH1/CH2."""
        
        try:
            print("\n📤 Preparing to transfer custom waveform data to Rigol...")
            
            # Prepare waveforms
            h_waveform = self.prepare_rigol_waveform(can_h_data, "CAN_H")
            l_waveform = self.prepare_rigol_waveform(can_l_data, "CAN_L")
            
            # Check waveform length (Rigol DG822 Pro supports up to 65536 samples)
            max_samples = 65536
            if len(h_waveform) > max_samples:
                print(f"⚠️ Waveform too long ({len(h_waveform)} > {max_samples}). Truncating...")
                h_waveform = h_waveform[:max_samples]
                l_waveform = l_waveform[:max_samples]
            
            print(f"  - CAN_H waveform: {len(h_waveform)} samples")
            print(f"  - CAN_L waveform: {len(l_waveform)} samples")
            
            # Reset signal generator
            self.send_scpi("*RST")
            self.clear_error_queue()
            time.sleep(0.5)
            
            # Configure CH1 (CAN_H)
            print("  - Configuring CH1 (CAN_H)...")
            self.configure_arb_channel(1, sample_rate=sample_rate)
            self.set_waveform_point_count(1, len(h_waveform))
            try:
                self.send_waveform_binary(1, h_waveform)
            except Exception as e:
                print(f"⚠️ Binary waveform upload failed for CH1: {e}")
                return False
            
            # Configure CH2 (CAN_L)
            print("  - Configuring CH2 (CAN_L)...")
            self.configure_arb_channel(2, sample_rate=sample_rate)
            self.set_waveform_point_count(2, len(l_waveform))
            try:
                self.send_waveform_binary(2, l_waveform)
            except Exception as e:
                print(f"⚠️ Binary waveform upload failed for CH2: {e}")
                return False
            
            # Set output voltage levels (CAN signals typically 0-5V or 0-3.3V)
            print("  - Setting output voltage levels...")
            self.send_scpi(f"SOURCE1:VOLT {float(amplitude)}")
            self.send_scpi(f"SOURCE1:VOLT:OFFSET {float(offset)}")
            self.send_scpi(f"SOURCE2:VOLT {float(amplitude)}")
            self.send_scpi(f"SOURCE2:VOLT:OFFSET {float(offset)}")
            time.sleep(0.1)
            
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
                            resp = self.rigol.query(q.format(ch=ch))
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
                        resp = self.rigol.query(q.format(ch=ch))
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
            self.rigol.write("OUTPUT1:STATE OFF")
            self.rigol.write("OUTPUT2:STATE OFF")
            print("✅ Output stopped on CH1 and CH2")
            return True
        except Exception as e:
            print(f"❌ Error stopping output: {e}")
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
