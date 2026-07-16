#!/usr/bin/env python3
"""Interactive CSV waveform editor.

Load a CSV file, plot the voltage values (absolute value) on a chart,
drag points on the curve to edit them, and export the edited curve to a
new CSV file.

Zoom is manual only (mouse wheel and the matplotlib pan/zoom toolbar) -
the view never auto-rescales while editing, so dragging points does not
jump the view around.
"""

import csv
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

# Column-name hints that suggest a column is a sample index / time axis
# rather than a plotted voltage curve.
_INDEX_HEADER_HINTS = ("index", "sample", "time", "sec", "t(")


def _looks_sequential(values):
    """Return True if values form a constant, non-zero step sequence (0,1,2,... or similar)."""
    if len(values) < 2:
        return False
    step = values[1] - values[0]
    if step == 0:
        return False
    for a, b in zip(values, values[1:]):
        if abs((b - a) - step) > 1e-9:
            return False
    return True


def read_csv_curves(path):
    """Parse a CSV file into (x_values, curves, x_header).

    curves is an ordered dict of {column_name: [abs(value), ...]}.
    x_header is the header text of the index/time column if one was
    detected, otherwise None (in which case x_values is just the row index).
    """
    with open(path, "r", newline="") as f:
        rows = [row for row in csv.reader(f) if row]

    if not rows:
        raise ValueError(f"CSV is empty: {path}")

    header = None
    data_rows = rows
    try:
        [float(v) for v in rows[0]]
    except ValueError:
        header = rows[0]
        data_rows = rows[1:]

    if not data_rows:
        raise ValueError(f"No data rows found in {path}")

    ncols = len(data_rows[0])
    columns = [[] for _ in range(ncols)]
    for row_num, row in enumerate(data_rows, start=1):
        if len(row) != ncols:
            raise ValueError(f"Row {row_num} has {len(row)} columns, expected {ncols}")
        for i, val in enumerate(row):
            columns[i].append(float(val))

    if header is None:
        header = [f"col{i + 1}" for i in range(ncols)]

    x_is_index_col = False
    if ncols >= 2:
        first_name = header[0].strip().lower()
        if any(hint in first_name for hint in _INDEX_HEADER_HINTS) or _looks_sequential(columns[0]):
            x_is_index_col = True

    if x_is_index_col:
        x_values = columns[0]
        x_header = header[0]
        curve_names = header[1:]
        curve_columns = columns[1:]
    else:
        x_values = list(range(len(data_rows)))
        x_header = None
        curve_names = header
        curve_columns = columns

    curves = {name: [abs(v) for v in col] for name, col in zip(curve_names, curve_columns)}
    return x_values, curves, x_header


def _format_x(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}"


def write_csv_curves(path, x_values, curves, x_header):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        headers = ([x_header] if x_header else []) + list(curves.keys())
        writer.writerow(headers)
        for i in range(len(x_values)):
            row = ([_format_x(x_values[i])] if x_header else []) + [f"{curves[name][i]:.6f}" for name in curves]
            writer.writerow(row)


class CsvWaveformEditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CSV Waveform Editor")
        self.geometry("1100x760")
        self.minsize(900, 650)

        self.csv_path = None
        self.x_header = None
        self.x_values = []
        self.curves = {}
        self.lines = {}
        self._drag_curve = None
        self._drag_index = None

        self._build_ui()

    def _build_ui(self):
        toolbar_frame = ttk.Frame(self, padding=8)
        toolbar_frame.pack(fill=tk.X)
        ttk.Button(toolbar_frame, text="Load CSV...", command=self.load_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar_frame, text="Save As CSV...", command=self.save_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar_frame, text="Reset View", command=self.reset_view).pack(side=tk.LEFT, padx=(0, 8))
        self.file_label_var = tk.StringVar(value="No file loaded")
        ttk.Label(toolbar_frame, textvariable=self.file_label_var).pack(side=tk.LEFT, padx=(8, 0))

        fig_frame = ttk.Frame(self)
        fig_frame.pack(fill=tk.BOTH, expand=True)

        self.figure = Figure(figsize=(9, 6), dpi=100)
        self.ax = self.figure.add_subplot(111)
        self.ax.set_xlabel("Sample Index")
        self.ax.set_ylabel("Voltage (V, absolute)")
        self.ax.grid(True, linestyle=":", alpha=0.6)

        self.canvas = FigureCanvasTkAgg(self.figure, master=fig_frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        nav_frame = ttk.Frame(fig_frame)
        nav_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, nav_frame)
        self.toolbar.update()

        status_frame = ttk.Frame(self, padding=(8, 4))
        status_frame.pack(fill=tk.X)
        self.status_var = tk.StringVar(
            value="拖动曲线上的点可修改该采样点的电压值（X 保持不变）。使用工具栏或鼠标滚轮进行手动缩放。"
        )
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)

    def load_csv(self):
        path = filedialog.askopenfilename(
            title="Select CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            x_values, curves, x_header = read_csv_curves(path)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        self.csv_path = path
        self.x_values = x_values
        self.x_header = x_header
        self.curves = curves
        self.file_label_var.set(Path(path).name)
        self.status_var.set(f"已加载 {Path(path).name}：{len(x_values)} 个采样点，{len(curves)} 条曲线。")
        self._plot_curves()

    def _plot_curves(self):
        self.ax.clear()
        self.ax.set_xlabel(self.x_header or "Sample Index")
        self.ax.set_ylabel("Voltage (V, absolute)")
        self.ax.grid(True, linestyle=":", alpha=0.6)

        self.lines = {}
        for name, values in self.curves.items():
            (line,) = self.ax.plot(self.x_values, values, marker="o", markersize=4, linewidth=1.2, label=name)
            self.lines[name] = line
        if len(self.curves) > 1:
            self.ax.legend(loc="upper right")

        self._apply_initial_limits()
        self.ax.set_autoscale_on(False)
        self.canvas.draw_idle()

    def _apply_initial_limits(self):
        all_y = [v for values in self.curves.values() for v in values]
        if not all_y or not self.x_values:
            return
        x_min, x_max = min(self.x_values), max(self.x_values)
        y_min, y_max = min(all_y), max(all_y)
        x_pad = (x_max - x_min) * 0.02 or 1
        y_pad = (y_max - y_min) * 0.1 or 0.5
        self.ax.set_xlim(x_min - x_pad, x_max + x_pad)
        self.ax.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)

    def reset_view(self):
        if not self.curves:
            return
        self._apply_initial_limits()
        self.canvas.draw_idle()

    def _on_scroll(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return
        base_scale = 1.2
        scale = 1 / base_scale if event.button == "up" else base_scale
        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        self.ax.set_xlim(
            event.xdata - (event.xdata - cur_xlim[0]) * scale,
            event.xdata + (cur_xlim[1] - event.xdata) * scale,
        )
        self.ax.set_ylim(
            event.ydata - (event.ydata - cur_ylim[0]) * scale,
            event.ydata + (cur_ylim[1] - event.ydata) * scale,
        )
        self.canvas.draw_idle()

    def _find_nearest_point(self, event, pixel_threshold=12):
        if event.x is None or event.y is None:
            return None
        best = None
        best_dist = pixel_threshold
        for name, values in self.curves.items():
            if not values:
                continue
            pts = self.ax.transData.transform(np.column_stack([self.x_values, values]))
            dists = np.hypot(pts[:, 0] - event.x, pts[:, 1] - event.y)
            idx = int(np.argmin(dists))
            dist = dists[idx]
            if dist < best_dist:
                best_dist = dist
                best = (name, idx)
        return best

    def _on_press(self, event):
        if self.toolbar.mode:
            # Pan/zoom tool is active; let the toolbar handle the click.
            return
        if event.inaxes != self.ax or event.button != 1:
            return
        hit = self._find_nearest_point(event)
        if hit:
            self._drag_curve, self._drag_index = hit
            self.status_var.set(f"正在编辑: {self._drag_curve}[{self._drag_index}]")

    def _on_motion(self, event):
        if self._drag_curve is None or event.inaxes != self.ax or event.ydata is None:
            return
        new_y = max(0.0, event.ydata)
        values = self.curves[self._drag_curve]
        values[self._drag_index] = new_y
        self.lines[self._drag_curve].set_ydata(values)
        self.canvas.draw_idle()

    def _on_release(self, _event):
        if self._drag_curve is not None:
            value = self.curves[self._drag_curve][self._drag_index]
            self.status_var.set(f"已更新 {self._drag_curve}[{self._drag_index}] = {value:.6f} V")
        self._drag_curve = None
        self._drag_index = None

    def save_csv(self):
        if not self.curves:
            messagebox.showwarning("无数据", "请先加载 CSV 文件。")
            return

        initial_name = f"{Path(self.csv_path).stem}_edited.csv" if self.csv_path else "edited.csv"
        path = filedialog.asksaveasfilename(
            title="保存修改后的 CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=initial_name,
        )
        if not path:
            return

        try:
            write_csv_curves(path, self.x_values, self.curves, self.x_header)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))
            return

        self.status_var.set(f"已保存到 {path}")
        messagebox.showinfo("保存成功", f"已保存修改后的 CSV：\n{path}")


def main():
    app = CsvWaveformEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
