# -*- coding: utf-8 -*-
"""
Görüntü tabanlı otomasyon — Citrix, RDP, VDI ve UI Automation'ın göremediği ekranlar için.
.robot görevlerinde:   Library    AlamountGoruntu

Ekranı piksel olarak görür: bir şablon görüntüsünü (OpenCV, çok ölçekli eşleme) ya da bir yazıyı
(Tesseract OCR, Türkçe) bulur; fareyi ve klavyeyi gerçek bir kullanıcı gibi kullanır.
Şablonlar görev klasöründeki goruntuler\\ altında durur ve ekrandan şöyle kesilir:
    AlamountRPA.exe goruntu-yakala giris_dugmesi
"""

import datetime as dt
import difflib
import os
import re
import sys
import time

import cv2
import numpy as np

# Ekran ölçeklendirmesi (%100/%125/%150) ve Citrix çözünürlük farkları için denenen ölçekler
OLCEKLER = (1.0, 0.9, 1.1, 0.8, 1.25, 0.75, 1.5, 0.67, 2.0, 0.5)
_TR = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def dpi_farkinda_ol():
    """Windows'ta ekran görüntüsü ve fare koordinatları aynı (fiziksel) piksel biriminde olsun."""
    if os.name == "nt":
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


def resim_oku(yol):
    """Türkçe karakterli yollarda da çalışır (cv2.imread Windows'ta çalışmaz)."""
    veri = np.fromfile(yol, dtype=np.uint8)
    img = cv2.imdecode(veri, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Görüntü okunamadı: {yol}")
    return img


def resim_yaz(yol, img):
    os.makedirs(os.path.dirname(os.path.abspath(yol)), exist_ok=True)
    ok, veri = cv2.imencode(".png", img)
    if not ok:
        raise ValueError(f"Görüntü yazılamadı: {yol}")
    veri.tofile(yol)
    return yol


def _gri(img):
    return img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _cakisma(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    kesisim = max(0, x2 - x1) * max(0, y2 - y1)
    return kesisim / float(min(a[2] * a[3], b[2] * b[3]) or 1)


def sablon_eslesmeleri(ekran, sablon, guven=0.85, olcekler=OLCEKLER, renkli=False, en_fazla=50):
    """Şablonun ekrandaki yerleri: [(x, y, genişlik, yükseklik, skor)], en iyi eşleşme önce.
    Önce gerçek boyutta arar; orada çok iyi bir eşleşme yoksa diğer ölçekleri de dener."""
    e = ekran if renkli else _gri(ekran)
    s0 = sablon if renkli else _gri(sablon)
    adaylar = []
    for o in olcekler:
        s = s0 if o == 1.0 else cv2.resize(s0, None, fx=o, fy=o,
                                           interpolation=cv2.INTER_AREA if o < 1 else cv2.INTER_CUBIC)
        h, w = s.shape[:2]
        if h < 4 or w < 4 or h > e.shape[0] or w > e.shape[1]:
            continue
        if float(s.std()) < 1.0:  # düz renkli şablonda korelasyon tanımsız: fark yöntemi
            r = 1.0 - cv2.matchTemplate(e, s, cv2.TM_SQDIFF_NORMED)
        else:
            r = cv2.matchTemplate(e, s, cv2.TM_CCOEFF_NORMED)
        r = np.nan_to_num(r, nan=0.0, posinf=0.0, neginf=0.0)
        ys, xs = np.where(r >= guven)
        if len(xs) > 2000:
            skor = r[ys, xs]
            sec = np.argpartition(-skor, 2000)[:2000]
            ys, xs = ys[sec], xs[sec]
        adaylar += [(int(x), int(y), w, h, float(r[y, x])) for x, y in zip(xs, ys)]
        if o == 1.0 and adaylar and max(a[4] for a in adaylar) >= 0.97:
            break
    adaylar.sort(key=lambda a: -a[4])
    secilen = []
    for a in adaylar:
        if all(_cakisma(a, b) < 0.3 for b in secilen):
            secilen.append(a)
            if len(secilen) >= en_fazla:
                break
    return secilen


def normallestir(metin):
    """Büyük/küçük harf, Türkçe karakter ve noktalama farklarını yok sayar (OCR hatalarına dayanıklı)."""
    m = str(metin).replace("İ", "i").replace("I", "ı").lower().translate(_TR)
    return re.sub(r"[\W_]+", " ", m).strip()


def yazi_kelimeleri(ekran, dil="tur+eng", psm=11, olcek=2.0, ters=False):
    """Ekrandaki kelimeler: [{"metin", "x", "y", "w", "h", "guven"}] (ekran görüntüsü koordinatlarında).
    Ekran yazıları küçük olduğundan görüntü büyütülerek okunur."""
    import pytesseract

    g = _gri(ekran)
    if ters:
        g = 255 - g
    if olcek != 1:
        g = cv2.resize(g, None, fx=olcek, fy=olcek, interpolation=cv2.INTER_CUBIC)
    d = pytesseract.image_to_data(g, lang=dil, config=f"--oem 1 --psm {psm}", output_type=pytesseract.Output.DICT)
    kelimeler = []
    for i, t in enumerate(d["text"]):
        t = (t or "").strip()
        guven = float(d["conf"][i])
        if not t or guven < 0:
            continue
        kelimeler.append({"metin": t, "x": d["left"][i] / olcek, "y": d["top"][i] / olcek,
                          "w": d["width"][i] / olcek, "h": d["height"][i] / olcek, "guven": guven})
    return kelimeler


def satirlara_ayir(kelimeler):
    """Kelimeleri konumlarına göre satırlara toplar (psm 11 satır bilgisi vermez)."""
    satirlar = []
    for k in sorted(kelimeler, key=lambda k: k["x"]):
        orta = k["y"] + k["h"] / 2
        for s in satirlar:
            son = s[-1]
            boy = max(son["h"], k["h"])
            bosluk = k["x"] - (son["x"] + son["w"])
            if abs(son["y"] + son["h"] / 2 - orta) < 0.6 * boy and -0.5 * boy <= bosluk < 2.5 * boy:
                s.append(k)
                break
        else:
            satirlar.append([k])
    satirlar.sort(key=lambda s: (round(s[0]["y"] / 8), s[0]["x"]))
    return satirlar


def yazi_eslesmeleri(kelimeler, aranan, benzerlik=0.8):
    """Aranan yazının (bir ya da birkaç kelime) yerleri: [(x, y, w, h, skor, okunan)], en iyi önce."""
    hedef = normallestir(aranan)
    if not hedef:
        raise ValueError("Aranan yazı boş")
    n = len(hedef.split())
    sonuc = []
    for satir in satirlara_ayir(kelimeler):
        normal = [normallestir(k["metin"]) for k in satir]
        for i in range(len(satir)):
            for uzunluk in {max(1, n - 1), n, n + 1}:
                pencere = satir[i:i + uzunluk]
                if len(pencere) < uzunluk:
                    continue
                okunan = " ".join(x for x in normal[i:i + uzunluk] if x)
                if not okunan:
                    continue
                skor = 1.0 if okunan == hedef else difflib.SequenceMatcher(None, okunan, hedef).ratio()
                if skor < benzerlik:
                    continue
                x1 = min(k["x"] for k in pencere)
                y1 = min(k["y"] for k in pencere)
                x2 = max(k["x"] + k["w"] for k in pencere)
                y2 = max(k["y"] + k["h"] for k in pencere)
                sonuc.append((x1, y1, x2 - x1, y2 - y1, skor, " ".join(k["metin"] for k in pencere)))
    sonuc.sort(key=lambda a: (-round(a[4], 3), round(a[1] / 8), a[0]))
    secilen = []
    for a in sonuc:
        if all(_cakisma(a, b) < 0.5 for b in secilen):
            secilen.append(a)
    return secilen


class Ekran:
    """Ekran görüntüsü (mss) + fare/klavye (pynput). Koordinatlar masaüstüne göre mutlak pikseldir."""

    TUSLAR = {
        "ctrl": "ctrl", "control": "ctrl", "kontrol": "ctrl", "alt": "alt", "altgr": "alt_gr", "shift": "shift",
        "win": "cmd", "windows": "cmd", "cmd": "cmd", "enter": "enter", "return": "enter", "giris": "enter",
        "esc": "esc", "escape": "esc", "tab": "tab", "sekme": "tab", "space": "space", "bosluk": "space",
        "backspace": "backspace", "geri": "backspace", "delete": "delete", "del": "delete", "sil": "delete",
        "insert": "insert", "ins": "insert", "home": "home", "end": "end", "pageup": "page_up", "pgup": "page_up",
        "pagedown": "page_down", "pgdn": "page_down", "up": "up", "yukari": "up", "down": "down", "asagi": "down",
        "left": "left", "sol": "left", "right": "right", "sag": "right", "printscreen": "print_screen",
        "capslock": "caps_lock", "menu": "menu",
    }

    def __init__(self, ekran_no=0):
        self.ekran_no = int(ekran_no)
        self._fare = self._klavye = None

    def goruntu(self, bolge=None):
        """(BGR görüntü, (sol, üst)) — bölge (x, y, w, h) mutlak koordinatlarda."""
        import mss

        with mss.mss() as m:
            if bolge:
                x, y, w, h = (int(v) for v in bolge)
                alan = {"left": x, "top": y, "width": w, "height": h}
            else:
                alan = m.monitors[min(self.ekran_no, len(m.monitors) - 1)]
            s = m.grab(alan)
            return np.ascontiguousarray(np.asarray(s)[:, :, :3]), (alan["left"], alan["top"])

    def _araclar(self):
        if self._fare is None:
            from pynput.keyboard import Controller as Klavye
            from pynput.mouse import Controller as Fare

            self._fare, self._klavye = Fare(), Klavye()
        return self._fare, self._klavye

    def fareyi_gotur(self, x, y):
        fare, _ = self._araclar()
        fare.position = (int(round(x)), int(round(y)))
        time.sleep(0.05)

    def tikla(self, x, y, tur="sol"):
        from pynput.mouse import Button

        fare, _ = self._araclar()
        self.fareyi_gotur(x, y)
        tur = normallestir(tur).replace(" ", "")
        if tur in ("sag", "right"):
            fare.click(Button.right, 1)
        elif tur in ("cift", "double", "ciftsol"):
            fare.click(Button.left, 2)
        elif tur in ("sol", "left", ""):
            fare.click(Button.left, 1)
        else:
            raise ValueError(f"Bilinmeyen tıklama türü: {tur} (sol, sağ, çift)")
        time.sleep(0.1)

    def yaz(self, metin, aralik=0.02):
        _, klavye = self._araclar()
        for ch in str(metin):
            klavye.type(ch)
            time.sleep(aralik)

    def tusa_bas(self, kisayol):
        """'enter', 'ctrl+s', 'alt+f4', 'ctrl+shift+esc' gibi."""
        from pynput.keyboard import Key

        _, klavye = self._araclar()
        parcalar = [p.strip() for p in str(kisayol).split("+") if p.strip()] or [kisayol]
        tuslar = []
        for p in parcalar:
            ad = normallestir(p).replace(" ", "")
            if ad in self.TUSLAR:
                tuslar.append(getattr(Key, self.TUSLAR[ad]))
            elif re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", ad):
                tuslar.append(getattr(Key, ad))
            elif len(p) == 1:
                tuslar.append(p.lower() if len(parcalar) > 1 else p)
            else:
                raise ValueError(f"Bilinmeyen tuş: {p}")
        for t in tuslar[:-1]:
            klavye.press(t)
        try:
            klavye.press(tuslar[-1])
            klavye.release(tuslar[-1])
        finally:
            for t in reversed(tuslar[:-1]):
                klavye.release(t)
        time.sleep(0.05)


def _bolge_coz(bolge):
    if bolge in (None, "", "None", "${NONE}"):
        return None
    if isinstance(bolge, dict):
        return (int(bolge["sol"]), int(bolge["ust"]), int(bolge["genislik"]), int(bolge["yukseklik"]))
    if isinstance(bolge, str):
        bolge = [p for p in re.split(r"[,\s]+", bolge.strip()) if p]
    deger = tuple(int(float(v)) for v in bolge)
    if len(deger) != 4 or deger[2] <= 0 or deger[3] <= 0:
        raise ValueError("Bölge 'x,y,genişlik,yükseklik' biçiminde olmalı")
    return deger


def _sonuc(x, y, w, h, skor, ofset, **ek):
    sol, ust = int(round(x + ofset[0])), int(round(y + ofset[1]))
    w, h = int(round(w)), int(round(h))
    return {"x": sol + w // 2, "y": ust + h // 2, "sol": sol, "ust": ust, "genislik": w, "yukseklik": h,
            "skor": round(float(skor), 3), **ek}


class AlamountGoruntu:
    """Görüntü ve OCR tabanlı ekran otomasyonu (Citrix / RDP / VDI).

    Koordinatlar masaüstüne göre mutlak piksellerdir. ``Görüntüyü Bul`` ve ``Yazıyı Bul`` sözlük döner:
    ``x``, ``y`` (merkez), ``sol``, ``ust``, ``genislik``, ``yukseklik``, ``skor``.
    Bulunamayan her aramada ekran görüntüsü Robot loguna eklenir.
    """

    ROBOT_LIBRARY_SCOPE = "GLOBAL"

    def __init__(self, guven=0.85, ekran=0, goruntu_klasoru=None, benzerlik=0.8, config=None):
        dpi_farkinda_ol()
        self.guven = float(guven)
        self.benzerlik = float(benzerlik)
        self.klasor = goruntu_klasoru
        self.ekran = Ekran(ekran)
        self._ayarlar = None
        self._config = config
        self._ocr_hazir = False

    # ------------------------------------------------------------------ yardımcılar
    def _ayar(self):
        if self._ayarlar is None:
            import ayarlar as ay

            yol = self._config or os.environ.get("ALAMOUNT_RPA_CONFIG") or ay.varsayilan_config_yolu()
            self._ayarlar = ay.ayarlari_yukle(yol)
        return self._ayarlar

    def _ocr(self):
        a = self._ayar()
        if not self._ocr_hazir:
            import pytesseract

            import ayarlar as ay

            os.environ.setdefault("OMP_THREAD_LIMIT", "1")
            cmd = ay.tesseract_bul(a)
            if not cmd:
                raise RuntimeError("Tesseract bulunamadı ([OCR] tesseract_yolu)")
            pytesseract.pytesseract.tesseract_cmd = cmd
            self._ocr_hazir = True
        return a.get("OCR", "dil") or "tur+eng"

    @staticmethod
    def _robot_degiskeni(ad):
        try:
            from robot.libraries.BuiltIn import BuiltIn

            return BuiltIn().get_variable_value(ad)
        except Exception:
            return None

    def _log(self, mesaj, html=False):
        try:
            from robot.api import logger

            logger.info(mesaj, html=html)
        except Exception:
            print(mesaj)

    def _sablon_yolu(self, ad):
        ad = str(ad)
        if os.path.isabs(ad):
            adaylar = [ad, ad + ".png"]
        else:
            klasorler = [self.klasor] if self.klasor else []
            kaynak = self._robot_degiskeni("${SUITE SOURCE}")
            if kaynak:
                d = os.path.dirname(kaynak) if os.path.isfile(kaynak) else kaynak
                klasorler += [os.path.join(d, "goruntuler"), d]
            try:
                klasorler.append(os.path.join(self._ayar().yol("ROBOT", "gorev_klasoru"), "goruntuler"))
            except Exception:
                pass
            klasorler.append(os.getcwd())
            adaylar = [os.path.join(k, ad + uz) for k in klasorler if k for uz in ("", ".png")]
        for p in adaylar:
            if os.path.isfile(p):
                return p
        raise FileNotFoundError(f"Şablon görüntüsü bulunamadı: {ad} (gorevler\\goruntuler klasörüne koyun)")

    def _cikti_klasoru(self):
        return self._robot_degiskeni("${OUTPUT DIR}") or os.getcwd()

    def _ekran_kaydet(self, img, on_ek):
        ad = f"{on_ek}_{dt.datetime.now():%H%M%S_%f}.png"
        yol = resim_yaz(os.path.join(self._cikti_klasoru(), ad), img)
        self._log(f'<img src="{ad}" style="max-width:900px;border:1px solid #ccc">', html=True)
        return yol

    def _bekle(self, ara, zaman_asimi, aciklama, img_on_ek):
        """ara() → (sonuçlar, görüntü) ; bulana kadar ya da süre dolana kadar dener."""
        bitis = time.time() + max(0.0, float(zaman_asimi))
        while True:
            sonuc, img = ara()
            if sonuc:
                return sonuc
            if time.time() >= bitis:
                self._ekran_kaydet(img, img_on_ek)
                raise AssertionError(f"{aciklama} ekranda bulunamadı ({float(zaman_asimi):g} sn)")
            time.sleep(0.5)

    # ------------------------------------------------------------------ arama
    def _goruntu_ara(self, sablon, guven, bolge, renkli=False):
        s = resim_oku(self._sablon_yolu(sablon))
        g = float(guven) if guven not in (None, "") else self.guven
        img, ofset = self.ekran.goruntu(_bolge_coz(bolge))
        bulunan = sablon_eslesmeleri(img, s, g, renkli=renkli)
        return [_sonuc(x, y, w, h, skor, ofset) for x, y, w, h, skor in bulunan], img

    def _yazi_ara(self, metin, bolge, benzerlik):
        dil = self._ocr()
        b = float(benzerlik) if benzerlik not in (None, "") else self.benzerlik
        img, ofset = self.ekran.goruntu(_bolge_coz(bolge))
        bulunan = yazi_eslesmeleri(yazi_kelimeleri(img, dil), metin, b)
        if not bulunan and float(_gri(img).mean()) < 110:  # koyu tema: açık renkli yazı
            bulunan = yazi_eslesmeleri(yazi_kelimeleri(img, dil, ters=True), metin, b)
        return [_sonuc(x, y, w, h, skor, ofset, okunan=okunan) for x, y, w, h, skor, okunan in bulunan], img

    def goruntuyu_bul(self, sablon, guven=None, bolge=None, zaman_asimi=10.0, sira=1, renkli=False):
        """Şablon görüntüsünü ekranda arar; bulunana kadar ``zaman_asimi`` saniye bekler.

        ``sablon``: goruntuler klasöründeki ad (``giris_dugmesi``) ya da tam yol.
        ``guven``: 0–1 arası eşleşme eşiği (varsayılan 0.85). ``sira``: aynı görüntü birden çok kez varsa kaçıncısı
        (yukarıdan aşağı, soldan sağa). ``renkli=True``: renk farkını da dikkate alır.
        """
        bulunan = self._bekle(lambda: self._goruntu_ara(sablon, guven, bolge, renkli), zaman_asimi,
                              f"Görüntü '{sablon}'", "bulunamadi")
        sira = int(sira)
        if sira > 1:
            bulunan = sorted(bulunan, key=lambda b: (round(b["ust"] / 8), b["sol"]))
            if sira > len(bulunan):
                raise AssertionError(f"Görüntü '{sablon}' {len(bulunan)} kez bulundu, {sira}. istenmiş")
        b = bulunan[sira - 1]
        self._log(f"Görüntü '{sablon}' bulundu: ({b['x']}, {b['y']}) skor {b['skor']}")
        return b

    def goruntu_var_mi(self, sablon, guven=None, bolge=None, renkli=False):
        """Şablon şu anda ekranda mı? Beklemez; True/False döner."""
        return bool(self._goruntu_ara(sablon, guven, bolge, renkli)[0])

    def goruntu_sayisi(self, sablon, guven=None, bolge=None, renkli=False):
        """Şablonun ekranda kaç kez göründüğünü döner (ör. listedeki satır sayısı)."""
        return len(self._goruntu_ara(sablon, guven, bolge, renkli)[0])

    def goruntu_gorunene_kadar_bekle(self, sablon, zaman_asimi=30.0, guven=None, bolge=None):
        return self.goruntuyu_bul(sablon, guven, bolge, zaman_asimi)

    def goruntu_kaybolana_kadar_bekle(self, sablon, zaman_asimi=30.0, guven=None, bolge=None):
        """Yükleniyor simgesi gibi bir görüntü ekrandan kalkana kadar bekler."""
        bitis = time.time() + float(zaman_asimi)
        while True:
            bulunan, img = self._goruntu_ara(sablon, guven, bolge)
            if not bulunan:
                return True
            if time.time() >= bitis:
                self._ekran_kaydet(img, "kaybolmadi")
                raise AssertionError(f"Görüntü '{sablon}' {float(zaman_asimi):g} sn içinde kaybolmadı")
            time.sleep(0.5)

    def yaziyi_bul(self, metin, bolge=None, zaman_asimi=10.0, benzerlik=None, sira=1):
        """Yazıyı ekranda OCR ile arar (Türkçe). Büyük/küçük harf, Türkçe karakter ve küçük OCR hataları
        yok sayılır; ``benzerlik`` 0–1 (varsayılan 0.8). Bulunana kadar ``zaman_asimi`` saniye bekler."""
        bulunan = self._bekle(lambda: self._yazi_ara(metin, bolge, benzerlik), zaman_asimi,
                              f"Yazı '{metin}'", "yazi_bulunamadi")
        sira = int(sira)
        if sira > 1:
            bulunan = sorted(bulunan, key=lambda b: (round(b["ust"] / 8), b["sol"]))
            if sira > len(bulunan):
                raise AssertionError(f"Yazı '{metin}' {len(bulunan)} kez bulundu, {sira}. istenmiş")
        b = bulunan[sira - 1]
        self._log(f"Yazı '{metin}' bulundu ('{b['okunan']}'): ({b['x']}, {b['y']}) benzerlik {b['skor']}")
        return b

    def yazi_var_mi(self, metin, bolge=None, benzerlik=None):
        return bool(self._yazi_ara(metin, bolge, benzerlik)[0])

    def yazi_gorunene_kadar_bekle(self, metin, zaman_asimi=30.0, bolge=None, benzerlik=None):
        return self.yaziyi_bul(metin, bolge, zaman_asimi, benzerlik)

    def ekrandaki_yaziyi_oku(self, bolge=None):
        """Ekranın (ya da bölgenin) yazısını satır satır döner."""
        dil = self._ocr()
        img, _ = self.ekran.goruntu(_bolge_coz(bolge))
        kelimeler = yazi_kelimeleri(img, dil, psm=11)
        if float(_gri(img).mean()) < 110:
            kelimeler = yazi_kelimeleri(img, dil, psm=11, ters=True) or kelimeler
        return "\n".join(" ".join(k["metin"] for k in s) for s in satirlara_ayir(kelimeler))

    # ------------------------------------------------------------------ fare / klavye
    def goruntuye_tikla(self, sablon, tiklama="sol", x_kaydir=0, y_kaydir=0, guven=None, bolge=None,
                        zaman_asimi=10.0, sira=1):
        """Şablonu bulur ve ortasına tıklar. ``x_kaydir``/``y_kaydir`` ile yanındaki alana tıklanır
        (ör. etiketin 150 piksel sağındaki kutu). ``tiklama``: sol, sağ, çift."""
        b = self.goruntuyu_bul(sablon, guven, bolge, zaman_asimi, sira)
        self.ekran.tikla(b["x"] + int(x_kaydir), b["y"] + int(y_kaydir), tiklama)
        return b

    def yaziya_tikla(self, metin, tiklama="sol", x_kaydir=0, y_kaydir=0, bolge=None, zaman_asimi=10.0,
                     benzerlik=None, sira=1):
        """Yazıyı OCR ile bulur ve üstüne (ya da kaydırılmış noktaya) tıklar."""
        b = self.yaziyi_bul(metin, bolge, zaman_asimi, benzerlik, sira)
        self.ekran.tikla(b["x"] + int(x_kaydir), b["y"] + int(y_kaydir), tiklama)
        return b

    def koordinata_tikla(self, x, y, tiklama="sol"):
        self.ekran.tikla(float(x), float(y), tiklama)

    def fareyi_gotur(self, x, y):
        self.ekran.fareyi_gotur(float(x), float(y))

    def yaz(self, metin, aralik=0.02):
        """Klavyeden yazar (Türkçe karakterler dahil). Yavaş uzak masaüstlerinde ``aralik`` artırılabilir."""
        self.ekran.yaz(metin, float(aralik))

    def tusa_bas(self, kisayol):
        """Tuş ya da kısayol: ``enter``, ``tab``, ``ctrl+a``, ``alt+f4``, ``ctrl+shift+s``."""
        self.ekran.tusa_bas(kisayol)

    def ekran_goruntusu_al(self, dosya=None, bolge=None):
        """Ekran görüntüsünü PNG olarak kaydeder (ör. şablon üretmek için bölge verin) ve yolunu döner."""
        img, _ = self.ekran.goruntu(_bolge_coz(bolge))
        if not dosya:
            return self._ekran_kaydet(img, "ekran")
        return resim_yaz(os.path.abspath(dosya), img)

    def demo_uygulamasini_baslat(self, cikti_dosyasi):
        """Alamount 'uzak masaüstü' demo penceresini açar (yalnızca piksellerden oluşan giriş ekranı)."""
        import subprocess

        if getattr(sys, "frozen", False):
            cmd = [sys.executable]
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "alamount_rpa.py")]
        cmd += ["goruntu-demo", "--cikti", os.path.abspath(cikti_dosyasi)]
        return subprocess.Popen(cmd).pid


# Robot Framework anahtar kelimeleri (Türkçe adlar)
_ADLAR = {
    "goruntuyu_bul": "Görüntüyü Bul", "goruntu_var_mi": "Görüntü Var Mı", "goruntu_sayisi": "Görüntü Sayısı",
    "goruntu_gorunene_kadar_bekle": "Görüntü Görünene Kadar Bekle",
    "goruntu_kaybolana_kadar_bekle": "Görüntü Kaybolana Kadar Bekle",
    "yaziyi_bul": "Yazıyı Bul", "yazi_var_mi": "Yazı Var Mı", "yazi_gorunene_kadar_bekle": "Yazı Görünene Kadar Bekle",
    "ekrandaki_yaziyi_oku": "Ekrandaki Yazıyı Oku", "goruntuye_tikla": "Görüntüye Tıkla",
    "yaziya_tikla": "Yazıya Tıkla", "koordinata_tikla": "Koordinata Tıkla", "fareyi_gotur": "Fareyi Götür",
    "yaz": "Yaz", "tusa_bas": "Tuşa Bas", "ekran_goruntusu_al": "Ekran Görüntüsü Al",
    "demo_uygulamasini_baslat": "Demo Uygulamasını Başlat",
}
for _metot, _robot_adi in _ADLAR.items():
    getattr(AlamountGoruntu, _metot).robot_name = _robot_adi
