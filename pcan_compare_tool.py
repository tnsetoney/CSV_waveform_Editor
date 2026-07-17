#!/usr/bin/env python3
"""Real-time PEAK PCAN two-channel frame comparison tool.

Opens two PEAK-System CAN (PCAN) channels and compares the frames received
on each against each other in real time. Frames are matched per CAN ID in
arrival order (a small FIFO per ID per channel): when a frame with a given
ID shows up on one channel, it is compared against the oldest still-waiting
frame with the same ID from the other channel. If no counterpart arrives
within the match timeout, the frame is reported as "unmatched" (seen on
only one channel).

Requires python-can (`pip install python-can`) and the PEAK PCAN-Basic
driver installed on the host.
"""

import queue
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, replace
from tkinter import messagebox, ttk

try:
    import can
    CAN_AVAILABLE = True
except ImportError:
    CAN_AVAILABLE = False

# Fallback channel names offered if hardware auto-detection is unavailable.
COMMON_CHANNELS = [f"PCAN_USBBUS{i}" for i in range(1, 9)] + [f"PCAN_PCIBUS{i}" for i in range(1, 9)]
COMMON_BITRATES = [1000000, 800000, 500000, 250000, 125000, 100000, 50000, 20000, 10000]

DEFAULT_MATCH_TIMEOUT_S = 1.0
POLL_INTERVAL_MS = 150
MAX_TABLE_ROWS = 500
MAX_DRAIN_PER_POLL = 300


@dataclass
class ChannelStats:
    frame_count: int = 0
    error_count: int = 0
    matched: int = 0
    mismatched: int = 0
    unmatched: int = 0  # frames on this channel with no counterpart before timeout


class CanChannelReader(threading.Thread):
    """Background thread that continuously reads frames from one PCAN channel."""

    def __init__(self, label, channel, bitrate, on_message, on_error, on_opened=None):
        super().__init__(daemon=True)
        self.label = label
        self.channel = channel
        self.bitrate = bitrate
        self.on_message = on_message
        self.on_error = on_error
        self.on_opened = on_opened
        self._stop_event = threading.Event()
        self._opened_event = threading.Event()
        self.bus = None

    def wait_until_opened(self, timeout=5.0):
        """Block until this channel has finished trying to open (success or failure)."""
        return self._opened_event.wait(timeout=timeout)

    def run(self):
        try:
            self.bus = can.Bus(interface="pcan", channel=self.channel, bitrate=self.bitrate)
        except Exception as exc:
            self.on_error(self.label, f"Failed to open {self.channel}: {exc}")
            self._opened_event.set()
            return

        self._opened_event.set()
        if self.on_opened:
            self.on_opened(self.label)

        while not self._stop_event.is_set():
            try:
                msg = self.bus.recv(timeout=0.5)
            except Exception as exc:
                self.on_error(self.label, f"Receive error on {self.channel}: {exc}")
                time.sleep(0.2)
                continue
            if msg is None:
                continue
            self.on_message(self.label, msg)

        try:
            self.bus.shutdown()
        except Exception:
            pass

    def stop(self):
        self._stop_event.set()


class CompareEngine:
    """Matches frames from two channels by CAN ID and tracks running stats."""

    def __init__(self, label_a, label_b, result_queue, match_timeout=DEFAULT_MATCH_TIMEOUT_S):
        self.label_a = label_a
        self.label_b = label_b
        self.result_queue = result_queue
        self.match_timeout = match_timeout
        self._lock = threading.Lock()
        self._pending = {label_a: {}, label_b: {}}  # label -> {arb_id: deque[(ts, msg)]}
        self.stats = {label_a: ChannelStats(), label_b: ChannelStats()}
        self._other = {label_a: label_b, label_b: label_a}

    def on_message(self, label, msg):
        if getattr(msg, "is_error_frame", False):
            with self._lock:
                self.stats[label].error_count += 1
            return

        now = time.monotonic()
        arb_id = msg.arbitration_id
        other_label = self._other[label]

        with self._lock:
            self.stats[label].frame_count += 1
            other_queue = self._pending[other_label].get(arb_id)
            if other_queue:
                other_ts, other_msg = other_queue.popleft()
                if not other_queue:
                    del self._pending[other_label][arb_id]

                if label == self.label_a:
                    a_msg, b_msg = msg, other_msg
                else:
                    a_msg, b_msg = other_msg, msg

                is_match = bytes(a_msg.data) == bytes(b_msg.data) and a_msg.dlc == b_msg.dlc
                if is_match:
                    self.stats[label].matched += 1
                    self.stats[other_label].matched += 1
                else:
                    self.stats[label].mismatched += 1
                    self.stats[other_label].mismatched += 1

                result = {
                    "kind": "match" if is_match else "mismatch",
                    "id": arb_id,
                    "a_data": bytes(a_msg.data),
                    "b_data": bytes(b_msg.data),
                    "dt_ms": abs(now - other_ts) * 1000.0,
                    "timestamp": time.strftime("%H:%M:%S"),
                }
            else:
                self._pending[label].setdefault(arb_id, deque()).append((now, msg))
                result = None

        if result is not None:
            self.result_queue.put(result)

    def sweep_timeouts(self):
        """Move any frames that have waited too long for a counterpart into 'unmatched'."""
        now = time.monotonic()
        results = []
        with self._lock:
            for label, id_map in self._pending.items():
                for arb_id in list(id_map.keys()):
                    dq = id_map[arb_id]
                    while dq and (now - dq[0][0]) > self.match_timeout:
                        _ts, msg = dq.popleft()
                        self.stats[label].unmatched += 1
                        results.append(
                            {
                                "kind": "unmatched",
                                "id": arb_id,
                                "channel": label,
                                "data": bytes(msg.data),
                                "timestamp": time.strftime("%H:%M:%S"),
                            }
                        )
                    if not dq:
                        del id_map[arb_id]
        for r in results:
            self.result_queue.put(r)

    def get_stats_snapshot(self):
        with self._lock:
            return {label: replace(stats) for label, stats in self.stats.items()}


class PcanCompareApp(tk.Tk):
    LABEL_A = "A"
    LABEL_B = "B"

    def __init__(self):
        super().__init__()
        self.title("PEAK CAN Channel Comparison Tool")
        self.geometry("1150x720")
        self.minsize(950, 620)

        self.reader_a = None
        self.reader_b = None
        self.engine = None
        self.result_queue = queue.Queue()
        self._poll_after_id = None
        self._channel_a_display = tk.StringVar(value="A")
        self._channel_b_display = tk.StringVar(value="B")

        self.channel_a_var = tk.StringVar()
        self.channel_b_var = tk.StringVar()
        self.bitrate_a_var = tk.StringVar(value="500000")
        self.bitrate_b_var = tk.StringVar(value="500000")
        self.match_timeout_var = tk.StringVar(value=str(DEFAULT_MATCH_TIMEOUT_S))
        self.show_matches_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_channels()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _ui_call(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    def _build_ui(self):
        conn_frame = ttk.LabelFrame(self, text="Channels", padding=10)
        conn_frame.pack(fill=tk.X, padx=10, pady=(10, 6))

        ttk.Label(conn_frame, text="Channel A:").grid(row=0, column=0, padx=(0, 6), pady=4, sticky=tk.W)
        self.channel_a_combo = ttk.Combobox(conn_frame, textvariable=self.channel_a_var, width=22)
        self.channel_a_combo.grid(row=0, column=1, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(conn_frame, text="Bitrate A:").grid(row=0, column=2, padx=(0, 6), pady=4, sticky=tk.W)
        self.bitrate_a_combo = ttk.Combobox(
            conn_frame, textvariable=self.bitrate_a_var, values=COMMON_BITRATES, width=10
        )
        self.bitrate_a_combo.grid(row=0, column=3, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(conn_frame, text="Channel B:").grid(row=1, column=0, padx=(0, 6), pady=4, sticky=tk.W)
        self.channel_b_combo = ttk.Combobox(conn_frame, textvariable=self.channel_b_var, width=22)
        self.channel_b_combo.grid(row=1, column=1, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(conn_frame, text="Bitrate B:").grid(row=1, column=2, padx=(0, 6), pady=4, sticky=tk.W)
        self.bitrate_b_combo = ttk.Combobox(
            conn_frame, textvariable=self.bitrate_b_var, values=COMMON_BITRATES, width=10
        )
        self.bitrate_b_combo.grid(row=1, column=3, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(conn_frame, text="Match timeout (s):").grid(row=0, column=4, padx=(0, 6), pady=4, sticky=tk.W)
        ttk.Entry(conn_frame, textvariable=self.match_timeout_var, width=8).grid(
            row=0, column=5, padx=(0, 16), pady=4, sticky=tk.W
        )

        ttk.Button(conn_frame, text="Refresh Channels", command=self.refresh_channels).grid(
            row=1, column=4, columnspan=2, padx=(0, 0), pady=4, sticky=tk.W
        )

        actions = ttk.Frame(self, padding=(10, 0))
        actions.pack(fill=tk.X)
        self.start_button = ttk.Button(actions, text="Start", command=self.start_capture)
        self.start_button.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="Stop", command=self.stop_capture, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Reset Stats", command=self.reset_stats).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(actions, text="Show matched frames", variable=self.show_matches_var).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.status_var = tk.StringVar(value="Idle. Select channels and bitrates, then click Start.")
        ttk.Label(actions, textvariable=self.status_var).pack(side=tk.LEFT, padx=(16, 0))

        stats_frame = ttk.LabelFrame(self, text="Statistics", padding=10)
        stats_frame.pack(fill=tk.X, padx=10, pady=6)

        self.stats_labels = {}
        headers = ["Channel", "Frames", "Matched", "Mismatched", "Unmatched", "Errors"]
        for col, text in enumerate(headers):
            ttk.Label(stats_frame, text=text, font=("TkDefaultFont", 9, "bold")).grid(
                row=0, column=col, padx=10, sticky=tk.W
            )
        for row, label in enumerate((self.LABEL_A, self.LABEL_B), start=1):
            name_var = tk.StringVar(value=label)
            self.stats_labels[label] = {
                "name": name_var,
                "frames": tk.StringVar(value="0"),
                "matched": tk.StringVar(value="0"),
                "mismatched": tk.StringVar(value="0"),
                "unmatched": tk.StringVar(value="0"),
                "errors": tk.StringVar(value="0"),
            }
            ttk.Label(stats_frame, textvariable=name_var).grid(row=row, column=0, padx=10, sticky=tk.W)
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["frames"]).grid(
                row=row, column=1, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["matched"]).grid(
                row=row, column=2, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["mismatched"]).grid(
                row=row, column=3, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["unmatched"]).grid(
                row=row, column=4, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["errors"]).grid(
                row=row, column=5, padx=10, sticky=tk.W
            )

        self.match_rate_var = tk.StringVar(value="Match rate: -")
        ttk.Label(stats_frame, textvariable=self.match_rate_var, font=("TkDefaultFont", 9, "bold")).grid(
            row=3, column=0, columnspan=6, padx=10, pady=(8, 0), sticky=tk.W
        )

        table_frame = ttk.LabelFrame(self, text="Live comparison results", padding=6)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        columns = ("time", "id", "a_data", "b_data", "result", "dt")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        self.tree.heading("time", text="Time")
        self.tree.heading("id", text="CAN ID")
        self.tree.heading("a_data", text="Channel A Data")
        self.tree.heading("b_data", text="Channel B Data")
        self.tree.heading("result", text="Result")
        self.tree.heading("dt", text="\u0394t (ms)")
        self.tree.column("time", width=90, anchor=tk.W)
        self.tree.column("id", width=90, anchor=tk.W)
        self.tree.column("a_data", width=260, anchor=tk.W)
        self.tree.column("b_data", width=260, anchor=tk.W)
        self.tree.column("result", width=180, anchor=tk.W)
        self.tree.column("dt", width=90, anchor=tk.E)
        self.tree.tag_configure("mismatch", background="#ffd6d6")
        self.tree.tag_configure("unmatched", background="#fff3cd")
        self.tree.tag_configure("match", background="")

        vsb = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_channels(self):
        detected = []
        if CAN_AVAILABLE:
            try:
                configs = can.detect_available_configs(interfaces=["pcan"])
                detected = [c["channel"] for c in configs]
            except Exception:
                detected = []

        values = detected if detected else COMMON_CHANNELS
        self.channel_a_combo["values"] = values
        self.channel_b_combo["values"] = values
        if not self.channel_a_var.get() and values:
            self.channel_a_var.set(values[0])
        if not self.channel_b_var.get():
            self.channel_b_var.set(values[1] if len(values) > 1 else (values[0] if values else ""))

        if detected:
            self.status_var.set(f"Detected {len(detected)} PCAN channel(s): {', '.join(detected)}")
        else:
            self.status_var.set("No PCAN channels auto-detected; showing common channel names.")

    def start_capture(self):
        if not CAN_AVAILABLE:
            messagebox.showerror("python-can missing", "Install python-can: python -m pip install python-can")
            return

        channel_a = self.channel_a_var.get().strip()
        channel_b = self.channel_b_var.get().strip()
        if not channel_a or not channel_b:
            messagebox.showwarning("Missing channel", "Select a channel for both A and B.")
            return
        if channel_a == channel_b:
            messagebox.showwarning("Same channel", "Channel A and Channel B must be different.")
            return

        try:
            bitrate_a = int(self.bitrate_a_var.get())
            bitrate_b = int(self.bitrate_b_var.get())
        except ValueError:
            messagebox.showerror("Invalid bitrate", "Bitrates must be integers (bits per second).")
            return

        try:
            match_timeout = float(self.match_timeout_var.get())
        except ValueError:
            messagebox.showerror("Invalid timeout", "Match timeout must be a number of seconds.")
            return

        self._channel_a_display.set(channel_a)
        self._channel_b_display.set(channel_b)
        self.stats_labels[self.LABEL_A]["name"].set(f"A ({channel_a})")
        self.stats_labels[self.LABEL_B]["name"].set(f"B ({channel_b})")
        self.tree.heading("a_data", text=f"Channel A Data ({channel_a})")
        self.tree.heading("b_data", text=f"Channel B Data ({channel_b})")

        self.result_queue = queue.Queue()
        self.engine = CompareEngine(self.LABEL_A, self.LABEL_B, self.result_queue, match_timeout=match_timeout)

        self.reader_a = CanChannelReader(
            self.LABEL_A, channel_a, bitrate_a, self._on_message, self._on_reader_error
        )
        self.reader_b = CanChannelReader(
            self.LABEL_B, channel_b, bitrate_b, self._on_message, self._on_reader_error
        )
        # Two channels on the same multi-channel PCAN device can race if
        # opened concurrently; wait for A to finish opening before starting B.
        self.reader_a.start()
        self.reader_a.wait_until_opened(timeout=5.0)
        self.reader_b.start()
        self.reader_b.wait_until_opened(timeout=5.0)

        for widget in (
            self.channel_a_combo,
            self.channel_b_combo,
            self.bitrate_a_combo,
            self.bitrate_b_combo,
        ):
            widget.configure(state=tk.DISABLED)
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
        self.status_var.set(f"Capturing on {channel_a} (A) and {channel_b} (B)...")

        self._poll_after_id = self.after(POLL_INTERVAL_MS, self._poll_results)

    def stop_capture(self):
        if self.reader_a:
            self.reader_a.stop()
            self.reader_a = None
        if self.reader_b:
            self.reader_b.stop()
            self.reader_b = None
        if self._poll_after_id is not None:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None

        for widget in (
            self.channel_a_combo,
            self.channel_b_combo,
            self.bitrate_a_combo,
            self.bitrate_b_combo,
        ):
            widget.configure(state=tk.NORMAL)
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.status_var.set("Stopped.")

    def reset_stats(self):
        if self.engine is not None:
            self.engine = CompareEngine(
                self.LABEL_A, self.LABEL_B, self.result_queue, match_timeout=self.engine.match_timeout
            )
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._refresh_stats_labels()

    def _on_message(self, label, msg):
        if self.engine is not None:
            self.engine.on_message(label, msg)

    def _on_reader_error(self, label, message):
        self._ui_call(self.status_var.set, f"[{label}] {message}")

    def _poll_results(self):
        if self.engine is not None:
            self.engine.sweep_timeouts()
            drained = 0
            while drained < MAX_DRAIN_PER_POLL:
                try:
                    item = self.result_queue.get_nowait()
                except queue.Empty:
                    break
                self._append_result_row(item)
                drained += 1
            self._refresh_stats_labels()

        self._poll_after_id = self.after(POLL_INTERVAL_MS, self._poll_results)

    def _append_result_row(self, item):
        kind = item["kind"]
        if kind == "match" and not self.show_matches_var.get():
            return

        can_id = f"0x{item['id']:X}"
        if kind == "unmatched":
            data_hex = item["data"].hex(" ").upper()
            if item["channel"] == self.LABEL_A:
                a_data, b_data = data_hex, "-"
                result_text = "Unmatched (A only)"
            else:
                a_data, b_data = "-", data_hex
                result_text = "Unmatched (B only)"
            dt_text = "-"
        else:
            a_data = item["a_data"].hex(" ").upper()
            b_data = item["b_data"].hex(" ").upper()
            result_text = "Match" if kind == "match" else "MISMATCH"
            dt_text = f"{item['dt_ms']:.1f}"

        self.tree.insert(
            "",
            tk.END,
            values=(item["timestamp"], can_id, a_data, b_data, result_text, dt_text),
            tags=(kind,),
        )

        children = self.tree.get_children()
        if len(children) > MAX_TABLE_ROWS:
            for old_item in children[: len(children) - MAX_TABLE_ROWS]:
                self.tree.delete(old_item)

    def _refresh_stats_labels(self):
        if self.engine is None:
            return
        snapshot = self.engine.get_stats_snapshot()
        for label in (self.LABEL_A, self.LABEL_B):
            stats = snapshot[label]
            widgets = self.stats_labels[label]
            widgets["frames"].set(str(stats.frame_count))
            widgets["matched"].set(str(stats.matched))
            widgets["mismatched"].set(str(stats.mismatched))
            widgets["unmatched"].set(str(stats.unmatched))
            widgets["errors"].set(str(stats.error_count))

        matched = snapshot[self.LABEL_A].matched
        mismatched = snapshot[self.LABEL_A].mismatched
        denom = matched + mismatched
        if denom > 0:
            rate = matched / denom * 100.0
            self.match_rate_var.set(f"Match rate: {rate:.2f}% ({matched}/{denom} compared pairs)")
        else:
            self.match_rate_var.set("Match rate: - (no compared pairs yet)")

    def _on_close(self):
        self.stop_capture()
        self.destroy()


def main():
    app = PcanCompareApp()
    app.mainloop()


if __name__ == "__main__":
    main()
