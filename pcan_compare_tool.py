#!/usr/bin/env python3
"""Real-time PEAK PCAN two-channel frame comparison tool.

Opens two PEAK-System CAN (PCAN) channels and compares the frames received
on each against each other in real time. Frames are matched per CAN ID in
arrival order (a small FIFO per ID per channel): when a frame with a given
ID shows up on one channel, it is compared against the oldest still-waiting
frame with the same ID from the other channel. If no counterpart arrives
within the match timeout, the frame is reported as "unmatched" (seen on
only one channel).

Optionally, a third "Channel C" can play back a CAN trace CSV (the same
format as the bundled "Volvo ECU plaintext ... .csv" export: Time Stamp,
ID, Extended, Dir, Bus, LEN, D1..D8) onto the bus. Every frame it sends is
recorded as an "expected" frame; when channel A or B subsequently receives
a frame with that ID, it is compared against the expected data too, so the
tool reports not only whether A and B agree with each other, but whether
each of them also agrees with what was actually sent.

Requires python-can (`pip install python-can`) and the PEAK PCAN-Basic
driver installed on the host.
"""

import csv
import queue
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

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
    sent_matched: int = 0  # received frame matched what Channel C sent
    sent_mismatched: int = 0  # received frame differed from what Channel C sent
    sent_missing: int = 0  # Channel C sent a frame this channel never received


@dataclass
class ExpectedEntry:
    """One frame transmitted by Channel C, awaiting confirmation from A and/or B."""

    ts: float
    data: bytes
    dlc: int
    pending: set = field(default_factory=set)


def load_can_trace_csv(path):
    """Load a PCAN-trace-style CSV for playback on the send/reference channel.

    Expected columns (as in the bundled "Volvo ECU plaintext ... .csv"):
    Time Stamp, ID, Extended, Dir, Bus, LEN, D1..D8. The Time Stamp column is
    assumed to be in microseconds (this matches the ~10ms cyclic message
    periods seen in the sample file).

    Returns a list of dicts: {"delay_s", "arbitration_id", "is_extended_id", "data"}
    where delay_s is how long to wait after the previous frame before sending
    this one (0.0 for the first frame).
    """
    frames = []
    prev_ts = None
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts = float(row["Time Stamp"])
                arb_id = int(row["ID"], 16)
                is_extended = row.get("Extended", "").strip().lower() == "true"
                length = int(row["LEN"])
                data = bytes(
                    int(row[f"D{i}"], 16)
                    for i in range(1, length + 1)
                    if row.get(f"D{i}", "").strip() != ""
                )
            except (KeyError, ValueError, TypeError):
                continue

            delay_s = 0.0 if prev_ts is None else max(0.0, (ts - prev_ts) / 1_000_000.0)
            prev_ts = ts
            frames.append(
                {
                    "delay_s": delay_s,
                    "arbitration_id": arb_id,
                    "is_extended_id": is_extended,
                    "data": data,
                }
            )

    if not frames:
        raise ValueError(f"No usable CAN frames parsed from {path}")
    return frames


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


class CanFrameSender(threading.Thread):
    """Background thread that plays back a list of CAN frames onto one PCAN channel.

    Used as the optional "Channel C" reference source: every frame it
    successfully sends is reported via on_sent(msg) so the comparison engine
    can check whether A and/or B subsequently receive the same content.
    """

    def __init__(
        self,
        channel,
        bitrate,
        frames,
        on_sent,
        on_error,
        on_opened=None,
        on_finished=None,
        speed=1.0,
        loop=False,
    ):
        super().__init__(daemon=True)
        self.channel = channel
        self.bitrate = bitrate
        self.frames = frames
        self.on_sent = on_sent
        self.on_error = on_error
        self.on_opened = on_opened
        self.on_finished = on_finished
        self.speed = speed if speed > 0 else 1.0
        self.loop = loop
        self._stop_event = threading.Event()
        self._opened_event = threading.Event()
        self.bus = None
        self.sent_count = 0

    def wait_until_opened(self, timeout=5.0):
        return self._opened_event.wait(timeout=timeout)

    def run(self):
        try:
            self.bus = can.Bus(interface="pcan", channel=self.channel, bitrate=self.bitrate)
        except Exception as exc:
            self.on_error("TX", f"Failed to open {self.channel}: {exc}")
            self._opened_event.set()
            return

        self._opened_event.set()
        if self.on_opened:
            self.on_opened("TX")

        try:
            while not self._stop_event.is_set():
                for frame in self.frames:
                    if self._stop_event.is_set():
                        break
                    delay = frame["delay_s"] / self.speed
                    if delay > 0 and self._stop_event.wait(timeout=delay):
                        break
                    msg = can.Message(
                        arbitration_id=frame["arbitration_id"],
                        data=frame["data"],
                        is_extended_id=frame["is_extended_id"],
                    )
                    try:
                        self.bus.send(msg)
                        self.sent_count += 1
                        self.on_sent(msg)
                    except Exception as exc:
                        self.on_error("TX", f"Send error: {exc}")
                if not self.loop:
                    break
        finally:
            try:
                self.bus.shutdown()
            except Exception:
                pass
            if self.on_finished:
                self.on_finished()

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
        self._expected = {}  # arb_id -> deque[ExpectedEntry] (frames sent by Channel C)
        self.stats = {label_a: ChannelStats(), label_b: ChannelStats()}
        self._other = {label_a: label_b, label_b: label_a}

    def on_sent(self, msg):
        """Record a frame transmitted by the send/reference channel (Channel C)."""
        now = time.monotonic()
        entry = ExpectedEntry(
            ts=now, data=bytes(msg.data), dlc=msg.dlc, pending={self.label_a, self.label_b}
        )
        with self._lock:
            self._expected.setdefault(msg.arbitration_id, deque()).append(entry)

    def on_message(self, label, msg):
        if getattr(msg, "is_error_frame", False):
            with self._lock:
                self.stats[label].error_count += 1
            return

        now = time.monotonic()
        arb_id = msg.arbitration_id
        other_label = self._other[label]
        results = []

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

                results.append(
                    {
                        "kind": "match" if is_match else "mismatch",
                        "id": arb_id,
                        "a_data": bytes(a_msg.data),
                        "b_data": bytes(b_msg.data),
                        "dt_ms": abs(now - other_ts) * 1000.0,
                        "timestamp": time.strftime("%H:%M:%S"),
                    }
                )
            else:
                self._pending[label].setdefault(arb_id, deque()).append((now, msg))

            # Sent-vs-received comparison: only produces results while Channel C
            # has an outstanding expectation for this ID that still needs `label`.
            dq = self._expected.get(arb_id)
            if dq:
                for entry in dq:
                    if label in entry.pending:
                        entry.pending.discard(label)
                        is_sent_match = bytes(msg.data) == entry.data and msg.dlc == entry.dlc
                        if is_sent_match:
                            self.stats[label].sent_matched += 1
                        else:
                            self.stats[label].sent_mismatched += 1
                        results.append(
                            {
                                "kind": "sent_match" if is_sent_match else "sent_mismatch",
                                "id": arb_id,
                                "channel": label,
                                "sent_data": entry.data,
                                "recv_data": bytes(msg.data),
                                "dt_ms": (now - entry.ts) * 1000.0,
                                "timestamp": time.strftime("%H:%M:%S"),
                            }
                        )
                        if not entry.pending:
                            dq.remove(entry)
                        break
                if not dq:
                    del self._expected[arb_id]

        for r in results:
            self.result_queue.put(r)

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

            for arb_id in list(self._expected.keys()):
                dq = self._expected[arb_id]
                still_pending = deque()
                for entry in dq:
                    if (now - entry.ts) > self.match_timeout:
                        for pending_label in entry.pending:
                            self.stats[pending_label].sent_missing += 1
                            results.append(
                                {
                                    "kind": "sent_missing",
                                    "id": arb_id,
                                    "channel": pending_label,
                                    "sent_data": entry.data,
                                    "timestamp": time.strftime("%H:%M:%S"),
                                }
                            )
                    else:
                        still_pending.append(entry)
                if still_pending:
                    self._expected[arb_id] = still_pending
                else:
                    del self._expected[arb_id]
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
        self.sender = None
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

        # Channel C: optional send/reference channel that plays back a CAN
        # trace CSV so A/B's received frames can be checked against it too.
        self.channel_c_var = tk.StringVar()
        self.bitrate_c_var = tk.StringVar(value="500000")
        self.send_frames = []
        self.send_file_var = tk.StringVar(value="No CSV loaded")
        self.loop_var = tk.BooleanVar(value=False)
        self.speed_var = tk.StringVar(value="1.0")
        self.sent_count_var = tk.StringVar(value="0")
        self._sent_count = 0

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

        send_frame = ttk.LabelFrame(self, text="Channel C (Send / Reference)", padding=10)
        send_frame.pack(fill=tk.X, padx=10, pady=(0, 6))

        ttk.Label(send_frame, text="Channel C:").grid(row=0, column=0, padx=(0, 6), pady=4, sticky=tk.W)
        self.channel_c_combo = ttk.Combobox(send_frame, textvariable=self.channel_c_var, width=22)
        self.channel_c_combo.grid(row=0, column=1, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(send_frame, text="Bitrate C:").grid(row=0, column=2, padx=(0, 6), pady=4, sticky=tk.W)
        self.bitrate_c_combo = ttk.Combobox(
            send_frame, textvariable=self.bitrate_c_var, values=COMMON_BITRATES, width=10
        )
        self.bitrate_c_combo.grid(row=0, column=3, padx=(0, 16), pady=4, sticky=tk.W)

        ttk.Label(send_frame, text="Speed:").grid(row=0, column=4, padx=(0, 6), pady=4, sticky=tk.W)
        ttk.Entry(send_frame, textvariable=self.speed_var, width=6).grid(
            row=0, column=5, padx=(0, 16), pady=4, sticky=tk.W
        )
        ttk.Checkbutton(send_frame, text="Loop", variable=self.loop_var).grid(
            row=0, column=6, padx=(0, 8), pady=4, sticky=tk.W
        )

        self.load_send_csv_button = ttk.Button(send_frame, text="Load CSV...", command=self.load_send_csv)
        self.load_send_csv_button.grid(row=1, column=0, padx=(0, 8), pady=4, sticky=tk.W)
        ttk.Label(send_frame, textvariable=self.send_file_var).grid(
            row=1, column=1, columnspan=3, padx=(0, 16), pady=4, sticky=tk.W
        )

        self.start_send_button = ttk.Button(send_frame, text="Start Sending", command=self.start_sending)
        self.start_send_button.grid(row=1, column=4, padx=(0, 8), pady=4, sticky=tk.W)
        self.stop_send_button = ttk.Button(
            send_frame, text="Stop Sending", command=self.stop_sending, state=tk.DISABLED
        )
        self.stop_send_button.grid(row=1, column=5, padx=(0, 8), pady=4, sticky=tk.W)
        ttk.Label(send_frame, text="Sent:").grid(row=1, column=6, padx=(8, 4), pady=4, sticky=tk.W)
        ttk.Label(send_frame, textvariable=self.sent_count_var).grid(row=1, column=7, pady=4, sticky=tk.W)

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
        headers = [
            "Channel",
            "Frames",
            "Matched",
            "Mismatched",
            "Unmatched",
            "Errors",
            "Sent OK",
            "Sent Mismatch",
            "Sent Missing",
        ]
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
                "sent_matched": tk.StringVar(value="0"),
                "sent_mismatched": tk.StringVar(value="0"),
                "sent_missing": tk.StringVar(value="0"),
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
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["sent_matched"]).grid(
                row=row, column=6, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["sent_mismatched"]).grid(
                row=row, column=7, padx=10, sticky=tk.W
            )
            ttk.Label(stats_frame, textvariable=self.stats_labels[label]["sent_missing"]).grid(
                row=row, column=8, padx=10, sticky=tk.W
            )

        self.match_rate_var = tk.StringVar(value="Match rate: -")
        ttk.Label(stats_frame, textvariable=self.match_rate_var, font=("TkDefaultFont", 9, "bold")).grid(
            row=3, column=0, columnspan=9, padx=10, pady=(8, 0), sticky=tk.W
        )

        table_frame = ttk.LabelFrame(self, text="Live comparison results", padding=6)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        columns = ("time", "id", "sent_data", "a_data", "b_data", "result", "dt")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        self.tree.heading("time", text="Time")
        self.tree.heading("id", text="CAN ID")
        self.tree.heading("sent_data", text="Sent Data")
        self.tree.heading("a_data", text="Channel A Data")
        self.tree.heading("b_data", text="Channel B Data")
        self.tree.heading("result", text="Result")
        self.tree.heading("dt", text="\u0394t (ms)")
        self.tree.column("time", width=90, anchor=tk.W)
        self.tree.column("id", width=90, anchor=tk.W)
        self.tree.column("sent_data", width=200, anchor=tk.W)
        self.tree.column("a_data", width=200, anchor=tk.W)
        self.tree.column("b_data", width=200, anchor=tk.W)
        self.tree.column("result", width=190, anchor=tk.W)
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
        self.channel_c_combo["values"] = values
        if not self.channel_a_var.get() and values:
            self.channel_a_var.set(values[0])
        if not self.channel_b_var.get():
            self.channel_b_var.set(values[1] if len(values) > 1 else (values[0] if values else ""))
        if not self.channel_c_var.get() and len(values) > 2:
            self.channel_c_var.set(values[2])

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
        self.stop_sending()
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
        self._sent_count = 0
        self.sent_count_var.set("0")
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._refresh_stats_labels()

    def load_send_csv(self):
        path = filedialog.askopenfilename(
            title="Select CAN trace CSV to send",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            frames = load_can_trace_csv(path)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self.send_frames = frames
        self.send_file_var.set(f"{Path(path).name} ({len(frames)} frames)")
        self.status_var.set(f"Loaded {len(frames)} frame(s) to send from {Path(path).name}.")

    def start_sending(self):
        if not CAN_AVAILABLE:
            messagebox.showerror("python-can missing", "Install python-can: python -m pip install python-can")
            return
        if self.engine is None:
            messagebox.showwarning("Not capturing", "Start channel A/B capture first.")
            return
        if not self.send_frames:
            messagebox.showwarning("No CSV loaded", "Load a CAN trace CSV to send first.")
            return

        channel_c = self.channel_c_var.get().strip()
        if not channel_c:
            messagebox.showwarning("Missing channel", "Select a channel for sending.")
            return
        if channel_c in (self._channel_a_display.get(), self._channel_b_display.get()):
            messagebox.showwarning("Same channel", "Channel C must be different from Channel A and B.")
            return

        try:
            bitrate_c = int(self.bitrate_c_var.get())
        except ValueError:
            messagebox.showerror("Invalid bitrate", "Bitrate C must be an integer (bits per second).")
            return

        try:
            speed = float(self.speed_var.get())
            if speed <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid speed", "Speed must be a positive number.")
            return

        self.sender = CanFrameSender(
            channel_c,
            bitrate_c,
            self.send_frames,
            on_sent=self._on_sent,
            on_error=self._on_reader_error,
            on_finished=self._on_send_finished,
            speed=speed,
            loop=self.loop_var.get(),
        )
        self.sender.start()
        self.sender.wait_until_opened(timeout=5.0)

        self.channel_c_combo.configure(state=tk.DISABLED)
        self.bitrate_c_combo.configure(state=tk.DISABLED)
        self.load_send_csv_button.configure(state=tk.DISABLED)
        self.start_send_button.configure(state=tk.DISABLED)
        self.stop_send_button.configure(state=tk.NORMAL)
        self.status_var.set(f"Sending {len(self.send_frames)} frame(s) from {channel_c}...")

    def stop_sending(self):
        if self.sender:
            self.sender.stop()
            self.sender = None
        self.channel_c_combo.configure(state=tk.NORMAL)
        self.bitrate_c_combo.configure(state=tk.NORMAL)
        self.load_send_csv_button.configure(state=tk.NORMAL)
        self.start_send_button.configure(state=tk.NORMAL)
        self.stop_send_button.configure(state=tk.DISABLED)

    def _on_send_finished(self):
        self._ui_call(self._handle_send_finished)

    def _handle_send_finished(self):
        # Called when the sender thread completes on its own (non-loop mode).
        self.sender = None
        self.channel_c_combo.configure(state=tk.NORMAL)
        self.bitrate_c_combo.configure(state=tk.NORMAL)
        self.load_send_csv_button.configure(state=tk.NORMAL)
        self.start_send_button.configure(state=tk.NORMAL)
        self.stop_send_button.configure(state=tk.DISABLED)
        self.status_var.set("Finished sending CSV playback.")

    def _on_message(self, label, msg):
        if self.engine is not None:
            self.engine.on_message(label, msg)

    def _on_sent(self, msg):
        self._sent_count += 1
        self._ui_call(self.sent_count_var.set, str(self._sent_count))
        if self.engine is not None:
            self.engine.on_sent(msg)

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
        if kind in ("match", "sent_match") and not self.show_matches_var.get():
            return

        can_id = f"0x{item['id']:X}"

        if kind == "unmatched":
            data_hex = item["data"].hex(" ").upper()
            sent_data = "-"
            if item["channel"] == self.LABEL_A:
                a_data, b_data = data_hex, "-"
                result_text = "Unmatched (A only)"
            else:
                a_data, b_data = "-", data_hex
                result_text = "Unmatched (B only)"
            dt_text = "-"
        elif kind in ("match", "mismatch"):
            sent_data = "-"
            a_data = item["a_data"].hex(" ").upper()
            b_data = item["b_data"].hex(" ").upper()
            result_text = "Match" if kind == "match" else "MISMATCH"
            dt_text = f"{item['dt_ms']:.1f}"
        elif kind in ("sent_match", "sent_mismatch"):
            sent_data = item["sent_data"].hex(" ").upper()
            recv_hex = item["recv_data"].hex(" ").upper()
            if item["channel"] == self.LABEL_A:
                a_data, b_data = recv_hex, "-"
            else:
                a_data, b_data = "-", recv_hex
            outcome = "Match" if kind == "sent_match" else "MISMATCH"
            result_text = f"Sent\u2192{item['channel']} {outcome}"
            dt_text = f"{item['dt_ms']:.1f}"
        elif kind == "sent_missing":
            sent_data = item["sent_data"].hex(" ").upper()
            a_data = b_data = "-"
            result_text = f"Sent\u2192{item['channel']} Missing"
            dt_text = "-"
        else:
            return

        if kind in ("mismatch", "sent_mismatch"):
            tag = "mismatch"
        elif kind in ("unmatched", "sent_missing"):
            tag = "unmatched"
        else:
            tag = "match"

        self.tree.insert(
            "",
            tk.END,
            values=(item["timestamp"], can_id, sent_data, a_data, b_data, result_text, dt_text),
            tags=(tag,),
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
            widgets["sent_matched"].set(str(stats.sent_matched))
            widgets["sent_mismatched"].set(str(stats.sent_mismatched))
            widgets["sent_missing"].set(str(stats.sent_missing))

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
