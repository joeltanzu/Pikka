# Pikka

A minimal, dark-themed macOS desktop app for sorting and batch-renaming photos — built as a single Python file using PyQt6.

---

## Overview

Pikka lets you drag a folder of photos into a visual grid, sort and reorder them, then rename them in one shot with a sequential prefix (`photo_001.jpg`, `photo_002.jpg`, …). Non-JPEG formats can be converted to JPEG on the fly during rename.

**Supported formats:** JPG, PNG, HEIC, WEBP, TIFF, BMP, GIF

**Key features:**

- Batch rename with sequential numbering and a configurable prefix
- Optional JPEG conversion for PNG, HEIC, WEBP, TIFF, BMP, and GIF files
- Optional deletion of original files after conversion
- Sort by Name, Date Modified, Date Taken (EXIF), or File Size — ascending or descending
- Thumbnail grid with drag-to-reorder (live card shuffling as you drag)
- Folder watching: a banner appears when files change on disk while the app is open


---

## Requirements

- macOS
- Python 3.9+
- [PyQt6](https://pypi.org/project/PyQt6/)
- [Pillow](https://pypi.org/project/Pillow/)
- [piexif](https://pypi.org/project/piexif/)
- [watchdog](https://pypi.org/project/watchdog/) *(optional — enables live folder watching)*

---

## Installation

# Clone the repo
git clone https://github.com/joeltanzu/Pikka.git
cd Pikka

# Install dependencies
pip install PyQt6 pillow piexif watchdog
```

---

## Usage

# Launch the app
python3 pikka.py

1. **Open a folder** — drag a folder onto the window, or click the folder button in the header.
2. **Sort** — use the sort toolbar to order by Name, Date Modified, Date Taken, or Size. Toggle ascending/descending with the arrow button.
3. **Reorder** — drag cards within the grid to set a custom order before renaming.
4. **Configure rename** — set a prefix in the bottom bar (default: `photo_`). Enable JPEG conversion for any non-JPEG formats shown in the conversion panel.
5. **Rename** — click **Rename**. A confirmation dialog lists every old → new filename. Confirm to apply.

---

## License

MIT License. 
