from setuptools import setup

APP = ["pikka.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,  # Must be False for PyQt6
    "packages": [
        "PyQt6",
        "PIL",
        "piexif",
        "watchdog",
    ],
    "includes": [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtWidgets",
    ],
    "iconfile": "icon.icns",
    "excludes": [
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
    ],
    "plist": {
        "CFBundleName": "Pikka",
        "CFBundleDisplayName": "Pikka",
        "CFBundleIdentifier": "com.joeltanzu.pikka",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # honour system dark/light mode
    },
}

setup(
    name="Pikka",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
