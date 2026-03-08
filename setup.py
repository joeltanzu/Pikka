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
    "strip": True,  # Strip debug symbols from binaries
    "excludes": [
        # Stdlib / GUI toolkits not used
        "tkinter", "_tkinter",
        "matplotlib", "numpy", "scipy", "pandas",

        # Unused PyQt6 modules (keep only Core, Gui, Widgets)
        "PyQt6.QtBluetooth",
        "PyQt6.QtDBus",
        "PyQt6.QtDesigner",
        "PyQt6.QtHelp",
        "PyQt6.QtLocation",
        "PyQt6.QtMultimedia",
        "PyQt6.QtMultimediaWidgets",
        "PyQt6.QtNetwork",
        "PyQt6.QtNetworkAuth",
        "PyQt6.QtNfc",
        "PyQt6.QtOpenGL",
        "PyQt6.QtOpenGLWidgets",
        "PyQt6.QtPdf",
        "PyQt6.QtPdfWidgets",
        "PyQt6.QtPositioning",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtQml",
        "PyQt6.QtQuick",
        "PyQt6.QtQuick3D",
        "PyQt6.QtQuickControls2",
        "PyQt6.QtQuickWidgets",
        "PyQt6.QtRemoteObjects",
        "PyQt6.QtSensors",
        "PyQt6.QtSerialBus",
        "PyQt6.QtSerialPort",
        "PyQt6.QtShaderTools",
        "PyQt6.QtSpatialAudio",
        "PyQt6.QtSql",
        "PyQt6.QtSvg",
        "PyQt6.QtSvgWidgets",
        "PyQt6.QtTest",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebSockets",

        # Dev / debug toolchain (pulled in as transitive deps)
        "debugpy",
        "IPython",
        "ipykernel",
        "ipython_genutils",
        "jedi",
        "jupyter_client",
        "jupyter_core",
        "zmq",
        "tornado",
        "parso",
        "pygments",
        "traitlets",
        "psutil",

        # Packaging tools not needed at runtime
        "setuptools",
        "pkg_resources",
        "pip",
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
