# MiniPACS – DICOM Mini PACS Test Server

MiniPACS is a lightweight, **single-file** Python DICOM server with a dark-mode
graphical user interface. It is built for **development, testing, and
integration** of DICOM-capable devices and software: modalities, worklist
clients, RIS/PACS systems, DICOM routers, and viewers.

One file (`mini_pacs_server.py`), no database, no configuration files. Start it,
point your modality at it, and watch DICOM traffic arrive in real time.

It provides Modality Worklist (MWL C-FIND), image storage (C-STORE), Modality
Performed Procedure Step (MPPS N-CREATE / N-SET), and C-ECHO verification — all
as an SCP (Service Class Provider). A built-in DICOM viewer lets you inspect
received images without leaving the application.

> **Intended use:** dev / test / integration environments only.

---

## Table of Contents

- [Medical Device Disclaimer](#-medical-device-disclaimer)
- [Feature Overview](#feature-overview)
- [Quick Start](#quick-start)
- [Command-Line Options](#command-line-options)
- [DICOM Configuration](#dicom-configuration)
- [Supported Services](#supported-services)
- [The GUI, Tab by Tab](#the-gui-tab-by-tab)
- [DICOM Viewer](#dicom-viewer)
- [MPPS Linking](#mpps-linking)
- [Character Sets](#character-sets)
- [Testing Against MiniPACS](#testing-against-minipacs)
- [Headless Mode & CI](#headless-mode--ci)
- [Building a Windows EXE](#building-a-windows-exe)
- [Architecture](#architecture)
- [Project Layout](#project-layout)
- [Troubleshooting](#troubleshooting)
- [Known Limitations](#known-limitations)
- [Development](#development)
- [Third-Party Licenses](#third-party-licenses)
- [License](#license)

---

## ⚠️ Medical Device Disclaimer

> **MiniPACS is NOT a certified medical device.**
>
> - It is NOT CE-marked or MDR-certified.
> - It must NOT be used in live clinical environments or for real patient care.
> - It must NOT be used to store or process real patient data.
> - Only use anonymized or synthetic test data.
> - Ensure compliance with GDPR and applicable data-protection regulations in
>   your jurisdiction.
>
> **This software is provided for developer and integration testing purposes
> only.**

---

## Feature Overview

| Area | What you get |
|------|--------------|
| **Worklist (MWL)** | Add entries via the GUI form, load 6 built-in samples, or start with 2 in headless mode. C-FIND responses are filtered by Modality and Scheduled Date. |
| **Storage (C-STORE)** | Accepts every Storage SOP Class. Files are written as `<SOPInstanceUID>.dcm` to a configurable directory. |
| **MPPS** | N-CREATE / N-SET tracked in a live table, with automatic linking to worklist entries by Accession Number. |
| **C-ECHO** | Always answered — useful as a connectivity ping. |
| **Viewer** | Grayscale windowing with presets, color images, multi-frame cine playback, zoom/pan, metadata panel, PNG export. |
| **Character sets** | 11 selectable encodings, injected into C-FIND responses; mismatch warnings on C-STORE. |
| **Logging** | Timestamped event log in the GUI and on stdout. |
| **Packaging** | `build.bat` / `MiniPACS.spec` produce a single self-contained `MiniPACS.exe`. |

---

## Quick Start

### Prerequisites

- Python 3.9+ (3.11+ recommended)
- Packages:

```
pip install pynetdicom pydicom Pillow numpy
```

`Pillow` and `numpy` are only required for the built-in viewer. The DICOM server
itself runs without them (with a reduced feature set in the GUI).

### Run directly

```
python mini_pacs_server.py
```

The GUI opens. Set the **AE-Title** and **Port**, then click **▶ Start Server**.
AE-Title and port can be changed at any time — stop and start the server to
apply.

---

## Command-Line Options

| Option | Effect |
|--------|--------|
| *(none)* | Launch the dark-mode GUI. |
| `--headless` | Run without a GUI: load 2 sample worklist entries, start the server on `MINIPACS:11112`, log to stdout, stop on `Ctrl+C`. |
| `-h`, `--help` | Show usage. |

---

## DICOM Configuration

Configure your DICOM device (modality / SCU) to connect to MiniPACS:

| Setting         | Value |
|-----------------|-------|
| Called AE-Title | `MINIPACS` (default, configurable) |
| Host / IP       | `127.0.0.1`, or your machine's LAN IP for remote devices |
| Port            | `11112` (default, configurable) |

The calling AE-Title of the SCU is not checked — any caller is accepted.

---

## Supported Services

| Service | Role | SOP Class UID | Notes |
|---------|------|---------------|-------|
| **Verification (C-ECHO)** | SCP | `1.2.840.10008.1.1` | Always returns success. |
| **Modality Worklist (C-FIND)** | SCP | `1.2.840.10008.5.1.4.31` | Filters on Modality and Scheduled Procedure Step Start Date. |
| **Storage (C-STORE)** | SCP | *all* Storage SOP Classes | Images, SR, PDF, RTSTRUCT, etc. Written to disk. |
| **MPPS (N-CREATE / N-SET)** | SCP | `1.2.840.10008.3.1.2.3.3` | Status tracked; linked to worklist by Accession Number. |

Transfer syntaxes: all that pynetdicom negotiates by default, including
Implicit/Explicit VR Little Endian and the common compressed syntaxes.

---

## The GUI, Tab by Tab

### Worklist

- **Config row** — AE-Title, Port, and Character Set. A hint reminds you that
  port 104 needs admin rights.
- **Add Worklist Entry** — a form for Patient Name/ID, Accession Number,
  Modality, Date (`YYYYMMDD`), Time (`HHMMSS`), Description, Station AE, and
  Physician. **+ Add Entry** appends it; **Load 6 Samples** adds a spread of
  modalities and character sets (including Cyrillic and Korean names).
- **Table** — every entry currently served. **Delete Selected** / **Delete All**
  manage the list.

### MPPS

Live table of received MPPS messages: shortened UID, patient, status
(`IN PROGRESS` → `COMPLETED` / `DISCONTINUED`), start/end time, and link status.
Rows are colour-coded green (linked) or orange (unlinked).

### Received Files

Every stored instance: filename, size, modality, patient, timestamp. Set the
**Storage Directory** with **Browse…**. Double-click a row to open it in the
viewer.

### DICOM Viewer

See [DICOM Viewer](#dicom-viewer) below.

### Log

Timestamped, colour-on-black event log. **Clear Log** empties it. The same lines
are printed to stdout.

---

## DICOM Viewer

The built-in viewer (tab **DICOM Viewer**) supports:

- **Grayscale images** — CT, MR, XA, CR, NM, … with windowing (WC/WW sliders,
  presets, and an **Auto WL** button that fits the window to the pixel range).
- **Color images** — RGB and RGBA photometric interpretations.
- **Multi-frame / cine** — playback toolbar (⏮ ⏪ ⏯ ⏩ ⏭), FPS slider (1–30),
  frame counter. `Space` toggles play/pause.
- **Windowing presets** — Default, Abdomen, Lung, Bone, Brain, Angio.
- **Zoom & pan** — mouse wheel to zoom, click-drag to pan, **Fit to Window** and
  **Reset Zoom** buttons.
- **Metadata sidebar** — collapsible panel with key tags and the transfer syntax.
- **Export** — save the current frame as PNG.
- **Open from disk** — open any `.dcm` file directly, independent of what the
  server has received.

### Encapsulated Video Fallback

If the transfer syntax is MPEG-2, MPEG-4, or HEVC
(`1.2.840.10008.1.2.4.100`–`106`), the pixel data cannot be decoded natively.
The viewer then shows:

> ⚠️ Encapsulated video (MPEG/HEVC) – native playback not supported. Click to
> open with system default player.

**Open externally** writes the pixel stream to a temporary `.mp4` and hands it to
the OS default player.

---

## MPPS Linking

The **MPPS** tab shows every received N-CREATE / N-SET with a **Link-Status**
column:

| Status | Meaning |
|--------|---------|
| 🔗 **Linked** | The Accession Number in the MPPS message matches a worklist entry (green row). |
| ⚠️ **Unlinked** | No matching worklist entry — the procedure was started without prior scheduling (orange row). |

**Why this matters:** in a real RIS/PACS environment, unlinked MPPS records mean
images were acquired without a matching order, which complicates billing, results
routing, and reconciliation. MiniPACS lets you verify that your modality sends
the Accession Number from the worklist all the way through to MPPS.

Log messages:

```
[MPPS] N-CREATE LINKED – AccNo ACC-001
[MPPS] N-CREATE UNLINKED – no matching worklist entry (AccNo: ACC-999)
```

---

## Character Sets

MiniPACS injects `(0008,0005) SpecificCharacterSet` into every C-FIND response.
The active character set is shown in the header and can be changed at any time
without restarting the server.

| Display Name | DICOM Value | Languages / Scripts |
|--------------|-------------|---------------------|
| UTF-8 (empfohlen) | `ISO_IR 192` | Universal (recommended) |
| Latin-1 – Westeuropa | `ISO_IR 100` | German, French, Spanish, … |
| Latin-2 – Osteuropa | `ISO_IR 101` | Polish, Czech, Hungarian, … |
| Kyrillisch | `ISO_IR 144` | Russian, Bulgarian, … |
| Arabisch | `ISO_IR 127` | Arabic |
| Griechisch | `ISO_IR 126` | Greek |
| Türkisch | `ISO_IR 148` | Turkish |
| Japanisch | `ISO 2022 IR 87` | Japanese (Kanji) |
| Koreanisch | `ISO 2022 IR 149` | Korean |
| Chinesisch | `GB18030` | Chinese (Simplified / Traditional) |
| ASCII (Default) | *(empty)* | US-ASCII only |

**UTF-8 is strongly recommended** for new installations — one encoding for all
scripts.

### Mismatch Warning

If a C-STORE object arrives with a different `SpecificCharacterSet` than the
server is configured for, the Log tab shows:

```
[WARN] C-STORE SpecificCharacterSet mismatch: received ISO_IR 100, server configured ISO_IR 192
```

This surfaces encoding inconsistencies between your modality and the server.

---

## Testing Against MiniPACS

Any DICOM toolkit works. Examples below use
[DCMTK](https://dicom.offis.de/dcmtk) command-line tools.

### C-ECHO (connectivity)

```
echoscu -aec MINIPACS 127.0.0.1 11112
```

### Query the worklist (C-FIND)

```
findscu -W -k "(0008,0060)=CT" -k "ScheduledProcedureStepSequence" \
        -aec MINIPACS 127.0.0.1 11112
```

`-W` selects the Modality Worklist information model. Add `-k` keys to filter;
MiniPACS honours Modality and Scheduled Procedure Step Start Date.

### Send an image (C-STORE)

```
storescu -aec MINIPACS 127.0.0.1 11112 image.dcm
```

The file appears in the **Received Files** tab and on disk as
`<SOPInstanceUID>.dcm`.

### Send MPPS (N-CREATE / N-SET)

Use your modality or a tool such as `dcmtk`'s `nsc`/`nsu` or
[dcm4che](https://github.com/dcm4che/dcm4che)'s `mppsscu`. Include a
`ScheduledStepAttributesSequence` with an `AccessionNumber` that matches a
worklist entry to see the link light up.

### With pynetdicom (Python)

```python
from pynetdicom import AE
from pynetdicom.sop_class import Verification

ae = AE()
ae.add_requested_context(Verification)
assoc = ae.associate("127.0.0.1", 11112, ae_title="MINIPACS")
if assoc.is_established:
    print(assoc.send_c_echo())
    assoc.release()
```

---

## Headless Mode & CI

```
python mini_pacs_server.py --headless
```

- Loads 2 sample worklist entries automatically.
- Starts the server on `MINIPACS:11112`.
- Logs every DICOM event to stdout.
- Stops on `Ctrl+C`.

Useful as a background service in integration pipelines:

```yaml
# GitHub Actions sketch
- name: Start MiniPACS
  run: python mini_pacs_server.py --headless &
- name: Wait for port
  run: |
    for i in $(seq 1 20); do
      python -c "import socket;socket.create_connection(('127.0.0.1',11112),2)" && break
      sleep 1
    done
- name: Run DICOM integration tests
  run: pytest tests/
```

---

## Building a Windows EXE

### Using the batch script

```
build.bat
```

It upgrades the build dependencies, runs PyInstaller with the required hidden
imports and `--collect-all` for the DICOM/imaging packages, and verifies that
`dist\MiniPACS.exe` was produced.

### Using the spec file

```
pyinstaller MiniPACS.spec
```

The spec is the source of truth for the packaging configuration (hidden imports,
`collect_all`, one-file windowed EXE, UPX compression). `build.bat` keeps its
command line in sync with it.

**Output:** `dist\MiniPACS.exe` — a single self-contained executable, no Python
installation required on the target machine.

### Notes

- UPX is enabled in the spec. If UPX is not on `PATH`, PyInstaller simply skips
  compression — the build still succeeds, the EXE is just larger.
- First launch of a one-file EXE is slower: it unpacks to a temp directory.
- Antivirus software occasionally flags fresh PyInstaller EXEs (generic
  heuristics). Whitelist locally or sign the binary for distribution.

---

## Architecture

Everything lives in `mini_pacs_server.py`.

```
main()
 ├─ --headless ─► run_headless()      stdout logging, no Tk
 └─ default    ─► run_gui()           tkinter + ttk dark theme
                     │
                     ├─ Worklist / MPPS / Files / Viewer / Log tabs
                     └─ poll loop (root.after) drains the log queue and
                        refreshes tables when handlers signal via callbacks

start_server(ae_title, port)
 └─ pynetdicom AE.start_server(block=False)   background thread
      handlers:  EVT_C_ECHO   ─► handle_echo
                 EVT_C_FIND   ─► handle_find      (generator, yields matches)
                 EVT_C_STORE  ─► handle_store     (writes .dcm, records file)
                 EVT_N_CREATE ─► handle_n_create  (MPPS start, worklist link)
                 EVT_N_SET    ─► handle_n_set     (MPPS status update)
```

**Threading model**

- The DICOM server runs on pynetdicom's own thread(s); handlers execute there.
- Shared state — `worklist_entries`, `mpps_entries`, `received_files` — is
  guarded by dedicated `threading.Lock`s.
- Handlers never touch Tk directly. They push log lines onto a `queue.Queue`
  and invoke lightweight callbacks that marshal UI work back to the Tk thread
  with `root.after(0, …)`.
- The active character set and server handle are small shared dicts mutated
  under the GIL.

**No persistence.** Worklist and MPPS state live in memory for the session.
Received files are the only thing written to disk.

---

## Project Layout

```
mini_pacs_server.py      the entire application
build.bat                PyInstaller build script (Windows)
MiniPACS.spec            PyInstaller spec (packaging source of truth)
README.md                this file
LICENSE                  MiniPACS license (MIT)
NOTICE.txt               third-party attribution
LICENSE_pynetdicom.txt   bundled dependency license
LICENSE_pydicom.txt      bundled dependency license
LICENSE_Pillow.txt       bundled dependency license
.gitignore
received_dicom/          default storage dir (created at runtime, git-ignored)
```

---

## Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| `ERROR: pydicom is not installed` on start | `pip install pydicom pynetdicom` |
| Viewer says "Pillow is not installed" | `pip install Pillow numpy` — the server still runs without them. |
| `[SRV] Failed to start: ... Permission denied` | Port below 1024 without admin rights. Use `11112`. |
| `[SRV] Failed to start: ... address already in use` | Another process (or a previous MiniPACS) holds the port. Stop it or pick another port. |
| SCU cannot associate | Check the **Called AE-Title** matches (`MINIPACS`), the firewall allows the port, and you are using the machine's real IP for remote devices. |
| C-FIND returns nothing | The worklist is empty, or your Modality/Date filter excludes every entry. Load the 6 samples to confirm connectivity. |
| Images decode but look wrong | Try **Auto WL** or a windowing preset. Compressed transfer syntaxes need the matching pydicom pixel-data handler / plugin installed. |
| `[WARN] ... SpecificCharacterSet mismatch` | Informational — your modality's encoding differs from the server setting. |

---

## Known Limitations

- SCP only — MiniPACS does not initiate C-MOVE / C-GET / C-STORE to other nodes.
- No Query/Retrieve (C-FIND/C-MOVE on the Study model); only Modality Worklist.
- No TLS.
- Worklist filtering covers Modality and Scheduled Date, not the full MWL key
  set.
- MPPS and worklist state are not persisted across restarts.
- Encapsulated video (MPEG/HEVC) is not rendered in-app, only handed to the OS
  player.

---

## Development

- Single file, standard library + pydicom/pynetdicom/Pillow/numpy. No build step
  to run from source.
- Style: keep it one file; match the surrounding code.
- Run the GUI (`python mini_pacs_server.py`) and headless
  (`python mini_pacs_server.py --headless`) paths before committing.
- `MiniPACS.spec` is the packaging source of truth — update it and `build.bat`
  together when imports change.

---

## Third-Party Licenses

| Library | License | Copyright Holder | File |
|---------|---------|------------------|------|
| pynetdicom | MIT | Scaramallion and contributors | `LICENSE_pynetdicom.txt` |
| pydicom | MIT | Darcy Mason and contributors | `LICENSE_pydicom.txt` |
| Pillow | HPND | Jeffrey A. Clark, Secret Labs AB, Fredrik Lundh | `LICENSE_Pillow.txt` |
| PyInstaller | GPL v2 + Classpath Exception | PyInstaller Development Team | see pyinstaller.org |
| Python / PSF | PSF License (BSD-compatible) | Python Software Foundation | see python.org |
| NumPy | BSD 3-Clause | NumPy Developers | see numpy.org |

Full attribution: see `NOTICE.txt`.

---

## License

MiniPACS is released under the MIT License — see `LICENSE`.
