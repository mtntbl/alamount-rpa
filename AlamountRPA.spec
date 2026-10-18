# -*- mode: python ; coding: utf-8 -*-
# Alamount RPA — PyInstaller: pyinstaller --noconfirm --clean AlamountRPA.spec
# Klasör (onedir) derlemesi: Robot Framework kütüphaneleri ada göre dinamik yüklendiği için
# gerekli RPA/robot alt modülleri açıkça eklenir.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

sys.path.insert(0, os.path.abspath("."))
import marka  # noqa: E402

# Windows dosya özellikleri (Özellikler > Ayrıntılar)
_s = tuple(int(x) for x in marka.SURUM.split(".")) + (0,)
SURUM_DOSYASI = os.path.join("build", "surum_bilgisi.txt")
os.makedirs("build", exist_ok=True)
with open(SURUM_DOSYASI, "w", encoding="utf-8") as f:
    f.write(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={_s}, prodvers={_s}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('041F04B0', [
      StringStruct('CompanyName', '{marka.SIRKET}'),
      StringStruct('FileDescription', '{marka.URUN}'),
      StringStruct('FileVersion', '{marka.SURUM}'),
      StringStruct('InternalName', 'AlamountRPA'),
      StringStruct('LegalCopyright', '© {marka.SIRKET}'),
      StringStruct('OriginalFilename', '{marka.EXE}'),
      StringStruct('ProductName', '{marka.URUN}'),
      StringStruct('ProductVersion', '{marka.SURUM}')])]),
    VarFileInfo([VarStruct('Translation', [0x041F, 1200])])])
""")

RPA_MODULLERI = (
    "RPA.Windows", "RPA.Desktop", "RPA.Browser.Selenium", "RPA.Browser.common", "RPA.Excel",
    "RPA.FileSystem", "RPA.PDF", "RPA.Tables", "RPA.core",
    # bağlayıcılar: e-posta, Outlook/Exchange, SAP GUI, veritabanı, REST, FTP, Azure, Microsoft 365, Salesforce, Word
    "RPA.Email", "RPA.Outlook", "RPA.SAP", "RPA.Database", "RPA.HTTP", "RPA.FTP", "RPA.Cloud.Azure", "RPA.MSGraph",
    "RPA.Salesforce", "RPA.JSON", "RPA.Archive", "RPA.Word", "RPA.Crypto", "RPA.Calendar", "RPA.Notifier",
)


def guvenli(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # Windows'a özgü paketler Linux'ta yoktur
        print("atlandı:", a, e)
        return []


hidden = [
    "pca_analiz", "ayarlar", "belge_ocr", "ise_giris", "llm_katmani", "mcp_sunucu", "AlamountRPA",
    "ajan", "merkez_sunucu", "merkez_db", "merkez_panel", "merkez_istemci", "bildirim", "cron", "surecler",
    "kuyruk_isleri", "marka", "merkez_mcp", "mcp_kopru", "AlamountGoruntu", "AlamountBaglayicilar",
    "goruntu_araclari", "oturum", "PIL.ImageTk", "PIL._tkinter_finder",
    "robot.libraries.BuiltIn", "robot.libraries.OperatingSystem", "robot.libraries.Collections",
    "robot.libraries.Process", "robot.libraries.String", "robot.libraries.DateTime",
    "robot.libraries.Screenshot", "robot.libraries.XML",
]
hidden += guvenli(collect_submodules, "robot")
hidden += guvenli(collect_submodules, "SeleniumLibrary")
hidden += guvenli(collect_submodules, "selenium")
hidden += guvenli(collect_submodules, "webdriver_manager")
hidden += guvenli(collect_submodules, "RPA", filter=lambda n: n.startswith(RPA_MODULLERI) or any(m.startswith(n + ".") for m in RPA_MODULLERI))
hidden += guvenli(collect_submodules, "uiautomation")
hidden += guvenli(collect_submodules, "comtypes")
hidden += guvenli(collect_submodules, "mcp", filter=lambda n: not n.startswith("mcp.cli"))
hidden += guvenli(collect_submodules, "anthropic")
# görüntü otomasyonu (ekran görüntüsü, fare/klavye) ve bağlayıcıların bağımlılıkları
for paket in ("mss", "pynput", "RequestsLibrary", "exchangelib", "O365", "simple_salesforce", "pyodbc", "psycopg2",
              "oracledb", "pymysql"):
    hidden += guvenli(collect_submodules, paket)
for paket in ("uvicorn", "starlette", "anyio", "h11", "python_multipart", "multipart"):
    hidden += guvenli(collect_submodules, paket)

datas = [("marka/logo.png", "marka"), ("marka/logo_koyu.png", "marka"), ("marka/favicon.png", "marka"),
         ("marka/simge.png", "marka"), ("marka/alamount.ico", "marka")]
for paket in ("robot", "SeleniumLibrary", "selenium", "webdriver_manager", "RPA", "uiautomation", "certifi", "mcp",
              "exchangelib", "O365", "tzlocal", "oracledb"):
    datas += guvenli(collect_data_files, paket)
binaries = []
for paket in ("uiautomation", "cv2", "pymupdf"):
    binaries += guvenli(collect_dynamic_libs, paket)

a = Analysis(
    ["alamount_rpa.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["IPython", "jupyter", "notebook", "pytest"],  # tkinter: şablon yakalama aracı ve demo kullanır
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AlamountRPA", console=True, upx=False,
          icon="marka/alamount.ico", version=SURUM_DOSYASI)
coll = COLLECT(exe, a.binaries, a.datas, name="AlamountRPA", upx=False)
