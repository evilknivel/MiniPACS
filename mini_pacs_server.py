"""
MiniPACS Server - Single-file DICOM mini PACS with dark-mode tkinter GUI
Supports: MWL C-FIND, C-STORE, MPPS N-CREATE/N-SET, C-ECHO
"""

import argparse
import os
import sys
import threading
import time
import datetime
import queue
import tempfile
from collections import OrderedDict

# ---------------------------------------------------------------------------
# Dependency check
# ---------------------------------------------------------------------------
try:
    import pydicom
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.sequence import Sequence
    from pydicom.uid import generate_uid
except ImportError:
    print("ERROR: pydicom is not installed. Run: pip install pydicom")
    sys.exit(1)

try:
    import pynetdicom
    from pynetdicom import AE, evt, AllStoragePresentationContexts
    from pynetdicom.sop_class import (
        ModalityWorklistInformationFind,
        ModalityPerformedProcedureStep,
        Verification,
    )
except ImportError:
    print("ERROR: pynetdicom is not installed. Run: pip install pynetdicom")
    sys.exit(1)

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
worklist_lock = threading.Lock()
worklist_entries = []  # list of pydicom Dataset

mpps_lock = threading.Lock()
mpps_entries = OrderedDict()  # uid -> dict

received_files_lock = threading.Lock()
received_files = []  # list of dicts

log_queue = queue.Queue()
storage_dir = os.path.join(os.getcwd(), "received_dicom")

# Character set state
CHAR_SET_OPTIONS = [
    ("UTF-8 (empfohlen)", "ISO_IR 192"),
    ("Latin-1 – Westeuropa (ä ö ü)", "ISO_IR 100"),
    ("Latin-2 – Osteuropa", "ISO_IR 101"),
    ("Kyrillisch", "ISO_IR 144"),
    ("Arabisch", "ISO_IR 127"),
    ("Griechisch", "ISO_IR 126"),
    ("Türkisch", "ISO_IR 148"),
    ("Japanisch", "ISO 2022 IR 87"),
    ("Koreanisch", "ISO 2022 IR 149"),
    ("Chinesisch", "GB18030"),
    ("ASCII (Default)", ""),
]
CHAR_SET_DISPLAY = [c[0] for c in CHAR_SET_OPTIONS]
CHAR_SET_VALUES = {c[0]: c[1] for c in CHAR_SET_OPTIONS}
active_char_set = {"value": "ISO_IR 192"}  # mutable dict for thread safety

# Server handle
server_handle = {"ae": None, "running": False}

# Callbacks for GUI
gui_callbacks = {
    "on_store": None,
    "on_mpps": None,
}


def now_str():
    """Timestamp for entry/file records: 'YYYY-MM-DD HH:MM:SS'."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    full = f"[{ts}] {msg}"
    log_queue.put(full)
    print(full)


# ---------------------------------------------------------------------------
# Sample worklist entries
# ---------------------------------------------------------------------------
SAMPLE_WORKLIST = [
    {
        "PatientName": "Müller^Hans",
        "PatientID": "P-00001",
        "AccessionNumber": "ACC-001",
        "Modality": "CT",
        "Date": "20260415",
        "Time": "080000",
        "Description": "CT Thorax/Abdomen",
        "StationAETitle": "CT_SCANNER1",
        "Physician": "Dr. Schmidt",
    },
    {
        "PatientName": "Özdemir^Fatma",
        "PatientID": "P-00002",
        "AccessionNumber": "ACC-002",
        "Modality": "MR",
        "Date": "20260415",
        "Time": "090000",
        "Description": "MRT Schädel nativ",
        "StationAETitle": "MR_UNIT2",
        "Physician": "Dr. Weber",
    },
    {
        "PatientName": "Smith^John",
        "PatientID": "P-00003",
        "AccessionNumber": "ACC-003",
        "Modality": "XA",
        "Date": "20260415",
        "Time": "100000",
        "Description": "Angiography Coronary",
        "StationAETitle": "XA_ANGIO1",
        "Physician": "Dr. Meyer",
    },
    {
        "PatientName": "Иванов^Иван",
        "PatientID": "P-00004",
        "AccessionNumber": "ACC-004",
        "Modality": "US",
        "Date": "20260415",
        "Time": "110000",
        "Description": "Ultraschall Abdomen",
        "StationAETitle": "US_UNIT1",
        "Physician": "Dr. Fischer",
    },
    {
        "PatientName": "Dupont^Marie",
        "PatientID": "P-00005",
        "AccessionNumber": "ACC-005",
        "Modality": "CR",
        "Date": "20260415",
        "Time": "120000",
        "Description": "Röntgen Thorax",
        "StationAETitle": "CR_UNIT1",
        "Physician": "Dr. Braun",
    },
    {
        "PatientName": "Park^Ji-Yeon",
        "PatientID": "P-00006",
        "AccessionNumber": "ACC-006",
        "Modality": "NM",
        "Date": "20260415",
        "Time": "130000",
        "Description": "Nuclear Medicine Bone Scan",
        "StationAETitle": "NM_UNIT1",
        "Physician": "Dr. Wolf",
    },
]


def make_worklist_dataset(entry):
    ds = Dataset()
    cs = active_char_set["value"]
    if cs:
        ds.SpecificCharacterSet = cs
    ds.PatientName = entry.get("PatientName", "")
    ds.PatientID = entry.get("PatientID", "")

    sps = Dataset()
    sps.ScheduledStationAETitle = entry.get("StationAETitle", "")
    sps.ScheduledProcedureStepStartDate = entry.get("Date", "")
    sps.ScheduledProcedureStepStartTime = entry.get("Time", "")
    sps.Modality = entry.get("Modality", "")
    sps.ScheduledPerformingPhysicianName = entry.get("Physician", "")
    sps.ScheduledProcedureStepDescription = entry.get("Description", "")
    sps.ScheduledProcedureStepID = entry.get("AccessionNumber", "")
    ds.ScheduledProcedureStepSequence = Sequence([sps])

    ds.AccessionNumber = entry.get("AccessionNumber", "")
    ds.RequestedProcedureDescription = entry.get("Description", "")
    ds.RequestedProcedureID = entry.get("AccessionNumber", "")
    return ds


# ---------------------------------------------------------------------------
# DICOM handlers
# ---------------------------------------------------------------------------

def handle_echo(event):
    log("[ECHO] C-ECHO received")
    return 0x0000


def handle_find(event):
    """MWL C-FIND SCP handler."""
    identifier = event.identifier
    mod_filter = ""
    date_filter = ""

    if hasattr(identifier, "ScheduledProcedureStepSequence"):
        seq = identifier.ScheduledProcedureStepSequence
        if seq and len(seq) > 0:
            item = seq[0]
            if hasattr(item, "Modality") and item.Modality:
                mod_filter = str(item.Modality).strip()
            if hasattr(item, "ScheduledProcedureStepStartDate") and item.ScheduledProcedureStepStartDate:
                date_filter = str(item.ScheduledProcedureStepStartDate).strip()

    log(f"[MWL] C-FIND request – Modality={mod_filter or '*'} Date={date_filter or '*'}")

    with worklist_lock:
        entries = list(worklist_entries)

    mod_want = mod_filter.upper()
    for entry in entries:
        try:
            # Filter on the source entry before building a Dataset
            if mod_want and mod_want != str(entry.get("Modality", "")).strip().upper():
                continue
            if date_filter and date_filter != str(entry.get("Date", "")).strip():
                continue

            # make_worklist_dataset already applies the active character set
            yield (0xFF00, make_worklist_dataset(entry))
        except Exception as e:
            log(f"[MWL] Error building response: {e}")

    log("[MWL] C-FIND complete")


def handle_store(event):
    """C-STORE SCP handler."""
    try:
        ds = event.dataset
        ds.file_meta = event.file_meta
        sop_uid = str(ds.SOPInstanceUID) if hasattr(ds, 'SOPInstanceUID') else generate_uid()
        fname = f"{sop_uid}.dcm"
        os.makedirs(storage_dir, exist_ok=True)
        fpath = os.path.join(storage_dir, fname)

        pydicom.dcmwrite(fpath, ds)
        fsize = os.path.getsize(fpath)

        modality = str(ds.Modality) if hasattr(ds, 'Modality') else ""
        patient_name = str(ds.PatientName) if hasattr(ds, 'PatientName') else ""
        acc_no = str(ds.AccessionNumber) if hasattr(ds, 'AccessionNumber') else ""

        # Check character set mismatch
        rcv_cs = str(ds.SpecificCharacterSet) if hasattr(ds, 'SpecificCharacterSet') else ""
        srv_cs = active_char_set["value"]
        if rcv_cs and srv_cs and rcv_cs != srv_cs:
            log(f"[WARN] C-STORE SpecificCharacterSet mismatch: received {rcv_cs}, server configured {srv_cs}")

        log(f"[STORE] Received {fname} ({fsize} bytes) Modality={modality} Patient={patient_name}")

        file_info = {
            "filename": fname,
            "filepath": fpath,
            "size": fsize,
            "modality": modality,
            "patient_name": patient_name,
            "acc_no": acc_no,
            "received_at": now_str(),
        }
        with received_files_lock:
            received_files.append(file_info)

        if gui_callbacks["on_store"]:
            gui_callbacks["on_store"](file_info)

        return 0x0000
    except Exception as e:
        log(f"[STORE] Error: {e}")
        return 0xC001


def handle_n_create(event):
    """MPPS N-CREATE handler."""
    try:
        ds = event.attribute_list
        uid = str(event.affected_sop_instance_uid)

        patient_name = str(ds.PatientName) if hasattr(ds, 'PatientName') else ""
        acc_no = ""

        if hasattr(ds, 'ScheduledStepAttributesSequence') and ds.ScheduledStepAttributesSequence:
            item = ds.ScheduledStepAttributesSequence[0]
            acc_no = str(item.AccessionNumber) if hasattr(item, 'AccessionNumber') else ""

        # Check linking against the worklist
        with worklist_lock:
            linked = bool(acc_no) and any(
                e.get("AccessionNumber", "") == acc_no for e in worklist_entries
            )

        if linked:
            log(f"[MPPS] N-CREATE LINKED – AccNo {acc_no}")
        else:
            log(f"[MPPS] N-CREATE UNLINKED – no matching worklist entry (AccNo: {acc_no})")

        entry = {
            "uid": uid,
            "uid_short": uid[-12:] if len(uid) > 12 else uid,
            "patient_name": patient_name,
            "status": "IN PROGRESS",
            "acc_no": acc_no,
            "linked": linked,
            "start_time": now_str(),
            "end_time": "",
        }

        with mpps_lock:
            mpps_entries[uid] = entry

        if gui_callbacks["on_mpps"]:
            gui_callbacks["on_mpps"](entry)

        rsp = Dataset()
        rsp.AffectedSOPInstanceUID = uid
        return 0x0000, rsp
    except Exception as e:
        log(f"[MPPS] N-CREATE Error: {e}")
        return 0xC001, None


def handle_n_set(event):
    """MPPS N-SET handler."""
    try:
        ds = event.modification_list
        uid = str(event.requested_sop_instance_uid)

        status = ""
        if hasattr(ds, 'PerformedProcedureStepStatus'):
            status = str(ds.PerformedProcedureStepStatus).upper()

        with mpps_lock:
            if uid in mpps_entries:
                if status:
                    mpps_entries[uid]["status"] = status
                    if status in ("COMPLETED", "DISCONTINUED"):
                        mpps_entries[uid]["end_time"] = now_str()
                entry = mpps_entries[uid]
            else:
                entry = None

        if entry:
            log(f"[MPPS] N-SET uid=...{uid[-8:]} status={status}")
            if gui_callbacks["on_mpps"]:
                gui_callbacks["on_mpps"](entry)

        rsp = Dataset()
        rsp.AffectedSOPInstanceUID = uid
        return 0x0000, rsp
    except Exception as e:
        log(f"[MPPS] N-SET Error: {e}")
        return 0xC001, None


# ---------------------------------------------------------------------------
# Server start / stop
# ---------------------------------------------------------------------------

def start_server(ae_title, port):
    if server_handle["running"]:
        log("[SRV] Server already running")
        return False

    try:
        ae = AE(ae_title=ae_title)
        ae.maximum_pdu_size = 0

        # C-ECHO
        ae.add_supported_context(Verification)

        # MWL C-FIND
        ae.add_supported_context(ModalityWorklistInformationFind)

        # MPPS N-CREATE + N-SET
        ae.add_supported_context(ModalityPerformedProcedureStep)

        # C-STORE – all storage SOP classes
        for cx in AllStoragePresentationContexts:
            ae.add_supported_context(cx.abstract_syntax)

        handlers = [
            (evt.EVT_C_ECHO, handle_echo),
            (evt.EVT_C_FIND, handle_find),
            (evt.EVT_C_STORE, handle_store),
            (evt.EVT_N_CREATE, handle_n_create),
            (evt.EVT_N_SET, handle_n_set),
        ]

        cs = active_char_set["value"]
        log(f"[SRV] Starting AE={ae_title} Port={port}")
        log(f"[SRV] Character Set: {cs or 'ASCII (Default)'}")

        server = ae.start_server(
            ("0.0.0.0", int(port)),
            block=False,
            evt_handlers=handlers,
        )

        server_handle["ae"] = server
        server_handle["running"] = True
        log(f"[SRV] Server started successfully on port {port}")
        return True
    except Exception as e:
        log(f"[SRV] Failed to start: {e}")
        server_handle["running"] = False
        return False


def stop_server():
    if not server_handle["running"]:
        return
    try:
        if server_handle["ae"]:
            server_handle["ae"].shutdown()
        server_handle["ae"] = None
        server_handle["running"] = False
        log("[SRV] Server stopped")
    except Exception as e:
        log(f"[SRV] Error stopping: {e}")
        server_handle["running"] = False


# ---------------------------------------------------------------------------
# HEADLESS MODE
# ---------------------------------------------------------------------------

def run_headless():
    print("[MiniPACS] Headless mode – loading 2 sample worklist entries")
    with worklist_lock:
        for entry in SAMPLE_WORKLIST[:2]:
            worklist_entries.append(entry)

    started = start_server("MINIPACS", 11112)
    if not started:
        sys.exit(1)

    print("[MiniPACS] Press Ctrl+C to stop")
    try:
        while True:
            while not log_queue.empty():
                print(log_queue.get_nowait())
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[MiniPACS] Shutting down...")
        stop_server()
        sys.exit(0)


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

def run_gui():
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import ttk, filedialog, messagebox, scrolledtext
    import numpy as np

    # ---- Refined Dark Console palette ----
    BG = "#16171a"        # window
    BG2 = "#1e2023"       # panels / tree field
    BG3 = "#25272b"       # raised strips, inputs, buttons
    BORDER = "#34373d"    # input borders
    FG = "#d6d7da"        # body text
    FG2 = "#9a9da3"       # dim headings / labels
    DIM = "#7c7f85"       # faint captions
    ACCENT = "#e0a458"    # single warm accent
    ACCENT_DK = "#c98f43"
    GREEN = "#6bbf8a"
    RED = "#e06c6c"
    ORANGE = "#d9b877"
    YELLOW = "#dcdcaa"
    TREE_SEL = "#3d3524"  # accent-tinted selection
    TREE_ROW1 = "#1e2023"
    TREE_ROW2 = "#232529"

    root = tk.Tk()
    root.title("MiniPACS Server")
    root.configure(bg=BG)
    root.geometry("1280x820")
    root.minsize(900, 600)

    # ---- Fonts: prefer a real mono for data, fall back gracefully ----
    _fams = set(tkfont.families(root))

    def _pick(cands, default):
        return next((c for c in cands if c in _fams), default)

    MONO = _pick(["JetBrains Mono", "Cascadia Mono", "Cascadia Code",
                  "Consolas"], "Courier New")
    UIF = _pick(["Segoe UI Variable Text", "Segoe UI"], "TkDefaultFont")
    F_UI = (UIF, 9)
    F_H = (UIF, 10, "bold")
    F_MONO = (MONO, 9)
    F_MONO_SM = (MONO, 8)

    # Style
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure(".", background=BG, foreground=FG, fieldbackground=BG3,
                    troughcolor=BG3, bordercolor=BORDER, darkcolor=BG3,
                    lightcolor=BG3, selectbackground=TREE_SEL, selectforeground=FG,
                    font=F_UI)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=FG)
    style.configure("TButton", background=BG3, foreground=FG, relief="flat",
                    padding=5, borderwidth=0)
    style.map("TButton",
              background=[("active", BORDER), ("pressed", "#3a3d44")],
              foreground=[("active", "#ffffff")])
    style.configure("Accent.TButton", background=ACCENT, foreground=BG,
                    relief="flat", padding=5, borderwidth=0, font=(UIF, 9, "bold"))
    style.map("Accent.TButton",
              background=[("active", ACCENT_DK), ("pressed", ACCENT_DK)],
              foreground=[("active", BG)])
    style.configure("TEntry", fieldbackground=BG3, foreground=FG, insertcolor=FG,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("TCombobox", fieldbackground=BG3, foreground=FG,
                    selectbackground=BG3, selectforeground=FG,
                    background=BG3, arrowcolor=FG2, bordercolor=BORDER)
    style.map("TCombobox",
              fieldbackground=[("readonly", BG3)],
              foreground=[("readonly", FG)],
              selectbackground=[("readonly", BG3)])
    style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=[0, 0, 0, 0])
    style.configure("TNotebook.Tab", background=BG, foreground=DIM,
                    padding=[16, 8], borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", "#241f17"), ("active", BG2)],
              foreground=[("selected", ACCENT), ("active", FG)],
              bordercolor=[("selected", ACCENT)],
              lightcolor=[("selected", ACCENT)])
    style.configure("Treeview", background=BG2, foreground=FG,
                    fieldbackground=BG2, rowheight=24,
                    bordercolor=BORDER, font=F_MONO)
    style.configure("Treeview.Heading", background=BG2, foreground=FG2,
                    relief="flat", borderwidth=0, font=(UIF, 8, "bold"))
    style.map("Treeview",
              background=[("selected", TREE_SEL)],
              foreground=[("selected", "#ffffff")])
    style.configure("Vertical.TScrollbar", background=BG3, troughcolor=BG,
                    arrowcolor=FG2, bordercolor=BG3)
    style.configure("Horizontal.TScrollbar", background=BG3, troughcolor=BG,
                    arrowcolor=FG2, bordercolor=BG3)
    style.configure("Horizontal.TScale", background=ACCENT, troughcolor=BG3)
    style.configure("TLabelframe", background=BG, bordercolor=BORDER)
    style.configure("TLabelframe.Label", background=BG, foreground=FG2)

    # ---- Header ----
    header = tk.Frame(root, bg=BG2, height=54)
    header.pack(fill=tk.X, side=tk.TOP)
    header.pack_propagate(False)

    tk.Label(header, text="MiniPACS", fg="#f2f3f4", bg=BG2,
             font=(UIF, 12, "bold")).pack(side=tk.LEFT, padx=(18, 14), pady=8)

    status_pill = tk.Frame(header, bg=BG3)
    status_pill.pack(side=tk.LEFT, pady=12)
    status_dot = tk.Label(status_pill, text="●", fg=RED, bg=BG3,
                          font=(UIF, 9))
    status_dot.pack(side=tk.LEFT, padx=(9, 4), pady=3)
    status_txt = tk.Label(status_pill, text="STOPPED", fg=FG2, bg=BG3,
                          font=(UIF, 8, "bold"))
    status_txt.pack(side=tk.LEFT, padx=(0, 10), pady=3)

    header_info = tk.Label(header, text="AE  MINIPACS     PORT  11112     CS  ISO_IR 192",
                           fg=FG2, bg=BG2, font=(MONO, 9))
    header_info.pack(side=tk.LEFT, padx=16)

    btn_start = ttk.Button(header, text="Start Server", style="Accent.TButton")
    btn_stop = ttk.Button(header, text="Stop")
    btn_start.pack(side=tk.RIGHT, padx=(4, 18), pady=10)
    btn_stop.pack(side=tk.RIGHT, padx=4, pady=10)

    # ---- Main notebook ----
    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    # ===========================================================
    # TAB 1: Worklist
    # ===========================================================
    tab_wl = ttk.Frame(notebook)
    notebook.add(tab_wl, text="  Worklist  ")

    # Config row
    cfg_frame = tk.Frame(tab_wl, bg=BG3, padx=8, pady=6)
    cfg_frame.pack(fill=tk.X)

    tk.Label(cfg_frame, text="AE-Title:", bg=BG3, fg=FG).grid(row=0, column=0, padx=4)
    ae_var = tk.StringVar(value="MINIPACS")
    ae_entry = ttk.Entry(cfg_frame, textvariable=ae_var, width=14)
    ae_entry.grid(row=0, column=1, padx=4)

    tk.Label(cfg_frame, text="Port:", bg=BG3, fg=FG).grid(row=0, column=2, padx=4)
    port_var = tk.StringVar(value="11112")
    port_entry = ttk.Entry(cfg_frame, textvariable=port_var, width=7)
    port_entry.grid(row=0, column=3, padx=4)

    tk.Label(cfg_frame, text="Zeichensatz / Character Set:", bg=BG3, fg=FG).grid(row=0, column=4, padx=(12, 4))
    cs_var = tk.StringVar(value=CHAR_SET_DISPLAY[0])
    cs_combo = ttk.Combobox(cfg_frame, textvariable=cs_var, values=CHAR_SET_DISPLAY,
                            state="readonly", width=30)
    cs_combo.current(0)
    cs_combo.grid(row=0, column=5, padx=4)

    info_label = tk.Label(cfg_frame,
                          text="ℹ️ Port 104 requires admin rights – default 11112 is recommended",
                          bg=BG3, fg=ORANGE, font=("Segoe UI", 8))
    info_label.grid(row=1, column=0, columnspan=8, sticky="w", padx=4, pady=(2, 0))

    # Worklist form
    form_frame = tk.LabelFrame(tab_wl, text=" Add Worklist Entry ",
                               bg=BG, fg=FG2, padx=8, pady=6)
    form_frame.pack(fill=tk.X, padx=6, pady=4)

    wl_fields = {}
    field_defs = [
        ("PatientName", "Patient Name", 0, 0),
        ("PatientID", "Patient ID", 0, 2),
        ("AccessionNumber", "Accession No.", 0, 4),
        ("Modality", "Modality", 0, 6),
        ("Date", "Date (YYYYMMDD)", 1, 0),
        ("Time", "Time (HHMMSS)", 1, 2),
        ("Description", "Description", 1, 4),
        ("StationAETitle", "Station AE", 1, 6),
        ("Physician", "Physician", 2, 0),
    ]
    for key, label, row, col in field_defs:
        tk.Label(form_frame, text=label + ":", bg=BG, fg=FG,
                 font=("Segoe UI", 8)).grid(row=row, column=col, sticky="w", padx=4)
        var = tk.StringVar()
        e = ttk.Entry(form_frame, textvariable=var, width=16)
        e.grid(row=row, column=col + 1, padx=4, pady=2)
        wl_fields[key] = var

    btn_row = tk.Frame(form_frame, bg=BG)
    btn_row.grid(row=3, column=0, columnspan=8, pady=4, sticky="w")

    def add_worklist_entry():
        entry = {k: v.get().strip() for k, v in wl_fields.items()}
        if not entry["PatientName"] and not entry["PatientID"]:
            messagebox.showwarning("Input Error", "PatientName or PatientID required", parent=root)
            return
        with worklist_lock:
            worklist_entries.append(entry)
        log(f"[WL] Added entry: {entry['PatientName']} AccNo={entry['AccessionNumber']}")
        refresh_worklist_tree()
        for v in wl_fields.values():
            v.set("")

    def load_samples():
        with worklist_lock:
            for s in SAMPLE_WORKLIST:
                worklist_entries.append(dict(s))
        log("[WL] Loaded 6 sample entries")
        refresh_worklist_tree()

    ttk.Button(btn_row, text="+ Add Entry", command=add_worklist_entry).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_row, text="Load 6 Samples", command=load_samples).pack(side=tk.LEFT, padx=2)

    def delete_selected_wl():
        sel = wl_tree.selection()
        if not sel:
            return
        indices = sorted([wl_tree.index(s) for s in sel], reverse=True)
        with worklist_lock:
            for i in indices:
                if 0 <= i < len(worklist_entries):
                    del worklist_entries[i]
        log(f"[WL] Deleted {len(sel)} entry/entries")
        refresh_worklist_tree()

    def delete_all_wl():
        if messagebox.askyesno("Confirm", "Delete all worklist entries?", parent=root):
            with worklist_lock:
                worklist_entries.clear()
            log("[WL] Cleared all entries")
            refresh_worklist_tree()

    ttk.Button(btn_row, text="Delete Selected", command=delete_selected_wl).pack(side=tk.LEFT, padx=2)
    ttk.Button(btn_row, text="Delete All", command=delete_all_wl).pack(side=tk.LEFT, padx=2)

    # Worklist tree
    wl_cols = ["PatientName", "PatientID", "AccessionNumber", "Modality",
               "Date", "Time", "Description", "StationAETitle", "Physician"]
    wl_tree_frame = tk.Frame(tab_wl, bg=BG)
    wl_tree_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

    wl_vsb = ttk.Scrollbar(wl_tree_frame, orient="vertical")
    wl_hsb = ttk.Scrollbar(wl_tree_frame, orient="horizontal")
    wl_tree = ttk.Treeview(wl_tree_frame, columns=wl_cols, show="headings",
                           yscrollcommand=wl_vsb.set, xscrollcommand=wl_hsb.set,
                           style="Treeview")
    wl_vsb.config(command=wl_tree.yview)
    wl_hsb.config(command=wl_tree.xview)
    wl_vsb.pack(side=tk.RIGHT, fill=tk.Y)
    wl_hsb.pack(side=tk.BOTTOM, fill=tk.X)
    wl_tree.pack(fill=tk.BOTH, expand=True)

    col_widths = {"PatientName": 140, "PatientID": 90, "AccessionNumber": 100,
                  "Modality": 70, "Date": 90, "Time": 80, "Description": 180,
                  "StationAETitle": 110, "Physician": 120}
    for col in wl_cols:
        wl_tree.heading(col, text=col)
        wl_tree.column(col, width=col_widths.get(col, 100), minwidth=60)
    wl_tree.tag_configure("even", background=TREE_ROW1)
    wl_tree.tag_configure("odd", background=TREE_ROW2)

    def refresh_worklist_tree():
        wl_tree.delete(*wl_tree.get_children())
        with worklist_lock:
            for i, e in enumerate(worklist_entries):
                tag = "even" if i % 2 == 0 else "odd"
                wl_tree.insert("", "end", tag=tag,
                               values=[e.get(c, "") for c in wl_cols])

    # ===========================================================
    # TAB 2: MPPS
    # ===========================================================
    tab_mpps = ttk.Frame(notebook)
    notebook.add(tab_mpps, text="  MPPS  ")

    mpps_cols = ["UID", "PatientName", "Status", "Start", "End", "LinkStatus"]
    mpps_tree_frame = tk.Frame(tab_mpps, bg=BG)
    mpps_tree_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    mpps_vsb = ttk.Scrollbar(mpps_tree_frame, orient="vertical")
    mpps_tree = ttk.Treeview(mpps_tree_frame, columns=mpps_cols, show="headings",
                             yscrollcommand=mpps_vsb.set)
    mpps_vsb.config(command=mpps_tree.yview)
    mpps_vsb.pack(side=tk.RIGHT, fill=tk.Y)
    mpps_tree.pack(fill=tk.BOTH, expand=True)

    mpps_col_widths = {"UID": 140, "PatientName": 150, "Status": 110,
                       "Start": 150, "End": 150, "LinkStatus": 120}
    for col in mpps_cols:
        mpps_tree.heading(col, text=col)
        mpps_tree.column(col, width=mpps_col_widths.get(col, 100), minwidth=60)

    mpps_tree.tag_configure("linked", background="#1a3a2a")
    mpps_tree.tag_configure("unlinked", background="#3a2a1a")

    def refresh_mpps_tree():
        mpps_tree.delete(*mpps_tree.get_children())
        with mpps_lock:
            entries = list(mpps_entries.values())
        for e in entries:
            link_label = "🔗 Linked" if e.get("linked") else "⚠️ Unlinked"
            tag = "linked" if e.get("linked") else "unlinked"
            mpps_tree.insert("", "end", tag=tag, values=[
                "..." + e["uid_short"],
                e["patient_name"],
                e["status"],
                e["start_time"],
                e["end_time"],
                link_label,
            ])

    # ===========================================================
    # TAB 3: Received Files
    # ===========================================================
    tab_files = ttk.Frame(notebook)
    notebook.add(tab_files, text="  Received Files  ")

    files_cfg = tk.Frame(tab_files, bg=BG3, padx=8, pady=6)
    files_cfg.pack(fill=tk.X)

    tk.Label(files_cfg, text="Storage Directory:", bg=BG3, fg=FG).pack(side=tk.LEFT, padx=4)
    storage_dir_var = tk.StringVar(value=storage_dir)
    storage_entry = ttk.Entry(files_cfg, textvariable=storage_dir_var, width=50)
    storage_entry.pack(side=tk.LEFT, padx=4)

    def browse_storage():
        d = filedialog.askdirectory(parent=root, initialdir=storage_dir_var.get())
        if d:
            storage_dir_var.set(d)
            global storage_dir
            storage_dir = d
            log(f"[SRV] Storage dir changed to: {d}")

    ttk.Button(files_cfg, text="Browse...", command=browse_storage).pack(side=tk.LEFT, padx=4)

    files_cols = ["Filename", "Size (KB)", "Modality", "PatientName", "Received"]
    files_tree_frame = tk.Frame(tab_files, bg=BG)
    files_tree_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    files_vsb = ttk.Scrollbar(files_tree_frame, orient="vertical")
    files_tree = ttk.Treeview(files_tree_frame, columns=files_cols, show="headings",
                              yscrollcommand=files_vsb.set)
    files_vsb.config(command=files_tree.yview)
    files_vsb.pack(side=tk.RIGHT, fill=tk.Y)
    files_tree.pack(fill=tk.BOTH, expand=True)

    files_col_widths = {"Filename": 280, "Size (KB)": 80, "Modality": 80,
                        "PatientName": 180, "Received": 150}
    for col in files_cols:
        files_tree.heading(col, text=col)
        files_tree.column(col, width=files_col_widths.get(col, 100), minwidth=60)
    files_tree.tag_configure("even", background=TREE_ROW1)
    files_tree.tag_configure("odd", background=TREE_ROW2)

    def refresh_files_tree():
        files_tree.delete(*files_tree.get_children())
        with received_files_lock:
            for i, f in enumerate(received_files):
                tag = "even" if i % 2 == 0 else "odd"
                files_tree.insert("", "end", iid=f["filepath"], tag=tag, values=[
                    f["filename"],
                    f"{f['size'] / 1024:.1f}",
                    f["modality"],
                    f["patient_name"],
                    f["received_at"],
                ])

    # ===========================================================
    # TAB 4: DICOM Viewer
    # ===========================================================
    tab_viewer = ttk.Frame(notebook)
    notebook.add(tab_viewer, text="  DICOM Viewer  ")

    # Viewer state
    viewer_state = {
        "ds": None,
        "pixel_array": None,
        "n_frames": 1,
        "current_frame": 0,
        "playing": False,
        "fps": 10,
        "zoom": 1.0,
        "pan_x": 0,
        "pan_y": 0,
        "drag_start": None,
        "tk_image": None,
        "after_id": None,
        "wl_after_id": None,
        "filepath": None,
        "is_encapsulated_video": False,
    }

    # Windowing presets: (center, width)
    WL_PRESETS = {
        "Default": None,
        "Abdomen": (60, 400),
        "Lung": (-600, 1500),
        "Bone": (400, 1800),
        "Brain": (40, 80),
        "Angio": (300, 600),
    }

    viewer_top = tk.Frame(tab_viewer, bg=BG3, padx=6, pady=4)
    viewer_top.pack(fill=tk.X)

    def viewer_open_file():
        fp = filedialog.askopenfilename(
            parent=root, title="Open DICOM File",
            filetypes=[("DICOM files", "*.dcm"), ("All files", "*.*")]
        )
        if fp:
            load_dicom_file(fp)

    ttk.Button(viewer_top, text="Open File", command=viewer_open_file).pack(side=tk.LEFT, padx=2)
    ttk.Button(viewer_top, text="Fit to Window",
               command=lambda: viewer_fit_to_window()).pack(side=tk.LEFT, padx=2)
    ttk.Button(viewer_top, text="Reset Zoom",
               command=lambda: viewer_reset_zoom()).pack(side=tk.LEFT, padx=2)
    ttk.Button(viewer_top, text="Export PNG",
               command=lambda: viewer_export_png()).pack(side=tk.LEFT, padx=2)

    viewer_main = tk.Frame(tab_viewer, bg=BG)
    viewer_main.pack(fill=tk.BOTH, expand=True)

    # Canvas area
    canvas_frame = tk.Frame(viewer_main, bg="#000000")
    canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    viewer_canvas = tk.Canvas(canvas_frame, bg="#000000", highlightthickness=0)
    viewer_canvas.pack(fill=tk.BOTH, expand=True)

    # Metadata sidebar (collapsible)
    sidebar_visible = tk.BooleanVar(value=True)
    sidebar_frame = tk.Frame(viewer_main, bg=BG2, width=220)
    sidebar_frame.pack(side=tk.RIGHT, fill=tk.Y)
    sidebar_frame.pack_propagate(False)

    tk.Label(sidebar_frame, text="METADATA", bg=BG2, fg=FG2,
             font=(UIF, 8, "bold")).pack(anchor="w", padx=8, pady=6)

    meta_text = scrolledtext.ScrolledText(sidebar_frame, bg=BG2, fg="#b9bbc0",
                                          font=F_MONO_SM, insertbackground=FG,
                                          state="disabled", width=28,
                                          wrap=tk.WORD, relief="flat", bd=0)
    meta_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    def toggle_sidebar():
        if sidebar_visible.get():
            sidebar_frame.pack_forget()
            sidebar_visible.set(False)
        else:
            sidebar_frame.pack(side=tk.RIGHT, fill=tk.Y)
            sidebar_visible.set(True)

    ttk.Button(viewer_top, text="⊟ Meta", command=toggle_sidebar).pack(side=tk.RIGHT, padx=2)

    # Windowing controls
    wl_frame = tk.Frame(tab_viewer, bg=BG3, padx=6, pady=4)
    wl_frame.pack(fill=tk.X)

    tk.Label(wl_frame, text="WC:", bg=BG3, fg=FG).pack(side=tk.LEFT, padx=2)
    wc_var = tk.IntVar(value=128)
    wc_scale = ttk.Scale(wl_frame, from_=-1024, to=4096, variable=wc_var,
                         orient="horizontal", length=140)
    wc_scale.pack(side=tk.LEFT, padx=2)
    wc_lbl = tk.Label(wl_frame, textvariable=wc_var, bg=BG3, fg=FG, width=5)
    wc_lbl.pack(side=tk.LEFT)

    tk.Label(wl_frame, text="WW:", bg=BG3, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
    ww_var = tk.IntVar(value=256)
    ww_scale = ttk.Scale(wl_frame, from_=1, to=8000, variable=ww_var,
                         orient="horizontal", length=140)
    ww_scale.pack(side=tk.LEFT, padx=2)
    ww_lbl = tk.Label(wl_frame, textvariable=ww_var, bg=BG3, fg=FG, width=5)
    ww_lbl.pack(side=tk.LEFT)

    tk.Label(wl_frame, text="Preset:", bg=BG3, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
    preset_var = tk.StringVar(value="Default")
    preset_combo = ttk.Combobox(wl_frame, textvariable=preset_var,
                                values=list(WL_PRESETS.keys()),
                                state="readonly", width=10)
    preset_combo.pack(side=tk.LEFT, padx=2)

    ttk.Button(wl_frame, text="Auto WL",
               command=lambda: viewer_auto_wl()).pack(side=tk.LEFT, padx=4)

    # Multi-frame toolbar
    mf_frame = tk.Frame(tab_viewer, bg=BG3, padx=6, pady=4)
    mf_frame.pack(fill=tk.X)

    frame_label_var = tk.StringVar(value="Frame 1 / 1")
    tk.Label(mf_frame, textvariable=frame_label_var, bg=BG3, fg=FG2,
             font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=4)

    ttk.Button(mf_frame, text="⏮",
               command=lambda: viewer_goto_frame(0)).pack(side=tk.LEFT, padx=1)
    ttk.Button(mf_frame, text="⏪",
               command=lambda: viewer_prev_frame()).pack(side=tk.LEFT, padx=1)
    play_btn_var = tk.StringVar(value="⏯")
    ttk.Button(mf_frame, textvariable=play_btn_var,
               command=lambda: viewer_toggle_play()).pack(side=tk.LEFT, padx=1)
    ttk.Button(mf_frame, text="⏩",
               command=lambda: viewer_next_frame()).pack(side=tk.LEFT, padx=1)
    ttk.Button(mf_frame, text="⏭",
               command=lambda: viewer_goto_frame(-1)).pack(side=tk.LEFT, padx=1)

    tk.Label(mf_frame, text="FPS:", bg=BG3, fg=FG).pack(side=tk.LEFT, padx=(8, 2))
    fps_var = tk.IntVar(value=10)
    fps_scale = ttk.Scale(mf_frame, from_=1, to=30, variable=fps_var,
                          orient="horizontal", length=100)
    fps_scale.pack(side=tk.LEFT, padx=2)
    tk.Label(mf_frame, textvariable=fps_var, bg=BG3, fg=FG, width=3).pack(side=tk.LEFT)

    # Encapsulated video message
    enc_video_frame = tk.Frame(tab_viewer, bg=BG)
    enc_video_lbl = tk.Label(enc_video_frame,
                             text="⚠️ Encapsulated video (MPEG/HEVC) – native playback not supported.\nClick to open with system default player.",
                             bg=BG, fg=ORANGE, font=("Segoe UI", 11), justify="center")
    enc_video_lbl.pack(pady=20)

    def open_ext_video():
        ds = viewer_state["ds"]
        if ds is None:
            return
        try:
            raw = ds.PixelData
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(raw)
            tmp.close()
            os.startfile(tmp.name)
            log(f"[VIEWER] Opened video externally: {tmp.name}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not open video: {e}", parent=root)

    ttk.Button(enc_video_frame, text="Open externally",
               command=open_ext_video).pack(pady=4)

    # --- Viewer functions ---
    ENCAPSULATED_VIDEO_UIDS = {
        "1.2.840.10008.1.2.4.100",
        "1.2.840.10008.1.2.4.101",
        "1.2.840.10008.1.2.4.102",
        "1.2.840.10008.1.2.4.103",
        "1.2.840.10008.1.2.4.104",
        "1.2.840.10008.1.2.4.105",
        "1.2.840.10008.1.2.4.106",
    }

    def load_dicom_file(filepath):
        if not PIL_AVAILABLE:
            messagebox.showerror("Error", "Pillow is not installed. Cannot display images.", parent=root)
            return
        try:
            ds = pydicom.dcmread(filepath, force=True)
            viewer_state["ds"] = ds
            viewer_state["filepath"] = filepath
            viewer_state["current_frame"] = 0
            viewer_state["zoom"] = 1.0
            viewer_state["pan_x"] = 0
            viewer_state["pan_y"] = 0

            # Check for encapsulated video
            ts = ""
            if hasattr(ds, "file_meta") and hasattr(ds.file_meta, "TransferSyntaxUID"):
                ts = str(ds.file_meta.TransferSyntaxUID)
            viewer_state["is_encapsulated_video"] = ts in ENCAPSULATED_VIDEO_UIDS

            if viewer_state["is_encapsulated_video"]:
                enc_video_frame.pack(fill=tk.BOTH, expand=True)
                viewer_canvas.pack_forget()
                update_metadata_panel(ds)
                log(f"[VIEWER] Encapsulated video file: {filepath}")
                return
            else:
                enc_video_frame.pack_forget()
                viewer_canvas.pack(fill=tk.BOTH, expand=True)

            # Load pixel data
            try:
                px = ds.pixel_array
            except Exception:
                messagebox.showerror("Error", "Could not decode pixel data.", parent=root)
                return

            try:
                n_frames = int(getattr(ds, "NumberOfFrames", 1) or 1)
            except Exception:
                n_frames = 1
            # 3D array with a non-RGB last axis => multi-frame grayscale
            if n_frames == 1 and px.ndim == 3 and px.shape[2] not in (3, 4):
                n_frames = px.shape[0]

            viewer_state["pixel_array"] = px
            viewer_state["n_frames"] = n_frames

            # Auto WL
            viewer_auto_wl_from_array(px)

            update_metadata_panel(ds)
            viewer_render_frame()

            if n_frames > 1:
                mf_frame.pack(fill=tk.X)
            else:
                mf_frame.pack_forget()

            log(f"[VIEWER] Loaded: {os.path.basename(filepath)} Frames={n_frames}")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load DICOM file:\n{e}", parent=root)
            log(f"[VIEWER] Error loading {filepath}: {e}")

    def apply_windowing(arr_2d, wc, ww):
        """Apply window/level to a 2D array, return uint8."""
        lo = wc - ww / 2.0
        hi = wc + ww / 2.0
        arr = arr_2d.astype(float)
        arr = np.clip(arr, lo, hi)
        arr = ((arr - lo) / (hi - lo) * 255.0).astype("uint8")
        return arr

    def viewer_render_frame():
        ds = viewer_state["ds"]
        px = viewer_state["pixel_array"]
        if ds is None or px is None:
            return
        try:
            frame_idx = viewer_state["current_frame"]
            n_frames = viewer_state["n_frames"]

            frame_label_var.set(f"Frame {frame_idx + 1} / {n_frames}")

            # Extract frame
            if n_frames > 1:
                if len(px.shape) == 3 and px.shape[2] not in (3, 4):
                    frame = px[frame_idx]
                elif len(px.shape) == 4:
                    frame = px[frame_idx]
                else:
                    frame = px
            else:
                frame = px

            # Convert to PIL Image
            photo_interp = str(ds.PhotometricInterpretation) if hasattr(ds, "PhotometricInterpretation") else ""

            if len(frame.shape) == 2:
                # Grayscale
                wc = wc_var.get()
                ww = ww_var.get()
                frame_8 = apply_windowing(frame, wc, ww)
                img = Image.fromarray(frame_8, mode="L").convert("RGB")
            elif len(frame.shape) == 3 and frame.shape[2] == 3:
                # RGB
                if frame.dtype != "uint8":
                    frame = (frame / frame.max() * 255).astype("uint8")
                img = Image.fromarray(frame, mode="RGB")
            elif len(frame.shape) == 3 and frame.shape[2] == 4:
                if frame.dtype != "uint8":
                    frame = (frame / frame.max() * 255).astype("uint8")
                img = Image.fromarray(frame, mode="RGBA").convert("RGB")
            else:
                frame_8 = apply_windowing(frame.squeeze(), wc_var.get(), ww_var.get())
                img = Image.fromarray(frame_8, mode="L").convert("RGB")

            # Apply zoom
            cw = viewer_canvas.winfo_width() or 512
            ch = viewer_canvas.winfo_height() or 512
            iw, ih = img.size
            scale = viewer_state["zoom"]

            new_w = max(1, int(iw * scale))
            new_h = max(1, int(ih * scale))
            img = img.resize((new_w, new_h), Image.LANCZOS)

            # Position with pan
            x = cw // 2 + viewer_state["pan_x"]
            y = ch // 2 + viewer_state["pan_y"]

            tk_img = ImageTk.PhotoImage(img)
            viewer_state["tk_image"] = tk_img

            viewer_canvas.delete("all")
            viewer_canvas.create_image(x, y, anchor="center", image=tk_img)

        except Exception as e:
            viewer_canvas.delete("all")
            viewer_canvas.create_text(
                (viewer_canvas.winfo_width() or 512) // 2,
                (viewer_canvas.winfo_height() or 512) // 2,
                text=f"Render error: {e}", fill=RED, font=("Segoe UI", 10)
            )

    def viewer_auto_wl_from_array(px):
        try:
            mn, mx = float(px.min()), float(px.max())
            wc = int((mn + mx) / 2)
            ww = max(1, int(mx - mn))
            wc_var.set(wc)
            ww_var.set(ww)
        except Exception:
            pass

    def viewer_auto_wl():
        px = viewer_state["pixel_array"]
        if px is not None:
            viewer_auto_wl_from_array(px)
            viewer_render_frame()

    def viewer_fit_to_window():
        ds = viewer_state["ds"]
        px = viewer_state["pixel_array"]
        if ds is None or px is None:
            return
        cw = viewer_canvas.winfo_width() or 512
        ch = viewer_canvas.winfo_height() or 512
        frame = px[0] if viewer_state["n_frames"] > 1 and len(px.shape) == 3 and px.shape[2] not in (3, 4) else px
        ih, iw = (frame.shape[0], frame.shape[1]) if len(frame.shape) >= 2 else (512, 512)
        scale = min(cw / max(iw, 1), ch / max(ih, 1))
        viewer_state["zoom"] = scale
        viewer_state["pan_x"] = 0
        viewer_state["pan_y"] = 0
        viewer_render_frame()

    def viewer_reset_zoom():
        viewer_state["zoom"] = 1.0
        viewer_state["pan_x"] = 0
        viewer_state["pan_y"] = 0
        viewer_render_frame()

    def viewer_export_png():
        ds = viewer_state["ds"]
        px = viewer_state["pixel_array"]
        if ds is None or px is None:
            messagebox.showinfo("Info", "No image loaded", parent=root)
            return
        fp = filedialog.asksaveasfilename(
            parent=root, defaultextension=".png",
            filetypes=[("PNG", "*.png")],
            initialfile="frame.png"
        )
        if not fp:
            return
        try:
            frame_idx = viewer_state["current_frame"]
            n_frames = viewer_state["n_frames"]
            if n_frames > 1 and len(px.shape) == 3 and px.shape[2] not in (3, 4):
                frame = px[frame_idx]
            else:
                frame = px
            if len(frame.shape) == 2:
                frame_8 = apply_windowing(frame, wc_var.get(), ww_var.get())
                img = Image.fromarray(frame_8, mode="L")
            elif len(frame.shape) == 3:
                if frame.dtype != "uint8":
                    frame = (frame / frame.max() * 255).astype("uint8")
                img = Image.fromarray(frame, mode="RGB")
            else:
                frame_8 = apply_windowing(frame.squeeze(), wc_var.get(), ww_var.get())
                img = Image.fromarray(frame_8, mode="L")
            img.save(fp)
            log(f"[VIEWER] Exported PNG: {fp}")
            messagebox.showinfo("Exported", f"Saved to:\n{fp}", parent=root)
        except Exception as e:
            messagebox.showerror("Error", f"Export failed: {e}", parent=root)

    def viewer_goto_frame(idx):
        n = viewer_state["n_frames"]
        if idx == -1:
            idx = n - 1
        viewer_state["current_frame"] = max(0, min(n - 1, idx))
        viewer_render_frame()

    def viewer_prev_frame():
        f = viewer_state["current_frame"]
        viewer_goto_frame(max(0, f - 1))

    def viewer_next_frame():
        n = viewer_state["n_frames"]
        f = viewer_state["current_frame"]
        viewer_goto_frame(min(n - 1, f + 1))

    def viewer_toggle_play():
        viewer_state["playing"] = not viewer_state["playing"]
        play_btn_var.set("⏸" if viewer_state["playing"] else "⏯")
        if viewer_state["playing"]:
            viewer_play_tick()

    def viewer_play_tick():
        if not viewer_state["playing"]:
            return
        n = viewer_state["n_frames"]
        if n <= 1:
            viewer_state["playing"] = False
            play_btn_var.set("⏯")
            return
        f = (viewer_state["current_frame"] + 1) % n
        viewer_state["current_frame"] = f
        viewer_render_frame()
        fps = max(1, fps_var.get())
        interval = int(1000 / fps)
        viewer_state["after_id"] = root.after(interval, viewer_play_tick)

    def viewer_on_scroll(event):
        if viewer_state["ds"] is None:
            return
        factor = 1.1 if event.delta > 0 else 0.9
        viewer_state["zoom"] = max(0.05, min(50.0, viewer_state["zoom"] * factor))
        viewer_render_frame()

    def viewer_on_drag_start(event):
        viewer_state["drag_start"] = (event.x, event.y)

    def viewer_on_drag(event):
        if viewer_state["drag_start"] is None:
            return
        dx = event.x - viewer_state["drag_start"][0]
        dy = event.y - viewer_state["drag_start"][1]
        viewer_state["pan_x"] += dx
        viewer_state["pan_y"] += dy
        viewer_state["drag_start"] = (event.x, event.y)
        viewer_render_frame()

    def viewer_on_drag_end(event):
        viewer_state["drag_start"] = None

    viewer_canvas.bind("<MouseWheel>", viewer_on_scroll)
    viewer_canvas.bind("<Button-1>", viewer_on_drag_start)
    viewer_canvas.bind("<B1-Motion>", viewer_on_drag)
    viewer_canvas.bind("<ButtonRelease-1>", viewer_on_drag_end)
    root.bind("<space>", lambda e: viewer_toggle_play())

    def on_wl_change(event=None):
        # Debounce: slider drags fire many events; render once they settle
        if viewer_state["wl_after_id"]:
            root.after_cancel(viewer_state["wl_after_id"])
        viewer_state["wl_after_id"] = root.after(50, viewer_render_frame)

    def on_preset_change(event=None):
        pname = preset_var.get()
        preset = WL_PRESETS.get(pname)
        if preset:
            wc_var.set(preset[0])
            ww_var.set(preset[1])
        viewer_render_frame()

    wc_scale.config(command=lambda v: on_wl_change())
    ww_scale.config(command=lambda v: on_wl_change())
    preset_combo.bind("<<ComboboxSelected>>", on_preset_change)

    def update_metadata_panel(ds):
        tags_to_show = [
            ("PatientName", "Patient Name"),
            ("PatientID", "Patient ID"),
            ("StudyDate", "Study Date"),
            ("Modality", "Modality"),
            ("SOPClassUID", "SOP Class UID"),
            ("Rows", "Rows"),
            ("Columns", "Columns"),
            ("NumberOfFrames", "# Frames"),
            ("BitsAllocated", "Bits Alloc"),
            ("PhotometricInterpretation", "Photom. Interp"),
            ("SpecificCharacterSet", "Char. Set"),
        ]
        ts = ""
        if hasattr(ds, "file_meta") and hasattr(ds.file_meta, "TransferSyntaxUID"):
            ts = str(ds.file_meta.TransferSyntaxUID)

        lines = []
        for attr, label in tags_to_show:
            val = str(getattr(ds, attr, "")) if hasattr(ds, attr) else ""
            lines.append(f"{label}:\n  {val}\n")
        if ts:
            lines.append(f"Transfer Syntax:\n  {ts}\n")

        meta_text.config(state="normal")
        meta_text.delete("1.0", "end")
        meta_text.insert("end", "\n".join(lines))
        meta_text.config(state="disabled")

    # Double-click in files tab opens viewer
    def on_file_double_click(event):
        sel = files_tree.selection()
        if not sel:
            return
        fp = sel[0]  # iid is filepath
        if os.path.exists(fp):
            notebook.select(tab_viewer)
            load_dicom_file(fp)

    files_tree.bind("<Double-1>", on_file_double_click)

    # ===========================================================
    # TAB 5: Log
    # ===========================================================
    tab_log = ttk.Frame(notebook)
    notebook.add(tab_log, text="  Log  ")

    log_text = scrolledtext.ScrolledText(
        tab_log, bg="#0d0e10", fg="#7fd6a0",
        font=F_MONO, state="disabled", wrap=tk.WORD,
        relief="flat", bd=0, insertbackground=FG, padx=10, pady=8
    )
    log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    def clear_log():
        log_text.config(state="normal")
        log_text.delete("1.0", "end")
        log_text.config(state="disabled")

    ttk.Button(tab_log, text="Clear Log", command=clear_log).pack(pady=4)

    # ===========================================================
    # Server control
    # ===========================================================
    def update_header():
        ae = ae_var.get()
        port = port_var.get()
        cs_disp = cs_var.get()
        cs_val = CHAR_SET_VALUES.get(cs_disp, "ISO_IR 192")
        header_info.config(text=f"AE  {ae}     PORT  {port}     CS  {cs_val or 'ASCII'}")

    def set_status(running):
        status_dot.config(fg=GREEN if running else RED)
        status_txt.config(text="RUNNING" if running else "STOPPED",
                          fg=GREEN if running else FG2)

    def on_cs_change(event=None):
        cs_disp = cs_var.get()
        cs_val = CHAR_SET_VALUES.get(cs_disp, "ISO_IR 192")
        active_char_set["value"] = cs_val
        log(f"[SRV] Character Set changed to: {cs_val or 'ASCII (Default)'}")
        update_header()

    cs_combo.bind("<<ComboboxSelected>>", on_cs_change)

    def do_start():
        ae_title = ae_var.get().strip() or "MINIPACS"
        port = port_var.get().strip() or "11112"
        cs_disp = cs_var.get()
        cs_val = CHAR_SET_VALUES.get(cs_disp, "ISO_IR 192")
        active_char_set["value"] = cs_val

        def _start():
            ok = start_server(ae_title, int(port))
            def _upd():
                if ok:
                    set_status(True)
                    btn_start.config(state="disabled")
                    btn_stop.config(state="normal")
                    update_header()
                else:
                    set_status(False)
            root.after(0, _upd)
        threading.Thread(target=_start, daemon=True).start()

    def do_stop():
        def _stop():
            stop_server()
            def _upd():
                set_status(False)
                btn_start.config(state="normal")
                btn_stop.config(state="disabled")
            root.after(0, _upd)
        threading.Thread(target=_stop, daemon=True).start()

    btn_start.config(command=do_start)
    btn_stop.config(command=do_stop, state="disabled")

    # ===========================================================
    # GUI update loop (poll queues)
    # ===========================================================
    def poll_log():
        msgs = []
        while True:
            try:
                msgs.append(log_queue.get_nowait())
            except queue.Empty:
                break
        if msgs:
            log_text.config(state="normal")
            log_text.insert("end", "\n".join(msgs) + "\n")
            log_text.see("end")
            log_text.config(state="disabled")
        root.after(200, poll_log)

    def on_store_cb(file_info):
        root.after(0, refresh_files_tree)

    def on_mpps_cb(entry):
        root.after(0, refresh_mpps_tree)

    gui_callbacks["on_store"] = on_store_cb
    gui_callbacks["on_mpps"] = on_mpps_cb

    ae_var.trace_add("write", lambda *_: update_header())
    port_var.trace_add("write", lambda *_: update_header())

    poll_log()
    log("[SRV] MiniPACS ready. Configure AE-Title and Port, then press ▶ Start Server")

    # Graceful close
    def on_close():
        if server_handle["running"]:
            stop_server()
        for key in ("after_id", "wl_after_id"):
            if viewer_state[key]:
                root.after_cancel(viewer_state[key])
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="MiniPACS DICOM Test Server")
    parser.add_argument("--headless", action="store_true",
                        help="Run without GUI, stdout logging, Ctrl+C to stop")
    args = parser.parse_args()

    os.makedirs(storage_dir, exist_ok=True)

    if args.headless:
        run_headless()
    else:
        run_gui()


if __name__ == "__main__":
    main()
