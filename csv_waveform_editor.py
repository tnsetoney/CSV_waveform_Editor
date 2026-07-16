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
from matplotlib.patches import Rectangle

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
    """Parse a CSV file into (x_values, curves, x_header, had_header).

    curves is an ordered dict of {column_name: [abs(value), ...]}.
    x_header is the header text of the index/time column if one was
    detected, otherwise None (in which case x_values is just the row index).
    had_header indicates whether the source file actually had a header row
    (as opposed to generic "colN" names made up because it had none).
    """
    with open(path, "r", newline="") as f:
        rows = [row for row in csv.reader(f) if row]

    if not rows:
        raise ValueError(f"CSV is empty: {path}")

    header = None
    data_rows = rows
    had_header = False
    try:
        [float(v) for v in rows[0]]
    except ValueError:
        header = rows[0]
        data_rows = rows[1:]
        had_header = True

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
    return x_values, curves, x_header, had_header


def _format_x(value):
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.6f}"


def write_csv_curves(path, x_values, curves, x_header, include_header=True):
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        if include_header:
            headers = ([x_header] if x_header else []) + list(curves.keys())
            writer.writerow(headers)
        for i in range(len(x_values)):
            row = ([_format_x(x_values[i])] if x_header else []) + [f"{curves[name][i]:.6f}" for name in curves]
            writer.writerow(row)


# Interpolation methods offered in the "Interpolate..." dialog.
INTERPOLATION_METHODS = ["Linear", "Cubic", "B-Spline", "Akima", "Lanczos"]


def _lanczos_kernel(x, a=3):
    x = np.asarray(x, dtype=float)
    out = np.sinc(x) * np.sinc(x / a)
    out[np.abs(x) > a] = 0.0
    return out


def _lanczos_resample(old_x, old_y, new_x, a=3):
    """Windowed-sinc (Lanczos) resampling, assuming roughly uniform spacing in old_x."""
    old_x = np.asarray(old_x, dtype=float)
    old_y = np.asarray(old_y, dtype=float)
    n = len(old_x)
    if n < 2:
        return np.full(len(new_x), old_y[0] if n == 1 else 0.0)

    dx = (old_x[-1] - old_x[0]) / (n - 1)
    if dx == 0:
        return np.full(len(new_x), old_y[0])

    new_y = np.empty(len(new_x), dtype=float)
    for i, xt in enumerate(new_x):
        pos = (xt - old_x[0]) / dx
        base = int(np.floor(pos))
        idxs = np.arange(base - a + 1, base + a + 1)
        weights = _lanczos_kernel(pos - idxs, a)
        clipped = np.clip(idxs, 0, n - 1)
        wsum = weights.sum()
        if wsum == 0:
            new_y[i] = old_y[clipped[np.argmin(np.abs(idxs - pos))]]
        else:
            new_y[i] = np.sum(weights * old_y[clipped]) / wsum
    return new_y


def interpolate_values(old_x, old_y, new_x, method):
    """Resample old_y (sampled at old_x) onto new_x using the given method.

    method is one of the labels in INTERPOLATION_METHODS.
    """
    old_x = np.asarray(old_x, dtype=float)
    old_y = np.asarray(old_y, dtype=float)
    new_x = np.asarray(new_x, dtype=float)

    if method == "Linear":
        return np.interp(new_x, old_x, old_y)
    if method == "Cubic":
        from scipy.interpolate import CubicSpline

        return CubicSpline(old_x, old_y)(new_x)
    if method == "B-Spline":
        from scipy.interpolate import make_interp_spline

        k = min(3, len(old_x) - 1)
        return make_interp_spline(old_x, old_y, k=k)(new_x)
    if method == "Akima":
        from scipy.interpolate import Akima1DInterpolator

        return Akima1DInterpolator(old_x, old_y)(new_x)
    if method == "Lanczos":
        return _lanczos_resample(old_x, old_y, new_x)
    raise ValueError(f"Unknown interpolation method: {method}")


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

        # Single-point drag state.
        self._drag_curve = None
        self._drag_index = None

        # Multi-point selection + group drag state.
        self.selected_points = []  # list of (curve_name, index)
        self._selection_scatter = None
        self._drag_mode = None  # None | "single" | "group" | "box"
        self._drag_start_values = {}
        self._drag_anchor_y = None
        self._select_box_patch = None
        self._select_box_start_data = None
        self._ctrl_held = False

        # Right-button pan state.
        self._right_pan_active = False
        self._right_pan_start_display = None
        self._right_pan_start_xlim = None
        self._right_pan_start_ylim = None

        # Undo history: list of {"snapshot", "changed_x_range", "description"}.
        self.undo_stack = []
        self._undo_stack_limit = 50
        self._pending_pre_snapshot = None
        self._pending_changed_range = None

        # Bottom overview ("minimap") panel state.
        self.overview_lines = {}
        self._overview_indicator = None
        self._xlim_cid = None

        # Whether to write a header row when saving; defaults to match the
        # loaded file, but the user can override it via the checkbox.
        self.include_header_var = tk.BooleanVar(value=True)

        self._build_ui()

    def _build_ui(self):
        toolbar_frame = ttk.Frame(self, padding=8)
        toolbar_frame.pack(fill=tk.X)
        ttk.Button(toolbar_frame, text="Load CSV...", command=self.load_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar_frame, text="Save As CSV...", command=self.save_csv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar_frame, text="Interpolate...", command=self.open_interpolate_dialog).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(toolbar_frame, text="Undo (Ctrl+Z)", command=self.undo).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(toolbar_frame, text="Reset View", command=self.reset_view).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(
            toolbar_frame, text="Include header row when saving", variable=self.include_header_var
        ).pack(side=tk.LEFT, padx=(0, 8))
        self.file_label_var = tk.StringVar(value="No file loaded")
        ttk.Label(toolbar_frame, textvariable=self.file_label_var).pack(side=tk.LEFT, padx=(8, 0))

        fig_frame = ttk.Frame(self)
        fig_frame.pack(fill=tk.BOTH, expand=True)

        self.figure = Figure(figsize=(9, 7), dpi=100)
        gridspec = self.figure.add_gridspec(2, 1, height_ratios=[5, 1], hspace=0.35)
        self.ax = self.figure.add_subplot(gridspec[0])
        self.ax.set_xlabel("Sample Index")
        self.ax.set_ylabel("Voltage (V, absolute)")
        self.ax.grid(True, linestyle=":", alpha=0.6)

        self.ax_overview = self.figure.add_subplot(gridspec[1])
        self.ax_overview.set_xlabel("Overview (full range)")
        self.ax_overview.set_yticks([])
        self.ax_overview.grid(True, linestyle=":", alpha=0.4)
        # Overview always shows the full curve; don't let the toolbar pan/zoom it.
        self.ax_overview.set_navigate(False)

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
            value=(
                "Drag a point on the curve to change its value (X stays fixed). "
                "Ctrl+click or drag a selection box to multi-select, then drag any selected point "
                "to move the whole selection's height together. Hold the right mouse button and drag "
                "to pan the view; a plain right click cancels the active Pan/Zoom tool. "
                "Use the toolbar or scroll wheel to zoom manually. The panel below is an overview of "
                "the full curve; the orange box shows the currently visible/edited range. Ctrl+Z undoes."
            )
        )
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT)

        canvas_widget = self.canvas.get_tk_widget()
        canvas_widget.bind("<Enter>", lambda _e: canvas_widget.focus_set())
        canvas_widget.bind("<FocusOut>", lambda _e: setattr(self, "_ctrl_held", False))

        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("key_press_event", self._on_key_press)
        self.canvas.mpl_connect("key_release_event", self._on_key_release)

        self.bind_all("<Control-z>", self.undo)

    def load_csv(self):
        path = filedialog.askopenfilename(
            title="Select CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            x_values, curves, x_header, had_header = read_csv_curves(path)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return

        self.csv_path = path
        self.x_values = x_values
        self.x_header = x_header
        self.curves = curves
        self.selected_points = []
        self.undo_stack = []
        self._pending_pre_snapshot = None
        self._pending_changed_range = None
        self.include_header_var.set(had_header)
        self.file_label_var.set(Path(path).name)
        self.status_var.set(f"Loaded {Path(path).name}: {len(x_values)} samples, {len(curves)} curve(s).")
        self._plot_curves()

    def _plot_curves(self):
        self.ax.clear()
        self.ax.set_xlabel(self.x_header or "Sample Index")
        self.ax.set_ylabel("Voltage (V, absolute)")
        self.ax.grid(True, linestyle=":", alpha=0.6)

        self.ax_overview.clear()
        self.ax_overview.set_xlabel("Overview (full range)")
        self.ax_overview.set_yticks([])
        self.ax_overview.grid(True, linestyle=":", alpha=0.4)
        self.ax_overview.set_navigate(False)

        self.lines = {}
        self.overview_lines = {}
        for name, values in self.curves.items():
            (line,) = self.ax.plot(self.x_values, values, marker="o", markersize=4, linewidth=1.2, label=name)
            self.lines[name] = line
            (ov_line,) = self.ax_overview.plot(self.x_values, values, linewidth=0.8)
            self.overview_lines[name] = ov_line
        if len(self.curves) > 1:
            self.ax.legend(loc="upper right")

        self._selection_scatter = self.ax.scatter(
            [], [], s=90, facecolors="none", edgecolors="red", linewidths=1.6, zorder=5
        )
        self._refresh_selection_highlight(redraw=False)

        self._apply_initial_limits()
        self.ax.set_autoscale_on(False)
        self._apply_overview_limits()
        self.ax_overview.set_autoscale_on(False)
        self._create_overview_indicator()
        self._connect_overview_callback()
        self._update_overview_indicator()
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

    def _apply_overview_limits(self):
        """The overview panel always shows the full data range, regardless of zoom."""
        all_y = [v for values in self.curves.values() for v in values]
        if not all_y or not self.x_values:
            return
        x_min, x_max = min(self.x_values), max(self.x_values)
        y_min, y_max = min(all_y), max(all_y)
        x_pad = (x_max - x_min) * 0.02 or 1
        y_pad = (y_max - y_min) * 0.1 or 0.5
        self.ax_overview.set_xlim(x_min - x_pad, x_max + x_pad)
        self.ax_overview.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)

    def _create_overview_indicator(self):
        y_lo, y_hi = self.ax_overview.get_ylim()
        x_lo, x_hi = self.ax.get_xlim()
        self._overview_indicator = Rectangle(
            (x_lo, y_lo),
            x_hi - x_lo,
            y_hi - y_lo,
            edgecolor="orange",
            facecolor="orange",
            alpha=0.25,
            linewidth=1.2,
            zorder=6,
        )
        self.ax_overview.add_patch(self._overview_indicator)

    def _connect_overview_callback(self):
        if self._xlim_cid is not None:
            try:
                self.ax.callbacks.disconnect(self._xlim_cid)
            except Exception:
                pass
        self._xlim_cid = self.ax.callbacks.connect("xlim_changed", lambda _ax: self._update_overview_indicator())

    def _update_overview_indicator(self):
        if self._overview_indicator is None:
            return
        x_lo, x_hi = self.ax.get_xlim()
        y_lo, y_hi = self.ax_overview.get_ylim()
        self._overview_indicator.set_xy((x_lo, y_lo))
        self._overview_indicator.set_width(x_hi - x_lo)
        self._overview_indicator.set_height(y_hi - y_lo)
        self.canvas.draw_idle()

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

    def _points_in_box(self, x0, y0, x1, y1):
        x_min, x_max = min(x0, x1), max(x0, x1)
        y_min, y_max = min(y0, y1), max(y0, y1)
        found = []
        for name, values in self.curves.items():
            for idx, (x, y) in enumerate(zip(self.x_values, values)):
                if x_min <= x <= x_max and y_min <= y <= y_max:
                    found.append((name, idx))
        return found

    def _refresh_selection_highlight(self, redraw=True):
        if self._selection_scatter is None:
            return
        if not self.selected_points:
            self._selection_scatter.set_offsets(np.empty((0, 2)))
        else:
            xs = [self.x_values[idx] for _name, idx in self.selected_points]
            ys = [self.curves[name][idx] for name, idx in self.selected_points]
            self._selection_scatter.set_offsets(np.column_stack([xs, ys]))
        if redraw:
            self.canvas.draw_idle()

    def _on_key_press(self, event):
        if event.key in ("control", "ctrl"):
            self._ctrl_held = True

    def _on_key_release(self, event):
        if event.key in ("control", "ctrl"):
            self._ctrl_held = False

    def _cancel_active_tool(self):
        """Deactivate the matplotlib toolbar's Pan or Zoom tool, if one is active."""
        mode = self.toolbar.mode
        if mode == "pan/zoom":
            self.toolbar.pan()
        elif mode == "zoom rect":
            self.toolbar.zoom()

    def _on_right_press(self, event):
        if event.inaxes != self.ax:
            return
        # A right click always cancels whatever toolbar tool (pan/zoom) is active.
        if self.toolbar.mode:
            self._cancel_active_tool()
            self.status_var.set("Cancelled the active Pan/Zoom tool.")
        if event.x is None or event.y is None:
            return
        # Also arm right-button pan, in case the user drags instead of just clicking.
        self._right_pan_active = True
        self._right_pan_start_display = (event.x, event.y)
        self._right_pan_start_xlim = self.ax.get_xlim()
        self._right_pan_start_ylim = self.ax.get_ylim()

    def _on_right_motion(self, event):
        if event.x is None or event.y is None or self._right_pan_start_display is None:
            return
        inv = self.ax.transData.inverted()
        x0_data, y0_data = inv.transform(self._right_pan_start_display)
        x1_data, y1_data = inv.transform((event.x, event.y))
        dx = x1_data - x0_data
        dy = y1_data - y0_data
        x0, x1 = self._right_pan_start_xlim
        y0, y1 = self._right_pan_start_ylim
        self.ax.set_xlim(x0 - dx, x1 - dx)
        self.ax.set_ylim(y0 - dy, y1 - dy)
        self.canvas.draw_idle()

    def _on_press(self, event):
        if event.button == 3:
            self._on_right_press(event)
            return
        if self.toolbar.mode:
            # Pan/zoom tool is active; let the toolbar handle the click.
            return
        if event.inaxes != self.ax or event.button != 1:
            return

        hit = self._find_nearest_point(event)

        if hit is not None:
            if self._ctrl_held:
                # Ctrl+click toggles this point in the selection without dragging.
                if hit in self.selected_points:
                    self.selected_points.remove(hit)
                else:
                    self.selected_points.append(hit)
                self._drag_mode = None
                self._refresh_selection_highlight()
                self.status_var.set(f"Selected {len(self.selected_points)} point(s).")
                return

            if hit in self.selected_points and len(self.selected_points) > 1:
                # Start a group drag of every currently selected point.
                self._drag_mode = "group"
                self._drag_anchor_y = event.ydata
                self._drag_start_values = {(c, i): self.curves[c][i] for c, i in self.selected_points}
                xs = [self.x_values[i] for _c, i in self.selected_points]
                self._pending_pre_snapshot = self._make_snapshot()
                self._pending_changed_range = (min(xs), max(xs))
                self.status_var.set(f"Dragging {len(self.selected_points)} selected point(s) together...")
            else:
                # Plain click on a point: make it the sole selection and drag it alone.
                self.selected_points = [hit]
                self._refresh_selection_highlight()
                self._drag_mode = "single"
                self._drag_curve, self._drag_index = hit
                self._pending_pre_snapshot = self._make_snapshot()
                x_at = self.x_values[self._drag_index]
                self._pending_changed_range = (x_at, x_at)
                self.status_var.set(f"Editing: {self._drag_curve}[{self._drag_index}]")
            return

        # Clicked empty space: start (or continue, if Ctrl held) a box selection.
        if not self._ctrl_held:
            self.selected_points = []
            self._refresh_selection_highlight()
        if event.xdata is None or event.ydata is None:
            return
        self._drag_mode = "box"
        self._select_box_start_data = (event.xdata, event.ydata)
        self._select_box_patch = Rectangle(
            (event.xdata, event.ydata),
            0,
            0,
            edgecolor="dodgerblue",
            facecolor="dodgerblue",
            alpha=0.15,
            linewidth=1.2,
            linestyle="--",
        )
        self.ax.add_patch(self._select_box_patch)

    def _on_motion(self, event):
        if self._right_pan_active:
            self._on_right_motion(event)
            return
        if self._drag_mode == "single":
            if event.inaxes != self.ax or event.ydata is None:
                return
            new_y = max(0.0, event.ydata)
            values = self.curves[self._drag_curve]
            values[self._drag_index] = new_y
            self.lines[self._drag_curve].set_ydata(values)
            self.overview_lines[self._drag_curve].set_ydata(values)
            self._refresh_selection_highlight(redraw=False)
            self.canvas.draw_idle()
        elif self._drag_mode == "group":
            if event.inaxes != self.ax or event.ydata is None:
                return
            delta = event.ydata - self._drag_anchor_y
            touched_curves = set()
            for (name, idx), start_value in self._drag_start_values.items():
                self.curves[name][idx] = max(0.0, start_value + delta)
                touched_curves.add(name)
            for name in touched_curves:
                self.lines[name].set_ydata(self.curves[name])
                self.overview_lines[name].set_ydata(self.curves[name])
            self._refresh_selection_highlight(redraw=False)
            self.canvas.draw_idle()
        elif self._drag_mode == "box":
            if self._select_box_patch is None or self._select_box_start_data is None:
                return
            if event.xdata is None or event.ydata is None:
                return
            x0, y0 = self._select_box_start_data
            x1, y1 = event.xdata, event.ydata
            self._select_box_patch.set_xy((min(x0, x1), min(y0, y1)))
            self._select_box_patch.set_width(abs(x1 - x0))
            self._select_box_patch.set_height(abs(y1 - y0))
            self.canvas.draw_idle()

    def _on_release(self, event):
        if self._right_pan_active:
            self._right_pan_active = False
            self._right_pan_start_display = None
            self._right_pan_start_xlim = None
            self._right_pan_start_ylim = None
            return
        if self._drag_mode == "single":
            value = self.curves[self._drag_curve][self._drag_index]
            self._finalize_pending_undo(f"Drag {self._drag_curve}[{self._drag_index}]")
            self.status_var.set(f"Updated {self._drag_curve}[{self._drag_index}] = {value:.6f} V")
        elif self._drag_mode == "group":
            self._finalize_pending_undo(f"Group drag of {len(self.selected_points)} point(s)")
            self.status_var.set(f"Updated the height of {len(self.selected_points)} selected point(s).")
        elif self._drag_mode == "box":
            if self._select_box_start_data is not None and event.xdata is not None and event.ydata is not None:
                x0, y0 = self._select_box_start_data
                found = self._points_in_box(x0, y0, event.xdata, event.ydata)
                if self._ctrl_held:
                    for point in found:
                        if point not in self.selected_points:
                            self.selected_points.append(point)
                else:
                    self.selected_points = found
                self._refresh_selection_highlight()
                if self.selected_points:
                    self.status_var.set(f"Selected {len(self.selected_points)} point(s).")
            if self._select_box_patch is not None:
                self._select_box_patch.remove()
                self._select_box_patch = None
            self._select_box_start_data = None
            self.canvas.draw_idle()

        self._drag_mode = None
        self._drag_curve = None
        self._drag_index = None
        self._drag_start_values = {}
        self._drag_anchor_y = None

    # -- Undo history -----------------------------------------------------

    def _make_snapshot(self):
        return {
            "x_values": list(self.x_values),
            "curves": {name: list(values) for name, values in self.curves.items()},
        }

    def _restore_snapshot(self, snapshot):
        self.x_values = list(snapshot["x_values"])
        self.curves = {name: list(values) for name, values in snapshot["curves"].items()}
        self.selected_points = []

    def _push_undo(self, pre_snapshot, changed_x_range, description):
        self.undo_stack.append(
            {"snapshot": pre_snapshot, "changed_x_range": changed_x_range, "description": description}
        )
        if len(self.undo_stack) > self._undo_stack_limit:
            self.undo_stack.pop(0)

    def _finalize_pending_undo(self, description):
        """Push the drag that just finished onto the undo stack, if it actually changed data."""
        if self._pending_pre_snapshot is None:
            return
        if self._pending_pre_snapshot["curves"] != self.curves:
            self._push_undo(self._pending_pre_snapshot, self._pending_changed_range, description)
        self._pending_pre_snapshot = None
        self._pending_changed_range = None

    def undo(self, _event=None):
        if not self.undo_stack:
            self.status_var.set("Nothing to undo.")
            return
        entry = self.undo_stack.pop()
        self._restore_snapshot(entry["snapshot"])
        self._plot_curves()
        self._zoom_to_range(entry["changed_x_range"])
        self.status_var.set(f"Undid: {entry['description']}")

    def _zoom_to_range(self, x_range, x_pad_frac=0.15, y_pad_frac=0.2):
        if x_range is None or not self.x_values:
            return
        x_min, x_max = x_range
        if x_min == x_max:
            x_min -= 1.0
            x_max += 1.0
        span = x_max - x_min
        pad = span * x_pad_frac or 1.0
        x_lo, x_hi = x_min - pad, x_max + pad
        self.ax.set_xlim(x_lo, x_hi)

        ys_in_range = [
            y for values in self.curves.values() for x, y in zip(self.x_values, values) if x_lo <= x <= x_hi
        ]
        if ys_in_range:
            y_min, y_max = min(ys_in_range), max(ys_in_range)
            y_pad = (y_max - y_min) * y_pad_frac or 0.5
            self.ax.set_ylim(max(0.0, y_min - y_pad), y_max + y_pad)
        self.canvas.draw_idle()

    # -- Interpolation ------------------------------------------------------

    def open_interpolate_dialog(self):
        if not self.curves or not self.x_values:
            messagebox.showwarning("No data", "Load a CSV file first.")
            return

        dialog = tk.Toplevel(self)
        dialog.title("Interpolate")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Method:").grid(row=0, column=0, padx=(0, 8), pady=6, sticky=tk.W)
        method_var = tk.StringVar(value=INTERPOLATION_METHODS[0])
        method_combo = ttk.Combobox(
            frame, textvariable=method_var, values=INTERPOLATION_METHODS, state="readonly", width=16
        )
        method_combo.grid(row=0, column=1, pady=6, sticky=tk.W)

        ttk.Label(frame, text="Target point count:").grid(row=1, column=0, padx=(0, 8), pady=6, sticky=tk.W)
        count_var = tk.StringVar(value=str(len(self.x_values)))
        ttk.Entry(frame, textvariable=count_var, width=18).grid(row=1, column=1, pady=6, sticky=tk.W)

        ttk.Label(
            frame,
            text="Resamples every curve to the chosen point count using the selected method "
            "(applying this can be reverted with Undo).",
            wraplength=320,
            justify=tk.LEFT,
        ).grid(row=2, column=0, columnspan=2, pady=(4, 10), sticky=tk.W)

        button_row = ttk.Frame(frame)
        button_row.grid(row=3, column=0, columnspan=2, sticky=tk.E)

        def on_apply():
            try:
                target_count = int(count_var.get())
            except ValueError:
                messagebox.showerror("Invalid input", "Target point count must be an integer.", parent=dialog)
                return
            if target_count < 2:
                messagebox.showerror("Invalid input", "Target point count must be at least 2.", parent=dialog)
                return
            try:
                self._apply_interpolation(method_var.get(), target_count)
            except Exception as exc:
                messagebox.showerror("Interpolation failed", str(exc), parent=dialog)
                return
            dialog.destroy()

        ttk.Button(button_row, text="Apply", command=on_apply).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(button_row, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT)

    def _apply_interpolation(self, method, target_count):
        old_x = np.asarray(self.x_values, dtype=float)
        x_min, x_max = float(old_x[0]), float(old_x[-1])
        new_x = np.linspace(x_min, x_max, int(target_count))

        new_curves = {}
        for name, values in self.curves.items():
            new_y = interpolate_values(old_x, values, new_x, method)
            new_y = np.clip(new_y, 0.0, None)
            new_curves[name] = new_y.tolist()

        pre_snapshot = self._make_snapshot()
        self.x_values = new_x.tolist()
        self.curves = new_curves
        self.selected_points = []

        self._push_undo(pre_snapshot, (x_min, x_max), f"Interpolate ({method}) -> {target_count} points")
        self._plot_curves()
        self.status_var.set(f"Applied {method} interpolation to all curves, resampled to {target_count} points.")

    def save_csv(self):
        if not self.curves:
            messagebox.showwarning("No data", "Load a CSV file first.")
            return

        initial_name = f"{Path(self.csv_path).stem}_edited.csv" if self.csv_path else "edited.csv"
        path = filedialog.asksaveasfilename(
            title="Save edited CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            initialfile=initial_name,
        )
        if not path:
            return

        try:
            write_csv_curves(
                path,
                self.x_values,
                self.curves,
                self.x_header,
                include_header=self.include_header_var.get(),
            )
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))
            return

        self.status_var.set(f"Saved to {path}")
        messagebox.showinfo("Saved", f"Saved the edited CSV to:\n{path}")


def main():
    app = CsvWaveformEditorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
