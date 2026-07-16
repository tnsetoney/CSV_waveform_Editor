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

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        connection_frame = ttk.LabelFrame(root, text="Instrument")
        connection_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(connection_frame, text="VISA Resource:").grid(row=0, column=0, padx=8, pady=8, sticky=tk.W)
        self.resource_combo = ttk.Combobox(connection_frame, textvariable=self.resource_var, state="readonly", width=60)
        self.resource_combo.grid(row=0, column=1, padx=8, pady=8, sticky=tk.W)

        ttk.Button(connection_frame, text="Refresh", command=self.refresh_resources).grid(row=0, column=2, padx=8, pady=8)
        ttk.Button(connection_frame, text="Connect", command=self.connect_selected_resource).grid(row=0, column=3, padx=8, pady=8)

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
        ttk.Button(actions, text="Upload to DG822", command=self.start_upload, style="Accent.TButton").pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Stop Output", command=self.stop_output).pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(root, text="Log")
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = ScrolledText(log_frame, wrap=tk.WORD, height=18)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def log(self, text):
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.update_idletasks()

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

        try:
            idn = self.manager.connect_resource(resource)
            self.idn_var.set(idn)
            self.log(f"Connected: {resource}")
            self.log(f"*IDN?: {idn}")
        except Exception as exc:
            messagebox.showerror("Connect failed", str(exc))
            self.log(f"Connect failed: {exc}")

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

    def stop_output(self):
        try:
            ok = self.manager.stop_output()
            if ok:
                self.log("Outputs disabled on CH1/CH2.")
            else:
                self.log("Failed to disable outputs.")
        except Exception as exc:
            self.log(f"Stop output error: {exc}")


def main():
    app = DG822CsvGui()
    app.mainloop()


if __name__ == "__main__":
    main()
