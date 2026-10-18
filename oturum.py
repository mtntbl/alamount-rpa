# -*- coding: utf-8 -*-
"""
Gözetimsiz robot: Windows oturumunu robot kendisi açar ve açık tutar.

  AlamountRPA.exe oturum-kur --kullanici .\\robot1      (yönetici olarak; parola sorulur ya da kasadan alınır)
  AlamountRPA.exe oturum-durum
  AlamountRPA.exe oturum-kaldir

Nasıl çalışır:
  * Parola, Windows'un otomatik oturum açma için kullandığı LSA gizli alanında şifreli saklanır
    (Sysinternals Autologon ile aynı yöntem; kayıt defterinde düz metin parola yoktur).
  * Bilgisayar açılınca ve oturum kapatılınca Windows robot kullanıcısıyla kendiliğinden oturum açar.
  * Robot ajanı bu oturumda, oturum açılınca başlayan zamanlanmış görevle çalışır.
  * Oturum gözetmeni (SYSTEM olarak çalışır) her 20 saniyede bir bakar:
      - biri RDP ile bağlanıp pencereyi kapattıysa oturumu konsola geri bağlar (kilitsiz),
      - oturum kilitlendiyse ve robot boştaysa oturumu kapatır; Windows temiz bir oturumla yeniden açar,
      - parola merkezin kasasından geliyorsa ve değiştiyse LSA'daki parolayı günceller.
"""

import json
import logging
import os
import subprocess
import sys
import time
from xml.sax.saxutils import escape

log = logging.getLogger("alamount")

WINLOGON = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
GOREV_AJAN = "AlamountRPA_Ajan"
GOREV_GOZETMEN = "AlamountRPA_OturumGozetmeni"
DURUMLAR = {0: "aktif", 1: "bagli", 2: "sorgu", 3: "golge", 4: "bagli_degil", 5: "bosta", 6: "dinliyor",
            7: "sifirlaniyor", 8: "kapali", 9: "baslatiliyor"}


# ====================================================================== saf mantık (her platformda test edilir)


def kullanici_coz(kullanici, bilgisayar=None):
    """'.\\robot1', 'MAKINE\\robot1', 'ALAN\\robot1', 'robot1@alan.com', 'robot1' → (alan, ad)."""
    bilgisayar = bilgisayar or os.environ.get("COMPUTERNAME", "")
    k = str(kullanici).strip()
    if not k:
        raise ValueError("Kullanıcı adı boş")
    if "\\" in k:
        alan, ad = k.split("\\", 1)
        return (bilgisayar if alan in (".", "") else alan), ad
    if "@" in k:
        return "", k
    return bilgisayar, k


def ayni_kullanici(oturum, kullanici, bilgisayar=None):
    alan, ad = kullanici_coz(kullanici, bilgisayar)
    if "@" in ad:
        return oturum.get("kullanici", "").lower() == ad.split("@")[0].lower()
    return oturum.get("kullanici", "").lower() == ad.lower() and \
        (not alan or not oturum.get("alan") or oturum["alan"].lower() == alan.lower())


def karar(oturumlar, kullanici, ajan_durumu, simdi, kilit_ilk=None, kilit_bekleme_sn=60, yeniden_ac=True,
          bilgisayar=None):
    """Gözetmenin ne yapacağı: (eylem, oturum_id, açıklama).
    eylem: 'tamam' | 'bekle' | 'konsola_bagla' | 'oturumu_kapat'"""
    benim = [o for o in oturumlar if o.get("kullanici") and ayni_kullanici(o, kullanici, bilgisayar)]
    if not benim:
        return "bekle", None, "Robot oturumu yok; Windows'un otomatik oturum açması bekleniyor"
    benim.sort(key=lambda o: (o["durum"] != "aktif", o["durum"] != "bagli_degil", o["id"]))
    o = benim[0]
    if o["durum"] == "bagli_degil":
        baskasi = [x for x in oturumlar if x["durum"] == "aktif" and x.get("istasyon", "").lower() == "console"
                   and x.get("kullanici") and not ayni_kullanici(x, kullanici, bilgisayar)]
        if baskasi:
            return "bekle", o["id"], (f"Robot oturumu bağlı değil ama konsolda {baskasi[0]['kullanici']} çalışıyor; "
                                      f"dokunulmadı")
        return "konsola_bagla", o["id"], "Robot oturumu bağlı değildi (RDP kapatıldı); konsola geri bağlanıyor"
    if o.get("kilitli"):
        if not yeniden_ac:
            return "bekle", o["id"], "Robot oturumu kilitli (kilitliyken_yeniden_ac = hayir)"
        if ajan_durumu and ajan_durumu.get("mesgul") and simdi - float(ajan_durumu.get("zaman", 0)) < 120:
            return "bekle", o["id"], "Robot oturumu kilitli ama robot çalışıyor; iş bitince yeniden açılacak"
        if kilit_ilk is None or simdi - kilit_ilk < kilit_bekleme_sn:
            return "bekle", o["id"], "Robot oturumu kilitli; biraz bekleniyor"
        return "oturumu_kapat", o["id"], "Robot oturumu kilitli ve robot boşta; temiz oturum için kapatılıyor"
    return "tamam", o["id"], "Robot oturumu açık"


def gorev_xml(aciklama, komut, argumanlar, calisma_klasoru, kullanici=None):
    """Görev Zamanlayıcı tanımı. kullanici verilirse: o kullanıcı oturum açınca, oturumunda (masaüstü erişimli);
    verilmezse: bilgisayar açılınca SYSTEM olarak."""
    if kullanici:
        tetik = f"<LogonTrigger><Enabled>true</Enabled><UserId>{escape(kullanici)}</UserId><Delay>PT10S</Delay></LogonTrigger>"
        kim = (f"<UserId>{escape(kullanici)}</UserId><LogonType>InteractiveToken</LogonType>"
               f"<RunLevel>LeastPrivilege</RunLevel>")
    else:
        tetik = "<BootTrigger><Enabled>true</Enabled><Delay>PT30S</Delay></BootTrigger>"
        kim = "<UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel>"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>Alamount RPA</Author><Description>{escape(aciklama)}</Description></RegistrationInfo>
  <Triggers>{tetik}</Triggers>
  <Principals><Principal id="Author">{kim}</Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
    <StartWhenAvailable>true</StartWhenAvailable>
    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escape(komut)}</Command><Arguments>{escape(argumanlar)}</Arguments>
    <WorkingDirectory>{escape(calisma_klasoru)}</WorkingDirectory></Exec></Actions>
</Task>
"""


def exe_komutu(config_yolu, alt_komut):
    """(komut, argümanlar) — paketlenmiş exe ya da geliştirme ortamında python alamount_rpa.py."""
    cfg = f'--config "{os.path.abspath(config_yolu)}" {alt_komut}'
    if getattr(sys, "frozen", False):
        return sys.executable, cfg
    betik = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alamount_rpa.py")
    return sys.executable, f'"{betik}" {cfg}'


def ajan_durum_dosyasi(ayarlar):
    return os.path.join(ayarlar.folder("log"), "ajan_durum.json")


def ajan_durumunu_yaz(ayarlar, mesgul, oturum_durumu):
    try:
        with open(ajan_durum_dosyasi(ayarlar), "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "mesgul": bool(mesgul), "oturum": oturum_durumu, "zaman": time.time()}, f)
    except OSError:
        pass


def ajan_durumunu_oku(ayarlar):
    try:
        with open(ajan_durum_dosyasi(ayarlar), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ====================================================================== Windows API

if os.name == "nt":
    import ctypes
    import ctypes.wintypes as w

    _wtsapi = ctypes.WinDLL("wtsapi32", use_last_error=True)
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _u32 = ctypes.WinDLL("user32", use_last_error=True)

    class _WTS_SESSION_INFOW(ctypes.Structure):
        _fields_ = [("SessionId", w.DWORD), ("pWinStationName", w.LPWSTR), ("State", ctypes.c_int)]

    class _WTSINFOEX_LEVEL1_W(ctypes.Structure):
        _fields_ = [("SessionId", w.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", w.LONG),
                    ("WinStationName", w.WCHAR * 33), ("UserName", w.WCHAR * 21), ("DomainName", w.WCHAR * 18),
                    ("LogonTime", w.LARGE_INTEGER), ("ConnectTime", w.LARGE_INTEGER),
                    ("DisconnectTime", w.LARGE_INTEGER), ("LastInputTime", w.LARGE_INTEGER),
                    ("CurrentTime", w.LARGE_INTEGER), ("IncomingBytes", w.DWORD), ("OutgoingBytes", w.DWORD),
                    ("IncomingFrames", w.DWORD), ("OutgoingFrames", w.DWORD),
                    ("IncomingCompressedBytes", w.DWORD), ("OutgoingCompressedBytes", w.DWORD)]

    class _WTSINFOEX_LEVEL_W(ctypes.Union):
        _fields_ = [("Level1", _WTSINFOEX_LEVEL1_W)]

    class _WTSINFOEXW(ctypes.Structure):
        _fields_ = [("Level", w.DWORD), ("Data", _WTSINFOEX_LEVEL_W)]

    class _LSA_UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", w.USHORT), ("MaximumLength", w.USHORT), ("Buffer", ctypes.c_void_p)]

    class _LSA_OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Length", w.ULONG), ("RootDirectory", w.HANDLE), ("ObjectName", ctypes.c_void_p),
                    ("Attributes", w.ULONG), ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]

    _wtsapi.WTSEnumerateSessionsW.argtypes = [w.HANDLE, w.DWORD, w.DWORD,
                                              ctypes.POINTER(ctypes.POINTER(_WTS_SESSION_INFOW)),
                                              ctypes.POINTER(w.DWORD)]
    _wtsapi.WTSQuerySessionInformationW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p),
                                                    ctypes.POINTER(w.DWORD)]
    _wtsapi.WTSFreeMemory.argtypes = [ctypes.c_void_p]
    _wtsapi.WTSLogoffSession.argtypes = [w.HANDLE, w.DWORD, w.BOOL]
    _advapi.LsaOpenPolicy.argtypes = [ctypes.c_void_p, ctypes.POINTER(_LSA_OBJECT_ATTRIBUTES), w.DWORD,
                                      ctypes.POINTER(w.HANDLE)]
    _advapi.LsaOpenPolicy.restype = w.ULONG
    _advapi.LsaStorePrivateData.argtypes = [w.HANDLE, ctypes.POINTER(_LSA_UNICODE_STRING),
                                            ctypes.POINTER(_LSA_UNICODE_STRING)]
    _advapi.LsaStorePrivateData.restype = w.ULONG
    _advapi.LsaRetrievePrivateData.argtypes = [w.HANDLE, ctypes.POINTER(_LSA_UNICODE_STRING),
                                               ctypes.POINTER(ctypes.POINTER(_LSA_UNICODE_STRING))]
    _advapi.LsaRetrievePrivateData.restype = w.ULONG
    _advapi.LsaNtStatusToWinError.argtypes = [w.ULONG]
    _advapi.LsaNtStatusToWinError.restype = w.ULONG
    _advapi.LsaFreeMemory.argtypes = [ctypes.c_void_p]
    _advapi.LsaClose.argtypes = [w.HANDLE]
    _advapi.LogonUserW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, w.DWORD, ctypes.POINTER(w.HANDLE)]
    _k32.ProcessIdToSessionId.argtypes = [w.DWORD, ctypes.POINTER(w.DWORD)]
    _k32.SetThreadExecutionState.argtypes = [w.DWORD]
    _k32.SetThreadExecutionState.restype = w.DWORD


def _windows():
    if os.name != "nt":
        raise RuntimeError("Bu komut yalnızca Windows'ta çalışır")


def _wts_dize(oturum_id, sinif):
    tampon, boy = ctypes.c_void_p(), w.DWORD()
    if not _wtsapi.WTSQuerySessionInformationW(0, oturum_id, sinif, ctypes.byref(tampon), ctypes.byref(boy)):
        return ""
    try:
        return ctypes.wstring_at(tampon.value) if tampon.value else ""
    finally:
        _wtsapi.WTSFreeMemory(tampon)


def _kilit_bayragi(oturum_id):
    """True: kilitli, False: açık, None: bilinmiyor (WTSSessionInfoEx)."""
    tampon, boy = ctypes.c_void_p(), w.DWORD()
    if not _wtsapi.WTSQuerySessionInformationW(0, oturum_id, 25, ctypes.byref(tampon), ctypes.byref(boy)):
        return None
    try:
        bilgi = ctypes.cast(tampon, ctypes.POINTER(_WTSINFOEXW)).contents
        bayrak = bilgi.Data.Level1.SessionFlags
        return {0: True, 1: False}.get(bayrak)
    finally:
        _wtsapi.WTSFreeMemory(tampon)


def oturumlar():
    """Bu bilgisayardaki oturumlar: [{id, kullanici, alan, durum, istasyon, kilitli}]."""
    _windows()
    dizi, adet = ctypes.POINTER(_WTS_SESSION_INFOW)(), w.DWORD()
    if not _wtsapi.WTSEnumerateSessionsW(0, 0, 1, ctypes.byref(dizi), ctypes.byref(adet)):
        raise OSError(ctypes.get_last_error(), "WTSEnumerateSessions başarısız")
    try:
        liste = []
        for i in range(adet.value):
            s = dizi[i]
            kullanici = _wts_dize(s.SessionId, 5)
            liste.append({"id": int(s.SessionId), "kullanici": kullanici, "alan": _wts_dize(s.SessionId, 7),
                          "durum": DURUMLAR.get(s.State, str(s.State)), "istasyon": s.pWinStationName or "",
                          "kilitli": _kilit_bayragi(s.SessionId) if kullanici else None})
        return liste
    finally:
        _wtsapi.WTSFreeMemory(dizi)


def bu_oturum_id():
    _windows()
    sid = w.DWORD()
    _k32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def bu_oturum_durumu():
    """Ajanın kendi oturumu: 'acik' | 'kilitli' | 'servis' (oturum 0) | 'bilinmiyor'."""
    if os.name != "nt":
        return "bilinmiyor"
    try:
        sid = bu_oturum_id()
        if sid == 0:
            return "servis"
        kilit = _kilit_bayragi(sid)
        if kilit is None:  # eski sürümler: giriş masaüstü açılamıyorsa kilitlidir
            h = _u32.OpenInputDesktop(0, False, 0x0100)
            if not h:
                return "kilitli"
            _u32.CloseDesktop(h)
            return "acik"
        return "kilitli" if kilit else "acik"
    except Exception:
        return "bilinmiyor"


def konsola_bagla(oturum_id):
    """Bağlantısı kopmuş oturumu fiziksel konsola bağlar (kilit ekranı olmadan). SYSTEM yetkisi gerekir."""
    tscon = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tscon.exe")
    r = subprocess.run([tscon, str(oturum_id), "/dest:console"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise OSError(f"tscon başarısız ({r.returncode}): {(r.stdout + r.stderr).strip()}")


def oturumu_kapat(oturum_id):
    if not _wtsapi.WTSLogoffSession(0, oturum_id, False):
        raise OSError(ctypes.get_last_error(), "WTSLogoffSession başarısız")


def bosta_sure_sn():
    """Son klavye/fare hareketinden beri geçen süre."""
    if os.name != "nt":
        return 0.0
    li = _LASTINPUTINFO(ctypes.sizeof(_LASTINPUTINFO), 0)
    if not _u32.GetLastInputInfo(ctypes.byref(li)):
        return 0.0
    return ((_k32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0


def uyanik_tut_baslat():
    """Bu iş parçacığı yaşadıkça bilgisayar uyku moduna geçmez, ekran kapanmaz."""
    if os.name == "nt":
        _k32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)  # CONTINUOUS|SYSTEM|DISPLAY


def bosta_tusu_gonder():
    """Ekran koruyucu/kilit zamanlayıcısını sıfırlar: F15 (klavyelerde olmayan, uygulamaların görmezden geldiği tuş)."""
    if os.name == "nt":
        _u32.keybd_event(0x7E, 0, 0, 0)
        _u32.keybd_event(0x7E, 0, 2, 0)


# ---------------------------------------------------------------------- LSA gizli alanı


def _lsa_dize(metin):
    tampon = ctypes.create_unicode_buffer(metin)
    boy = len(metin.encode("utf-16-le"))
    return _LSA_UNICODE_STRING(boy, boy + 2, ctypes.cast(tampon, ctypes.c_void_p)), tampon


def _lsa_ac(erisim):
    _windows()
    nitelik = _LSA_OBJECT_ATTRIBUTES()
    nitelik.Length = ctypes.sizeof(nitelik)
    h = w.HANDLE()
    durum = _advapi.LsaOpenPolicy(None, ctypes.byref(nitelik), erisim, ctypes.byref(h))
    if durum:
        raise OSError(_advapi.LsaNtStatusToWinError(durum), "LSA açılamadı (yönetici olarak çalıştırın)")
    return h


def lsa_gizli_yaz(ad, deger):
    """deger=None gizli alanı siler."""
    h = _lsa_ac(0x00000020 | 0x00000004)  # POLICY_CREATE_SECRET | POLICY_GET_PRIVATE_INFORMATION
    try:
        anahtar, _t1 = _lsa_dize(ad)
        if deger is None:
            durum = _advapi.LsaStorePrivateData(h, ctypes.byref(anahtar), None)
            if durum and durum != 0xC0000034:  # STATUS_OBJECT_NAME_NOT_FOUND: zaten yok
                raise OSError(_advapi.LsaNtStatusToWinError(durum), "LSA gizli alanı silinemedi")
            return
        veri, _t2 = _lsa_dize(deger)
        durum = _advapi.LsaStorePrivateData(h, ctypes.byref(anahtar), ctypes.byref(veri))
        if durum:
            raise OSError(_advapi.LsaNtStatusToWinError(durum), "LSA gizli alanına yazılamadı")
    finally:
        _advapi.LsaClose(h)


def lsa_gizli_oku(ad):
    """Gizli alanın değeri; yoksa None."""
    h = _lsa_ac(0x00000004)
    try:
        anahtar, _t = _lsa_dize(ad)
        p = ctypes.POINTER(_LSA_UNICODE_STRING)()
        durum = _advapi.LsaRetrievePrivateData(h, ctypes.byref(anahtar), ctypes.byref(p))
        if durum == 0xC0000034:
            return None
        if durum:
            raise OSError(_advapi.LsaNtStatusToWinError(durum), "LSA gizli alanı okunamadı")
        try:
            return ctypes.wstring_at(p.contents.Buffer, p.contents.Length // 2) if p else None
        finally:
            _advapi.LsaFreeMemory(p)
    finally:
        _advapi.LsaClose(h)


def parolayi_dogrula(kullanici, parola):
    """Windows'a gerçekten giriş yapılabiliyor mu? (Yanlış parolayla otomatik oturum açmayı kurmamak için.)"""
    _windows()
    alan, ad = kullanici_coz(kullanici)
    token = w.HANDLE()
    if not _advapi.LogonUserW(ad, alan or None, parola, 2, 0, ctypes.byref(token)):  # INTERACTIVE, DEFAULT
        kod = ctypes.get_last_error()
        aciklama = {1326: "kullanıcı adı ya da parola yanlış", 1385: "bu kullanıcının yerel oturum açma izni yok",
                    1331: "hesap devre dışı", 1909: "hesap kilitli", 1330: "parolanın süresi dolmuş"}
        raise ValueError(f"Windows girişi doğrulanamadı: {aciklama.get(kod, f'hata {kod}')}")
    _k32.CloseHandle(token)


# ---------------------------------------------------------------------- otomatik oturum açma


def autologon_ayarla(kullanici, parola, yeniden_giris=True):
    import winreg

    alan, ad = kullanici_coz(kullanici)
    lsa_gizli_yaz("DefaultPassword", parola)
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINLOGON, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, "AutoAdminLogon", 0, winreg.REG_SZ, "1")
        winreg.SetValueEx(k, "DefaultUserName", 0, winreg.REG_SZ, ad)
        winreg.SetValueEx(k, "DefaultDomainName", 0, winreg.REG_SZ, alan)
        winreg.SetValueEx(k, "ForceAutoLogon", 0, winreg.REG_SZ, "1" if yeniden_giris else "0")
        for eski in ("DefaultPassword", "AutoLogonCount"):  # düz metin parola ve sayaç kalmasın
            try:
                winreg.DeleteValue(k, eski)
            except FileNotFoundError:
                pass


def autologon_kaldir():
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINLOGON, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
        winreg.SetValueEx(k, "AutoAdminLogon", 0, winreg.REG_SZ, "0")
        for ad in ("ForceAutoLogon", "DefaultPassword", "AutoLogonCount"):
            try:
                winreg.DeleteValue(k, ad)
            except FileNotFoundError:
                pass
    lsa_gizli_yaz("DefaultPassword", None)


def autologon_durumu():
    import winreg

    d = {}
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, WINLOGON, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
        for ad in ("AutoAdminLogon", "DefaultUserName", "DefaultDomainName", "ForceAutoLogon", "DefaultPassword"):
            try:
                d[ad] = winreg.QueryValueEx(k, ad)[0]
            except FileNotFoundError:
                d[ad] = None
    try:
        d["lsa_parola"] = bool(lsa_gizli_oku("DefaultPassword"))
    except OSError as e:
        d["lsa_parola"] = f"okunamadı ({e})"
    return d


# ---------------------------------------------------------------------- zamanlanmış görevler


def gorev_olustur(ad, xml):
    import tempfile

    yol = os.path.join(tempfile.gettempdir(), f"{ad}.xml")
    with open(yol, "w", encoding="utf-16") as f:
        f.write(xml)
    try:
        r = subprocess.run(["schtasks", "/Create", "/F", "/TN", ad, "/XML", yol], capture_output=True, text=True,
                           timeout=60)
        if r.returncode != 0:
            raise OSError(f"Görev oluşturulamadı ({ad}): {(r.stdout + r.stderr).strip()}")
    finally:
        os.remove(yol)


def gorev_var_mi(ad):
    return subprocess.run(["schtasks", "/Query", "/TN", ad], capture_output=True, timeout=60).returncode == 0


def gorev_sil(ad):
    subprocess.run(["schtasks", "/End", "/TN", ad], capture_output=True, timeout=60)  # çalışan kopyayı durdur
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", ad], capture_output=True, timeout=60)


def gorev_calistir(ad):
    subprocess.run(["schtasks", "/Run", "/TN", ad], capture_output=True, timeout=60)


# ---------------------------------------------------------------------- config.ini


def config_bolumunu_yaz(config_yolu, degerler):
    """[OTURUM] bölümündeki anahtarları yorumları bozmadan günceller (yoksa ekler)."""
    import re

    with open(config_yolu, encoding="utf-8-sig") as f:
        metin = f.read()
    m = re.search(r"(?ms)^\[OTURUM\][^\n]*\n(.*?)(?=^\[|\Z)", metin)
    if not m:
        metin = metin.rstrip("\n") + "\n\n[OTURUM]\n" + "".join(f"{k} = {v}\n" for k, v in degerler.items())
    else:
        govde = m.group(1)
        for k, v in degerler.items():
            desen = re.compile(rf"(?m)^{re.escape(k)}\s*=.*$")
            satir = f"{k} = {v}"
            govde = desen.sub(lambda _m: satir, govde, count=1) if desen.search(govde) else govde + satir + "\n"
        metin = metin[:m.start(1)] + govde + metin[m.end(1):]
    with open(config_yolu, "w", encoding="utf-8") as f:
        f.write(metin)


# ====================================================================== komutlar


def _yonetici_mi():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _kasadan_parola(ayarlar, varlik):
    from merkez_istemci import MerkezIstemci

    return MerkezIstemci.ayarlardan(ayarlar).varlik(varlik)["deger"]


def kur(ayarlar, kullanici, parola=None, parola_varligi="", yeniden_giris=True, ajani_baslat=True):
    _windows()
    if not _yonetici_mi():
        print("Bu komut yönetici olarak çalıştırılmalı (komut istemine sağ tık > Yönetici olarak çalıştır).")
        return 1
    if parola_varligi:
        parola = _kasadan_parola(ayarlar, parola_varligi)
        print(f"Parola merkezin kasasından alındı ({parola_varligi}).")
    if not parola:
        import getpass

        parola = getpass.getpass(f"{kullanici} için Windows parolası: ")
    parolayi_dogrula(kullanici, parola)
    print("Windows girişi doğrulandı.")
    alan, ad = kullanici_coz(kullanici)
    tam_ad = f"{alan}\\{ad}" if alan else ad
    autologon_ayarla(kullanici, parola, yeniden_giris)
    print("Otomatik oturum açma ayarlandı (parola LSA'da şifreli; kayıt defterinde düz metin yok).")
    klasor = os.path.dirname(os.path.abspath(ayarlar.path))
    komut, arg = exe_komutu(ayarlar.path, "ajan")
    gorev_olustur(GOREV_AJAN, gorev_xml(f"Alamount RPA robot ajanı ({tam_ad} oturumunda)", komut, arg, klasor,
                                        tam_ad))
    komut, arg = exe_komutu(ayarlar.path, "oturum-gozetmen")
    gorev_olustur(GOREV_GOZETMEN, gorev_xml("Alamount RPA oturum gözetmeni (robot oturumunu açık tutar)", komut, arg,
                                            klasor))
    print(f"Zamanlanmış görevler oluşturuldu: {GOREV_AJAN} (oturum açılınca), {GOREV_GOZETMEN} (açılışta, SYSTEM)")
    config_bolumunu_yaz(ayarlar.path, {"mod": "autologon", "kullanici": tam_ad, "parola_varligi": parola_varligi,
                                       "kilitliyken_is_al": "hayir"})
    for komut_satiri in (["powercfg", "/change", "standby-timeout-ac", "0"],
                         ["powercfg", "/change", "hibernate-timeout-ac", "0"]):
        subprocess.run(komut_satiri, capture_output=True, timeout=30)
    print("Uyku modu (prizde) kapatıldı.")
    if ajani_baslat:
        gorev_calistir(GOREV_GOZETMEN)
    print("\nHazır. Bilgisayar yeniden başlatıldığında robot kendi oturumunu açar ve ajan çalışmaya başlar.\n"
          "Şimdi denemek için: bilgisayarı yeniden başlatın (ya da oturumu kapatın).")
    return 0


def kaldir(ayarlar):
    _windows()
    if not _yonetici_mi():
        print("Bu komut yönetici olarak çalıştırılmalı.")
        return 1
    autologon_kaldir()
    for g in (GOREV_GOZETMEN, GOREV_AJAN):
        gorev_sil(g)
    config_bolumunu_yaz(ayarlar.path, {"mod": "yok"})
    print("Otomatik oturum açma kapatıldı, LSA'daki parola silindi, görevler kaldırıldı.")
    return 0


def durum(ayarlar):
    _windows()
    kullanici = ayarlar.get("OTURUM", "kullanici")
    print(f"Mod: {ayarlar.get('OTURUM', 'mod') or 'yok'}   Robot kullanıcısı: {kullanici or '-'}")
    try:
        a = autologon_durumu()
        print(f"Otomatik oturum açma: {'AÇIK' if a['AutoAdminLogon'] == '1' else 'kapalı'}  "
              f"kullanıcı: {a['DefaultDomainName'] or ''}\\{a['DefaultUserName'] or ''}  "
              f"yeniden giriş: {'evet' if a['ForceAutoLogon'] == '1' else 'hayır'}  "
              f"LSA parola: {a['lsa_parola']}"
              + ("  ! Kayıt defterinde düz metin parola var" if a["DefaultPassword"] else ""))
    except OSError as e:
        print(f"Otomatik oturum açma okunamadı: {e}")
    for g in (GOREV_AJAN, GOREV_GOZETMEN):
        print(f"Görev {g}: {'var' if gorev_var_mi(g) else 'YOK'}")
    print("\nOturumlar:")
    for o in oturumlar():
        if o["kullanici"] or o["durum"] in ("aktif", "bagli_degil"):
            isaret = " ← robot" if kullanici and o["kullanici"] and ayni_kullanici(o, kullanici) else ""
            kilit = {True: "kilitli", False: "açık", None: "-"}[o["kilitli"]]
            print(f"  #{o['id']:<3} {o['istasyon']:<14} {o['durum']:<12} {kilit:<8} "
                  f"{o['alan']}\\{o['kullanici']}{isaret}")
    a = ajan_durumunu_oku(ayarlar)
    if a:
        print(f"\nAjan: {'meşgul' if a['mesgul'] else 'boşta'}, oturum {a['oturum']}, "
              f"{int(time.time() - a['zaman'])} sn önce")
    return 0


def gozetmen(ayarlar, tek_sefer=False, aralik=20):
    """SYSTEM olarak sürekli çalışır; robot oturumunu açık ve kilitsiz tutar."""
    _windows()
    kullanici = ayarlar.get("OTURUM", "kullanici")
    if not kullanici:
        log.error("[OTURUM] kullanici boş; önce: AlamountRPA.exe oturum-kur --kullanici .\\robot1")
        return 1
    yeniden_ac = ayarlar.getbool("OTURUM", "kilitliyken_yeniden_ac")
    varlik = ayarlar.get("OTURUM", "parola_varligi")
    log.info("Oturum gözetmeni başladı: %s (oturum %s)", kullanici, bu_oturum_id())
    kilit_ilk, son_aciklama, son_parola_kontrol = None, None, 0.0
    while True:
        try:
            liste = oturumlar()
            eylem, oid, aciklama = karar(liste, kullanici, ajan_durumunu_oku(ayarlar), time.time(), kilit_ilk,
                                         ayarlar.getint("OTURUM", "kilit_bekleme_sn"), yeniden_ac)
            robot_oturumu = next((o for o in liste if o["id"] == oid), None)
            kilit_ilk = (kilit_ilk or time.time()) if robot_oturumu and robot_oturumu.get("kilitli") else None
            if aciklama != son_aciklama:
                (log.info if eylem in ("tamam", "bekle") else log.warning)("%s", aciklama)
                son_aciklama = aciklama
            if eylem == "konsola_bagla":
                konsola_bagla(oid)
            elif eylem == "oturumu_kapat":
                oturumu_kapat(oid)
                kilit_ilk = None
            if varlik and time.time() - son_parola_kontrol > 6 * 3600:
                son_parola_kontrol = time.time()
                yeni = _kasadan_parola(ayarlar, varlik)
                if yeni and yeni != lsa_gizli_oku("DefaultPassword"):
                    lsa_gizli_yaz("DefaultPassword", yeni)
                    log.warning("Robot parolası kasada değişmiş; otomatik oturum açma parolası güncellendi")
        except Exception as e:
            log.error("Oturum gözetmeni: %s", e)
        if tek_sefer:
            return 0
        time.sleep(aralik)
