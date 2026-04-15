# MiniPACS – DICOM Mini PACS Test Server

## What is MiniPACS

MiniPACS is a lightweight, single-file Python DICOM server with a dark-mode graphical user interface. It is intended for **development, testing, and integration** of DICOM-capable devices and software such as modalities, worklist clients, RIS/PACS systems, and DICOM viewers.

It supports Modality Worklist (MWL C-FIND), image storage (C-STORE), Modality Performed Procedure Step (MPPS N-CREATE/N-SET), and C-ECHO verification. A built-in DICOM viewer lets you inspect received images directly in the application.

**Intended use:** dev/test/integration environments only.

---

## ⚠️ Medical Device Disclaimer

> **MiniPACS is NOT a certified medical device.**
>
> - It is NOT CE-marked or MDR-certified.
> - It must NOT be used in live clinical environments or for real patient care.
> - It must NOT be used to store or process real patient data.
> - Only use anonymized or synthetic test data.
> - Ensure compliance with GDPR and applicable data protection regulations in your jurisdiction.
>
> **This software is provided for developer and integration testing purposes only.**

---

## Quick Start

### Prerequisites

```
pip install pynetdicom pydicom pyinstaller Pillow
```

### Run directly

```
python mini_pacs_server.py
```

The GUI will open. Configure the AE-Title and port, then click **▶ Start Server**.

---

## Build EXE

Run the included build script:

```
build.bat
```

Or manually:

```
pyinstaller ^
    --onefile ^
    --windowed ^
    --name MiniPACS ^
    --hidden-import pynetdicom ^
    --hidden-import pynetdicom.sop_class ^
    --hidden-import pydicom ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageTk ^
    --collect-all pynetdicom ^
    --collect-all pydicom ^
    --collect-all PIL ^
    mini_pacs_server.py
```

Output: `dist\MiniPACS.exe`

---

## Headless Mode

Run without a GUI, useful for CI pipelines or automated integration tests:

```
python mini_pacs_server.py --headless
```

- Loads 2 sample worklist entries automatically
- Logs all DICOM events to stdout
- Press **Ctrl+C** to stop

---

## DICOM Configuration

Configure your DICOM device (modality, SCU) to connect to MiniPACS:

| Setting         | Value                |
|-----------------|----------------------|
| Called AE-Title | `MINIPACS` (default) |
| Host / IP       | `127.0.0.1` (or your PC's IP) |
| Port            | `11112` (default)    |

Both AE-Title and port are configurable in the GUI without restarting.

---

## Supported Services

| Service                          | Role | Description                                      |
|----------------------------------|------|--------------------------------------------------|
| **MWL C-FIND**                   | SCP  | Modality Worklist – returns scheduled procedures |
| **C-STORE**                      | SCP  | Accepts all Storage SOP Classes (images, SR, etc.) |
| **MPPS N-CREATE / N-SET**        | SCP  | Modality Performed Procedure Step tracking       |
| **C-ECHO**                       | SCP  | Verification / ping                              |

---

## DICOM Viewer

The built-in viewer (Tab: **DICOM Viewer**) supports:

- **Grayscale images:** CT, MR, XA, CR, NM, etc. — with windowing (W/C sliders and presets)
- **Color images:** RGB, RGBA photometric interpretations
- **Multi-frame / cine:** playback toolbar with ⏮ ⏪ ⏯ ⏩ ⏭ controls, FPS slider (1–30), frame counter
- **Windowing presets:** Default, Abdomen, Lung, Bone, Brain, Angio; Auto-WL button
- **Zoom & Pan:** mouse scroll to zoom, click-drag to pan
- **Metadata sidebar:** collapsible panel with key DICOM tags
- **Export:** save current frame as PNG
- **Open from disk:** open any `.dcm` file directly

### Encapsulated Video Fallback

If the Transfer Syntax is MPEG-2, MPEG-4, or HEVC (`1.2.840.10008.1.2.4.100`–`106`), the viewer cannot decode the pixel data natively. Instead, it shows:

> ⚠️ Encapsulated video (MPEG/HEVC) – native playback not supported. Click to open with system default player.

The **Open externally** button saves the pixel data to a temporary `.mp4` file and opens it with the Windows default player.

---

## MPPS Linking

The **MPPS** tab shows all received N-CREATE / N-SET messages with a **Link-Status** column:

| Status         | Meaning                                                                 |
|----------------|-------------------------------------------------------------------------|
| 🔗 **Linked**  | The AccessionNumber in the MPPS message matches a worklist entry (green row) |
| ⚠️ **Unlinked** | No matching worklist entry found – procedure was started without prior scheduling (orange row) |

**Why this matters:** In a real RIS/PACS environment, unlinked MPPS records indicate that images were acquired without a matching order. This complicates billing, results routing, and reconciliation. MiniPACS helps you verify that your modality correctly sends the AccessionNumber from the worklist.

Log messages:
```
[MPPS] N-CREATE LINKED – AccNo ACC-001
[MPPS] N-CREATE UNLINKED – no matching worklist entry (AccNo: ACC-999)
```

---

## Character Sets

MiniPACS injects `(0008,0005) SpecificCharacterSet` into every C-FIND response. The active character set is shown in the header and can be changed at any time without restarting the server.

| Display Name               | DICOM Value      | Languages / Scripts            |
|----------------------------|------------------|--------------------------------|
| UTF-8 (empfohlen)          | `ISO_IR 192`     | Universal (recommended)        |
| Latin-1 – Westeuropa       | `ISO_IR 100`     | German, French, Spanish, etc.  |
| Latin-2 – Osteuropa        | `ISO_IR 101`     | Polish, Czech, Hungarian, etc. |
| Kyrillisch                 | `ISO_IR 144`     | Russian, Bulgarian, etc.       |
| Arabisch                   | `ISO_IR 127`     | Arabic                         |
| Griechisch                 | `ISO_IR 126`     | Greek                          |
| Türkisch                   | `ISO_IR 148`     | Turkish                        |
| Japanisch                  | `ISO 2022 IR 87` | Japanese (Kanji)               |
| Koreanisch                 | `ISO 2022 IR 149`| Korean                         |
| Chinesisch                 | `GB18030`        | Chinese (Simplified/Traditional)|
| ASCII (Default)            | *(empty)*        | US-ASCII only                  |

**UTF-8 is strongly recommended** for new installations, as it supports all scripts in a single encoding.

### Mismatch Warning

If a C-STORE object arrives with a different `SpecificCharacterSet` than the server is configured for, the Log tab displays:

```
[WARN] C-STORE SpecificCharacterSet mismatch: received ISO_IR 100, server configured ISO_IR 192
```

This helps identify encoding inconsistencies between your modality and the server.

---

## Port Note

| Port    | Admin / Elevated Rights Required? | Notes                          |
|---------|-----------------------------------|--------------------------------|
| `11112` | No                                | Default – works without UAC    |
| `104`   | Yes (admin / root)                | Well-known DICOM port          |
| `1024+` | No                                | Any port ≥ 1024 works normally |

To change the port: enter the desired port number in the **Port** field in the GUI and restart the server. The info label in the GUI reminds you:

> ℹ️ Port 104 requires admin rights – default 11112 is recommended

---

## Third-Party Licenses

| Library      | License | Copyright Holder                         | File                       |
|--------------|---------|------------------------------------------|----------------------------|
| pynetdicom   | MIT     | Scaramallion and contributors            | `LICENSE_pynetdicom.txt`   |
| pydicom      | MIT     | Darcy Mason and contributors             | `LICENSE_pydicom.txt`      |
| Pillow       | HPND    | Jeffrey A. Clark, Secret Labs AB, Fredrik Lundh | `LICENSE_Pillow.txt` |
| PyInstaller  | GPL v2 + Classpath Exception | PyInstaller Development Team | See pyinstaller.org |
| Python / PSF | PSF License (BSD-compatible) | Python Software Foundation | See python.org |
| NumPy        | BSD 3-Clause | NumPy Developers             | See numpy.org              |

Full attribution: see `NOTICE.txt`
