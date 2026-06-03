<p align="center">
  <img src="assets/icon.png" width="128" alt="Pikka icon" />
</p>

# Pikka

> A minimal macOS photo-sorting app for visually ordering images and batch-renaming them in one clean pass.

![version](https://img.shields.io/badge/version-1.0.0-00d4aa?style=flat-square)
![platform](https://img.shields.io/badge/platform-macOS-lightgrey?style=flat-square)
![python](https://img.shields.io/badge/python-3.9+-blue?style=flat-square)
![ui](https://img.shields.io/badge/ui-PyQt6-f0a020?style=flat-square)

---

![Pikka screenshot](assets/screenshot.png)

## What it does

Pikka helps you take a messy folder of photos, see the images as a grid, place them in the order you actually want, and rename them with a clean numbered sequence.

It is intentionally small and practical: load a folder, sort or drag the images into place, preview every rename, then commit the batch.

## Features

- Drag a folder onto the app or open one from the header
- Thumbnail grid with live drag-to-reorder behavior
- Sort by file name, date modified, EXIF date taken, or file size
- Toggle ascending or descending sort order
- Batch rename with a configurable prefix and sequential numbering
- Confirmation dialog showing every old filename and new filename before changes are applied
- Optional JPEG conversion for non-JPEG images
- Optional deletion of originals after conversion
- Folder watcher that warns when files change on disk while the app is open
- Dark, focused interface designed around image review rather than file-browser clutter

## Supported formats

| Format | Notes |
|---|---|
| JPG / JPEG | Supported directly |
| PNG | Can be converted to JPEG |
| HEIC | Can be converted to JPEG when Pillow supports the local codec path |
| WEBP | Can be converted to JPEG |
| TIFF / TIF | Can be converted to JPEG |
| BMP | Can be converted to JPEG |
| GIF | Can be converted to JPEG |

## Requirements

- macOS
- Python 3.9+
- [PyQt6](https://pypi.org/project/PyQt6/)
- [Pillow](https://pypi.org/project/Pillow/)
- [piexif](https://pypi.org/project/piexif/)
- [watchdog](https://pypi.org/project/watchdog/)

## Getting started

```bash
git clone https://github.com/joeltanzu/Pikka.git
cd Pikka

python3 -m pip install PyQt6 pillow piexif watchdog
python3 pikka.py
```

You can also launch Pikka with a folder already loaded:

```bash
python3 pikka.py /path/to/photos
```

## Workflow

1. **Open a folder** by dropping it onto the window or using the folder button.
2. **Sort the grid** by name, modified date, date taken, or size.
3. **Drag images** into a custom order when the automatic sort is not enough.
4. **Set a prefix** such as `photo_`, `trip_`, or `listing_`.
5. **Choose conversion options** for non-JPEG files if you want a JPEG-only output set.
6. **Review the rename preview** before committing the batch.
7. **Rename** and let Pikka apply the sequence.

## Building the app bundle

Pikka includes a py2app configuration:

```bash
python3 setup.py py2app
open dist/Pikka.app
```

For a lightweight development bundle:

```bash
python3 setup.py py2app --alias
```

## macOS Gatekeeper

The local app bundle is unsigned, so macOS may block it the first time you open it.

Recommended path:

1. Right-click `Pikka.app` in Finder.
2. Choose **Open**.
3. Confirm **Open** in the system dialog.

Alternatively, remove the quarantine flag:

```bash
xattr -dr com.apple.quarantine dist/Pikka.app
```

## Built with

- PyQt6 for the native desktop interface
- Pillow and piexif for image handling and metadata-aware thumbnail work
- watchdog for folder-change detection
- py2app for macOS app bundling

## License

MIT. Small tool, sharp edge, use it well.
