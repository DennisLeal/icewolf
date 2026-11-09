from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = ["keyring.backends.Windows", "google_auth_httplib2"]
for package in ("faster_whisper", "kokoro_onnx", "espeakng_loader", "onnxruntime", "ctranslate2",
                "googleapiclient", "pypdf", "docx", "keyring"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    ["entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["torch", "tensorflow", "matplotlib", "scipy", "IPython", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="Icewolf",
    console=False, disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Icewolf")
