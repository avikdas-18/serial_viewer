# grid_serial_text_colored_connect.py
# Reads one value at a time from a serial port and displays them in a 20x10 grid with color coding.
# Now includes UI controls to edit COM port and baud rate, and Connect/Disconnect/Refresh actions.

import threading
import queue
import time
import serial
import serial.tools.list_ports
import tkinter as tk
from tkinter import ttk

# ---------------- Configuration ----------------
DEFAULT_PORT = "COM8"   # starting value in the Port field
DEFAULT_BAUD = 115200   # starting value in the Baud field
ROWS = 20
COLS = 10
TOTAL_CELLS = ROWS * COLS
TEXT_MODE = False       # True: ASCII like "57\n"; False: raw 8-bit bytes 0–255
# ------------------------------------------------

def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

class SerialReader(threading.Thread):
    def __init__(self, port, baud, out_q, text_mode=True):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.out_q = out_q
        self.text_mode = text_mode
        self._stop = threading.Event()
        self.ser = None

    def stop(self):
        self._stop.set()
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def run(self):
        try:
            self.ser = serial.Serial(self.port, baudrate=self.baud, timeout=1)
            self.out_q.put(("__STATUS__", f"Connected: {self.port} @ {self.baud} ({'text' if self.text_mode else 'raw 8-bit'})"))
        except serial.SerialException as e:
            self.out_q.put(("__ERROR__", f"Open failed: {e}"))
            return

        while not self._stop.is_set():
            try:
                if self.text_mode:
                    line = self.ser.readline()
                    if not line:
                        continue
                    s = line.decode("ascii", errors="ignore").strip()
                    if not s:
                        continue
                    self.out_q.put(("value", s))
                else:
                    b = self.ser.read(1)
                    if not b:
                        continue
                    val = int(b[0])  # 0–255
                    self.out_q.put(("value", str(val)))
            except serial.SerialException as e:
                self.out_q.put(("__ERROR__", f"Read error: {e}"))
                break
            except Exception:
                # ignore sporadic parse errors
                continue

        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass
        self.out_q.put(("__STATUS__", "Disconnected"))

class GridApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Serial Grid (20x10) — Colored Values")

        self.queue = queue.Queue()
        self.labels = []
        self.index = 0
        self.reader = None

        self.last_value = tk.StringVar(value="—")
        self.status_var = tk.StringVar(value="Idle")

        # ---------- Controls (Port/Baud/Buttons) ----------
        controls = ttk.Frame(root, padding=6)
        controls.pack(fill="x")

        ttk.Label(controls, text="Port:").pack(side="left")
        self.port_var = tk.StringVar(value=DEFAULT_PORT)
        self.port_combo = ttk.Combobox(controls, textvariable=self.port_var, width=12, state="normal")
        self.port_combo.pack(side="left", padx=(4, 10))
        self.refresh_ports()  # populate initial list

        ttk.Label(controls, text="Baud:").pack(side="left")
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.baud_entry = ttk.Entry(controls, textvariable=self.baud_var, width=8)
        self.baud_entry.pack(side="left", padx=(4, 10))

        self.btn_connect = ttk.Button(controls, text="Connect", command=self.connect)
        self.btn_connect.pack(side="left", padx=2)
        self.btn_disconnect = ttk.Button(controls, text="Disconnect", command=self.disconnect)
        self.btn_disconnect.pack(side="left", padx=2)
        self.btn_refresh = ttk.Button(controls, text="Refresh Ports", command=self.refresh_ports)
        self.btn_refresh.pack(side="left", padx=8)

        ttk.Label(controls, textvariable=self.status_var).pack(side="left", padx=(12, 0))

        # ---------- Header ----------
        header = ttk.Frame(root, padding=6)
        header.pack(fill="x")
        ttk.Label(header, text="Last value:", font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.last_value).pack(side="left", padx=(6, 20))

        # ---------- Grid ----------
        grid_frame = ttk.Frame(root, padding=6)
        grid_frame.pack()

        # Use tk.Labels for easy background colors
        for r in range(ROWS):
            row_labels = []
            for c in range(COLS):
                lbl = tk.Label(grid_frame, text="", width=5, height=1,
                               relief="solid", bd=1, font=("Arial", 10), bg="white")
                lbl.grid(row=r, column=c, padx=1, pady=1, sticky="nsew")
                row_labels.append(lbl)
            self.labels.append(row_labels)

        # Schedule queue processing
        self.root.after(20, self.process_queue)

        # Try not to auto-connect; user can choose port/baud and press Connect

        # Close handler
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- Port UI helpers ----------
    def refresh_ports(self):
        ports = list_ports()
        self.port_combo["values"] = ports
        # keep current selection if present; else set first
        cur = self.port_var.get()
        if cur not in ports and ports:
            self.port_var.set(ports[0])

    # ---------- Serial connection controls ----------
    def connect(self):
        # If already connected, reconnect with new settings
        self.disconnect()

        port = self.port_var.get().strip()
        try:
            baud = int(self.baud_var.get().strip())
        except ValueError:
            self.status_var.set("Invalid baud rate")
            return

        if not port:
            self.status_var.set("Select/enter a port")
            return

        self.status_var.set(f"Connecting to {port} @ {baud} ...")
        self.reader = SerialReader(port, baud, self.queue, text_mode=TEXT_MODE)
        self.reader.start()

    def disconnect(self):
        if self.reader is not None:
            try:
                self.reader.stop()
            except Exception:
                pass
            self.reader = None
            self.status_var.set("Disconnected")

    # ---------- Grid + queue ----------
    def set_cell(self, idx, text_value):
        r = idx // COLS
        c = idx % COLS
        try:
            val = int(text_value)
        except ValueError:
            val = 0

        # Color rules
        if val < 20:
            color = "red"
        elif val < 60:
            color = "yellow"
        else:
            color = "green"

        self.labels[r][c].config(text=text_value, bg=color)

    def process_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "__ERROR__":
                    self.status_var.set(f"Error: {payload}")
                elif kind == "__STATUS__":
                    self.status_var.set(payload)
                elif kind == "value":
                    self.last_value.set(payload)
                    self.set_cell(self.index, payload)
                    self.index = (self.index + 1) % TOTAL_CELLS
        except queue.Empty:
            pass
        self.root.after(20, self.process_queue)

    # ---------- Misc ----------
    def on_close(self):
        self.disconnect()
        time.sleep(0.05)
        self.root.destroy()

def main():
    root = tk.Tk()
    app = GridApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
