#!/usr/bin/env python3
"""Simple GUI to load CSV waveform files and upload them to a Rigol DG822 Pro."""

import csv
import io
import threading
from contextlib import redirect_stdout
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from rigol_can_waveform_generator import PYVISA_AVAILABLE, RigolWaveformManager


class DG822CsvGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DG822 Pro CSV Uploader")
        self.geometry("980x700")
        self.minsize(900, 620)

        self.manager = RigolWaveformManager()
        self.manager.set_io_logger(lambda msg: self._ui_call(self.log_io, msg))
        self.operation_in_progress = False

        self.resource_var = tk.StringVar()
        self.idn_var = tk.StringVar(value="Not connected")

        self.mode_var = tk.StringVar(value="dual")
        self.dual_file_var = tk.StringVar()
        self.ch1_file_var = tk.StringVar()
        self.ch2_file_var = tk.StringVar()

        self.sample_rate_var = tk.StringVar(value="1000000")
        self.amplitude_var = tk.StringVar(value="2.0")
        self.offset_var = tk.StringVar(value="2.5")

        self._build_ui()
        self.refresh_resources()

    def _ui_call(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        connection_frame = ttk.LabelFrame(root, text="Instrument")
        connection_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(connection_frame, text="VISA Resource:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        self.resource_combo = ttk.Combobox(connection_frame, textvariable=self.resource_var, state="readonly", width=60)
        self.resource_combo.grid(row=0, column=1, padx=8, pady=8, sticky=tk.W)

        ttk.Button(connection_frame, text="Refresh", command=self.refresh_resources).grid(row=0, column=2, padx=8, pady=8)
        self.connect_button = ttk.Button(connection_frame, text="Connect", command=self.connect_selected_resource)
        self.connect_button.grid(row=0, column=3, padx=8, pady=8)

        ttk.Label(connection_frame, text="IDN:").grid(row=1, column=0, padx=8, pady=(0, 8), sticky=tk.W)
        ttk.Label(connection_frame, textvariable=self.idn_var).grid(row=1, column=1, columnspan=3, padx=8, pady=(0, 8), sticky=tk.W)

        files_frame = ttk.LabelFrame(root, text="CSV Input")
        files_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Radiobutton(files_frame, text="Single CSV (columns CAN_H_V / CAN_L_V)", value="dual", variable=self.mode_var).grid(
            row=0, column=0, columnspan=3, padx=8, pady=(8, 4), sticky=tk.W
        )
        ttk.Entry(files_frame, textvariable=self.dual_file_var, width=90).grid(row=1, column=0, padx=8, pady=4, sticky=tk.W)
        ttk.Button(files_frame, text="Browse", command=self.browse_dual_file).grid(row=1, column=1, padx=8, pady=4)

        ttk.Radiobutton(files_frame, text="Two CSV files (CH1 and CH2 single-column)", value="split", variable=self.mode_var).grid(
            row=2, column=0, columnspan=3, padx=8, pady=(10, 4), sticky=tk.W
        )
        ttk.Label(files_frame, text="CH1 CSV:").grid(row=3, column=0, padx=8, pady=4, sticky=tk.W)
        ttk.Entry(files_frame, textvariable=self.ch1_file_var, width=80).grid(row=3, column=0, padx=(70, 8), pady=4, sticky=tk.W)
        ttk.Button(files_frame, text="Browse", command=lambda: self.browse_single_file(self.ch1_file_var)).grid(row=3, column=1, padx=8, pady=4)

        ttk.Label(files_frame, text="CH2 CSV:").grid(row=4, column=0, padx=8, pady=(0, 8), sticky=tk.W)
        ttk.Entry(files_frame, textvariable=self.ch2_file_var, width=80).grid(row=4, column=0, padx=(70, 8), pady=(0, 8), sticky=tk.W)
        ttk.Button(files_frame, text="Browse", command=lambda: self.browse_single_file(self.ch2_file_var)).grid(row=4, column=1, padx=8, pady=(0, 8))

        params_frame = ttk.LabelFrame(root, text="Output Parameters")
        params_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(params_frame, text="Sample Rate (Hz):").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        ttk.Entry(params_frame, textvariable=self.sample_rate_var, width=14).grid(row=0, column=1, padx=8, pady=8, sticky=tk.W)

        ttk.Label(params_frame, text="Amplitude (Vpp):").grid(row=0, column=2, padx=8, pady=8, sticky=tk.W)
        ttk.Entry(params_frame, textvariable=self.amplitude_var, width=10).grid(row=0, column=3, padx=8, pady=8, sticky=tk.W)

        ttk.Label(params_frame, text="Offset (V):").grid(row=0, column=4, padx=8, pady=8, sticky=tk.W)
        ttk.Entry(params_frame, textvariable=self.offset_var, width=10).grid(row=0, column=5, padx=8, pady=8, sticky=tk.W)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(0, 10))
        self.upload_button = ttk.Button(actions, text="Upload to DG822", command=self.start_upload, style="Accent.TButton")
        self.upload_button.pack(side=tk.LEFT, padx=(0, 8))
        self.download_button = ttk.Button(actions, text="Download Only (No Output)", command=self.start_download_only)
        self.download_button.pack(side=tk.LEFT, padx=(0, 8))
        self.start_output_button = ttk.Button(actions, text="Start Output", command=self.start_output)
        self.start_output_button.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_output_button = ttk.Button(actions, text="Stop Output", command=self.stop_output)
        self.stop_output_button.pack(side=tk.LEFT)

        ch_actions = ttk.Frame(root)
        ch_actions.pack(fill=tk.X, pady=(0, 10))
        self.ch1_on_button = ttk.Button(ch_actions, text="CH1 ON", command=lambda: self.set_channel_output(1, True))
        self.ch1_on_button.pack(side=tk.LEFT, padx=(0, 8))
        self.ch1_off_button = ttk.Button(ch_actions, text="CH1 OFF", command=lambda: self.set_channel_output(1, False))
        self.ch1_off_button.pack(side=tk.LEFT, padx=(0, 8))
        self.ch2_on_button = ttk.Button(ch_actions, text="CH2 ON", command=lambda: self.set_channel_output(2, True))
        self.ch2_on_button.pack(side=tk.LEFT, padx=(0, 8))
        self.ch2_off_button = ttk.Button(ch_actions, text="CH2 OFF", command=lambda: self.set_channel_output(2, False))
        self.ch2_off_button.pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, height=9)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))

        io_log_frame = ttk.LabelFrame(root, text="SCPI I/O Log")
        io_log_frame.pack(fill=tk.BOTH, expand=True)
        self.io_log_text = ScrolledText(io_log_frame, wrap=tk.WORD, height=9)
        self.io_log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

    def log(self, text):
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

    def log_io(self, text):
        self.io_log_text.insert(tk.END, text + "\n")
        self.io_log_text.see(tk.END)
        self.update_idletasks()

    def _set_busy(self, busy):
        self.operation_in_progress = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for btn in [
            self.upload_button,
            self.download_button,
            self.start_output_button,
            self.stop_output_button,
            self.ch1_on_button,
            self.ch1_off_button,
            self.ch2_on_button,
            self.ch2_off_button,
        ]:
            btn.configure(state=state)

    def _begin_operation(self, name):
        if self.operation_in_progress:
            self.log(f"Busy: another operation is running. Skip {name}.")
            return False
        self._set_busy(True)
        return True

    def _end_operation(self):
        self._set_busy(False)

    def refresh_resources(self):
        if not PYVISA_AVAILABLE:
            messagebox.showerror("PyVISA missing", "PyVISA is not installed in this Python environment.")
            return

        try:
            resources = self.manager.list_resources()
        except Exception as exc:
            messagebox.showerror("VISA error", f"Failed to enumerate VISA resources:\n{exc}")
            return

        self.resource_combo["values"] = resources
        if resources:
            self.resource_combo.current(0)
            self.log(f"Found {len(resources)} VISA resource(s).")
        else:
            self.resource_var.set("")
            self.log("No VISA resources found.")

    def connect_selected_resource(self):
        resource = self.resource_var.get().strip()
        if not resource:
            messagebox.showwarning("No resource", "Select a VISA resource first.")
            return

        self.connect_button.configure(state=tk.DISABLED)
        self.idn_var.set("Connecting...")
        self.log(f"Connecting to: {resource}")
        worker = threading.Thread(target=self._connect_worker, args=(resource,), daemon=True)
        worker.start()

    def _connect_worker(self, resource):
        try:
            # First attempt: short timeout with IDN verification.
            idn = self.manager.connect_resource(resource, timeout_ms=12000, verify_idn=True)
            self._ui_call(self.idn_var.set, idn)
            self._ui_call(self.log, f"Connected: {resource}")
            self._ui_call(self.log, f"IDN: {idn}")
        except Exception as first_exc:
            try:
                # Fallback: open session without IDN query, useful for flaky read paths.
                idn = self.manager.connect_resource(resource, timeout_ms=12000, verify_idn=False)
                self._ui_call(self.idn_var.set, idn)
                self._ui_call(self.log, f"Connected with fallback (no IDN): {resource}")
                self._ui_call(self.log, f"Primary connect error: {first_exc}")
            except Exception as second_exc:
                self._ui_call(self.idn_var.set, "Connect failed")
                self._ui_call(self.log, f"Connect failed: {second_exc}")
                self._ui_call(messagebox.showerror, "Connect failed", str(second_exc))
        finally:
            self._ui_call(self.connect_button.configure, state=tk.NORMAL)

    def browse_dual_file(self):
        path = filedialog.askopenfilename(
            title="Select dual-channel CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if path:
            self.dual_file_var.set(path)

    def browse_single_file(self, target_var):
        path = filedialog.askopenfilename(
            title="Select CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if path:
            target_var.set(path)

    def _parse_single_column_csv(self, file_path):
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        with open(path, "r", newline="") as f:
            reader = csv.reader(f)
            rows = [row for row in reader if row]

        if not rows:
            raise ValueError(f"CSV is empty: {path}")

        values = []
        start_idx = 0
        try:
            float(rows[0][0])
        except Exception:
            start_idx = 1

        for row in rows[start_idx:]:
            values.append(float(row[0]))

        if not values:
            raise ValueError(f"No numeric data found in {path}")
        return values

    def start_upload(self):
        if not self.manager.rigol:
            messagebox.showwarning("Not connected", "Connect to DG822 first.")
            return
        if not self._begin_operation("upload"):
            return

        try:
            sample_rate = float(self.sample_rate_var.get())
            amplitude = float(self.amplitude_var.get())
            offset = float(self.offset_var.get())
        except ValueError:
            messagebox.showerror("Invalid parameters", "Sample rate, amplitude, and offset must be numeric.")
            return

        mode = self.mode_var.get()
        if mode == "dual":
            dual_path = self.dual_file_var.get().strip()
            if not dual_path:
                messagebox.showwarning("Missing file", "Choose a dual-channel CSV file.")
                return

            worker = threading.Thread(
                target=self._upload_dual_worker,
                args=(dual_path, sample_rate, amplitude, offset),
                daemon=True,
            )
            worker.start()
        else:
            ch1_path = self.ch1_file_var.get().strip()
            ch2_path = self.ch2_file_var.get().strip()
            if not ch1_path or not ch2_path:
                messagebox.showwarning("Missing files", "Choose both CH1 and CH2 CSV files.")
                return

            worker = threading.Thread(
                target=self._upload_split_worker,
                args=(ch1_path, ch2_path, sample_rate, amplitude, offset),
                daemon=True,
            )
            worker.start()

    def start_download_only(self):
        if not self.manager.rigol:
            messagebox.showwarning("Not connected", "Connect to DG822 first.")
            return
        if not self._begin_operation("download"):
            return

        try:
            sample_rate = float(self.sample_rate_var.get())
        except ValueError:
            messagebox.showerror("Invalid parameters", "Sample rate must be numeric.")
            return

        mode = self.mode_var.get()
        if mode == "dual":
            dual_path = self.dual_file_var.get().strip()
            if not dual_path:
                messagebox.showwarning("Missing file", "Choose a dual-channel CSV file.")
                return
            worker = threading.Thread(
                target=self._download_dual_worker,
                args=(dual_path, sample_rate),
                daemon=True,
            )
            worker.start()
        else:
            ch1_path = self.ch1_file_var.get().strip()
            ch2_path = self.ch2_file_var.get().strip()
            if not ch1_path or not ch2_path:
                messagebox.showwarning("Missing files", "Choose both CH1 and CH2 CSV files.")
                return
            worker = threading.Thread(
                target=self._download_split_worker,
                args=(ch1_path, ch2_path, sample_rate),
                daemon=True,
            )
            worker.start()

    def _upload_dual_worker(self, dual_path, sample_rate, amplitude, offset):
        self.log(f"Uploading dual CSV: {dual_path}")
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                can_h, can_l = self.manager.load_waveform_csv_path(dual_path)
                ok = self.manager.transfer_arrays_to_rigol(
                    can_h,
                    can_l,
                    sample_rate=sample_rate,
                    amplitude=amplitude,
                    offset=offset,
                )
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            if ok:
                self.log("Upload completed successfully.")
                messagebox.showinfo("Success", "Waveform uploaded to DG822.")
            else:
                self.log("Upload failed.")
                messagebox.showerror("Upload failed", "Rigol reported an upload failure. Check log.")
        except Exception as exc:
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            self.log(f"Upload failed: {exc}")
            messagebox.showerror("Upload failed", str(exc))
        finally:
            self._ui_call(self._end_operation)

    def _upload_split_worker(self, ch1_path, ch2_path, sample_rate, amplitude, offset):
        self.log(f"Uploading CH1 CSV: {ch1_path}")
        self.log(f"Uploading CH2 CSV: {ch2_path}")
        buffer = io.StringIO()
        try:
            can_h = self._parse_single_column_csv(ch1_path)
            can_l = self._parse_single_column_csv(ch2_path)
            with redirect_stdout(buffer):
                ok = self.manager.transfer_arrays_to_rigol(
                    can_h,
                    can_l,
                    sample_rate=sample_rate,
                    amplitude=amplitude,
                    offset=offset,
                )
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            if ok:
                self.log("Upload completed successfully.")
                messagebox.showinfo("Success", "Waveform uploaded to DG822.")
            else:
                self.log("Upload failed.")
                messagebox.showerror("Upload failed", "Rigol reported an upload failure. Check log.")
        except Exception as exc:
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            self.log(f"Upload failed: {exc}")
            messagebox.showerror("Upload failed", str(exc))
        finally:
            self._ui_call(self._end_operation)

    def _download_dual_worker(self, dual_path, sample_rate):
        self.log(f"Downloading dual CSV only (no output): {dual_path}")
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                can_h, can_l = self.manager.load_waveform_csv_path(dual_path)
                ok = self.manager.download_arrays_to_rigol(can_h, can_l, sample_rate=sample_rate)
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            if ok:
                self.log("Download completed successfully. Outputs remain OFF.")
                messagebox.showinfo("Download Success", "CSV data downloaded to DG822 memory. Outputs are OFF.")
            else:
                self.log("Download failed.")
                messagebox.showerror("Download failed", "Rigol reported a download failure. Check log.")
        except Exception as exc:
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            self.log(f"Download failed: {exc}")
            messagebox.showerror("Download failed", str(exc))
        finally:
            self._ui_call(self._end_operation)

    def _download_split_worker(self, ch1_path, ch2_path, sample_rate):
        self.log(f"Downloading CH1 CSV only (no output): {ch1_path}")
        self.log(f"Downloading CH2 CSV only (no output): {ch2_path}")
        buffer = io.StringIO()
        try:
            can_h = self._parse_single_column_csv(ch1_path)
            can_l = self._parse_single_column_csv(ch2_path)
            with redirect_stdout(buffer):
                ok = self.manager.download_arrays_to_rigol(can_h, can_l, sample_rate=sample_rate)
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            if ok:
                self.log("Download completed successfully. Outputs remain OFF.")
                messagebox.showinfo("Download Success", "CSV data downloaded to DG822 memory. Outputs are OFF.")
            else:
                self.log("Download failed.")
                messagebox.showerror("Download failed", "Rigol reported a download failure. Check log.")
        except Exception as exc:
            output = buffer.getvalue().strip()
            if output:
                for line in output.splitlines():
                    self.log(line)
            self.log(f"Download failed: {exc}")
            messagebox.showerror("Download failed", str(exc))
        finally:
            self._ui_call(self._end_operation)

    def stop_output(self):
        if not self._begin_operation("stop output"):
            return
        try:
            ok = self.manager.stop_output()
            if ok:
                self.log("Outputs disabled on CH1/CH2.")
            else:
                self.log("Failed to disable outputs.")
        except Exception as exc:
            self.log(f"Stop output error: {exc}")
        finally:
            self._end_operation()

    def start_output(self):
        if not self.manager.rigol:
            messagebox.showwarning("Not connected", "Connect to DG822 first.")
            return
        if not self._begin_operation("start output"):
            return

        worker = threading.Thread(target=self._start_output_worker, daemon=True)
        worker.start()

    def _start_output_worker(self):
        self.log("Starting output on CH1/CH2...")
        try:
            try:
                sample_rate = float(self.sample_rate_var.get())
            except Exception:
                sample_rate = 1000000.0
            try:
                amplitude = float(self.amplitude_var.get())
            except Exception:
                amplitude = None
            try:
                offset = float(self.offset_var.get())
            except Exception:
                offset = None

            self.manager.activate_downloaded_waveform(
                sample_rate=sample_rate,
                amplitude=amplitude,
                offset=offset,
            )
            ok = self.manager.ensure_outputs_on()
            if ok:
                self.log("Outputs enabled on CH1/CH2.")
                messagebox.showinfo("Output Started", "CH1 and CH2 outputs are ON.")
            else:
                self.log("Failed to enable outputs.")
                messagebox.showerror("Start Output Failed", "Could not enable CH1/CH2 outputs.")
        except Exception as exc:
            self.log(f"Start output error: {exc}")
            messagebox.showerror("Start Output Failed", str(exc))
        finally:
            self._ui_call(self._end_operation)

    def set_channel_output(self, channel, enabled):
        if not self.manager.rigol:
            messagebox.showwarning("Not connected", "Connect to DG822 first.")
            return
        if not self._begin_operation(f"CH{channel} {'ON' if enabled else 'OFF'}"):
            return

        worker = threading.Thread(
            target=self._set_channel_output_worker,
            args=(channel, enabled),
            daemon=True,
        )
        worker.start()

    def _set_channel_output_worker(self, channel, enabled):
        state = "ON" if enabled else "OFF"
        self.log(f"Setting CH{channel} {state}...")
        try:
            ok = self.manager.set_channel_output(channel, enabled)
            if ok:
                self.log(f"CH{channel} {state} success.")
            else:
                self.log(f"CH{channel} {state} failed.")
                messagebox.showerror("Channel Output Failed", f"Failed to set CH{channel} {state}.")
        except Exception as exc:
            self.log(f"CH{channel} {state} error: {exc}")
            messagebox.showerror("Channel Output Failed", str(exc))
        finally:
            self._ui_call(self._end_operation)


def main():
    app = DG822CsvGui()
    app.mainloop()


if __name__ == "__main__":
    main()
