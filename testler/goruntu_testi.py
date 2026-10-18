# -*- coding: utf-8 -*-
"""
Görüntü otomasyonu birim testi (ekran gerekmez; ekran yerine sentetik görüntü verilir):
  * Çok ölçekli şablon eşleme (%100, %125, %80 ekran ölçeği), birden çok eşleşme, yokluk
  * OCR ile Türkçe yazı bulma (büyük/küçük harf, Türkçe karakter farkı, koyu tema)
  * Kütüphane: bulamayınca ekran görüntüsünü kaydedip anlaşılır hata vermesi, bölge/kaydırma
Kullanım: python testler/goruntu_testi.py <proje_klasoru>
"""
import os
import sys
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

KOK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
sys.path.insert(0, KOK)
import AlamountGoruntu as ag  # noqa: E402

SONUC = {}
dugme = ag.resim_oku(os.path.join(KOK, "gorevler", "goruntuler", "demo_giris_dugmesi.png"))


def font(boy):
    for f in ("C:/Windows/Fonts/segoeui.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.isfile(f):
            return ImageFont.truetype(f, boy)
    return ImageFont.load_default()


def ekran(yazilar=(), zemin="#f4f6fa", renk="#1d2433", boyut=(1280, 720)):
    im = Image.new("RGB", boyut, zemin)
    d = ImageDraw.Draw(im)
    for x, y, t, b in yazilar:
        d.text((x, y), t, font=font(b), fill=renk)
    return cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR)


def yapistir(e, s, x, y):
    e[y:y + s.shape[0], x:x + s.shape[1]] = s


# ---- şablon eşleme
e = ekran()
yapistir(e, dugme, 400, 300)
b = ag.sablon_eslesmeleri(e, dugme)
SONUC["şablon %100 bulundu (konum doğru)"] = len(b) == 1 and (b[0][0], b[0][1]) == (400, 300) and b[0][4] > 0.99
for olcek, ad in ((1.25, "%125"), (0.8, "%80"), (1.5, "%150")):
    e = ekran()
    s = cv2.resize(dugme, None, fx=olcek, fy=olcek, interpolation=cv2.INTER_LINEAR)
    yapistir(e, s, 200, 150)
    b = ag.sablon_eslesmeleri(e, dugme)
    SONUC[f"şablon {ad} ekran ölçeğinde bulundu"] = bool(b) and abs(b[0][0] - 200) <= 4 and abs(b[0][1] - 150) <= 4
e = ekran()
for i in range(3):
    yapistir(e, dugme, 100, 100 + i * 80)
SONUC["aynı şablon 3 kez sayıldı"] = len(ag.sablon_eslesmeleri(e, dugme)) == 3
SONUC["olmayan şablon bulunmadı"] = ag.sablon_eslesmeleri(ekran(), dugme) == []
e = ekran()
yapistir(e, np.full((30, 30, 3), 200, np.uint8), 50, 60)
b = ag.sablon_eslesmeleri(e, np.full((30, 30, 3), 200, np.uint8))
SONUC["düz renkli şablon çökmeden eşleşti"] = bool(b) and (b[0][0], b[0][1]) == (50, 60)

# ---- normalleştirme / OCR
SONUC["Türkçe normalleştirme"] = ag.normallestir("KULLANICI ADI:") == ag.normallestir("Kullanıcı adı") == "kullanici adi"
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
yazilar = [(60, 80, "Kullanıcı adı", 18), (60, 180, "Parola", 18), (700, 80, "İşlem Tarihi: 18.10.2026", 16),
           (60, 400, "Faturayı Onayla", 15), (400, 400, "Faturayı Reddet", 15)]
k = ag.yazi_kelimeleri(ekran(yazilar), "tur+eng")
for aranan in ("Kullanıcı adı", "KULLANICI ADI", "kullanici adi", "Parola", "işlem tarihi", "Faturayı Reddet"):
    m = ag.yazi_eslesmeleri(k, aranan)
    SONUC[f"OCR: '{aranan}' bulundu"] = bool(m)
m = ag.yazi_eslesmeleri(k, "Faturayı Reddet")
SONUC["OCR: doğru düğme seçildi (Onayla değil Reddet)"] = bool(m) and m[0][0] > 380
SONUC["OCR: olmayan yazı bulunmadı"] = not ag.yazi_eslesmeleri(k, "Sil")
koyu = ekran(yazilar, zemin="#1e1e1e", renk="#e8e8e8")
SONUC["OCR: koyu tema (ters çevirerek)"] = bool(ag.yazi_eslesmeleri(ag.yazi_kelimeleri(koyu, "tur+eng", ters=True),
                                                                    "Kullanıcı adı"))


# ---- kütüphane (ekran yerine sentetik görüntü)
class SahteEkran(ag.Ekran):
    def __init__(self, img):
        super().__init__()
        self.img, self.tiklamalar = img, []

    def goruntu(self, bolge=None):
        if bolge:
            x, y, w, h = bolge
            return self.img[y:y + h, x:x + w].copy(), (x, y)
        return self.img.copy(), (0, 0)

    def tikla(self, x, y, tur="sol"):
        self.tiklamalar.append((x, y, tur))


gecici = tempfile.mkdtemp()
cfg = os.path.join(gecici, "config.ini")
import ayarlar  # noqa: E402

open(cfg, "w", encoding="utf-8").write(ayarlar.TAM_CONFIG.replace("tesseract_yolu = tesseract\\tesseract.exe",
                                                                  "tesseract_yolu ="))
kut = ag.AlamountGoruntu(goruntu_klasoru=os.path.join(KOK, "gorevler", "goruntuler"), config=cfg)
e = ekran(yazilar)
yapistir(e, dugme, 500, 600)
kut.ekran = SahteEkran(e)
os.chdir(gecici)
b = kut.goruntuye_tikla("demo_giris_dugmesi", zaman_asimi=0)
SONUC["Görüntüye Tıkla: merkeze tıkladı"] = kut.ekran.tiklamalar[-1] == (590, 622, "sol")
kut.yaziya_tikla("Kullanıcı adı", y_kaydir=38, zaman_asimi=0)
x, y, _ = kut.ekran.tiklamalar[-1]
SONUC["Yazıya Tıkla: kaydırmalı tıklama"] = 60 <= x <= 200 and 120 <= y <= 150
b = kut.goruntuyu_bul("demo_giris_dugmesi", bolge="450,550,300,120", zaman_asimi=0)
SONUC["bölge içinde arama mutlak koordinat döndü"] = (b["x"], b["y"]) == (590, 622)
try:
    kut.goruntuyu_bul("demo_giris_dugmesi", bolge="0,0,300,300", zaman_asimi=0)
    SONUC["bulunamayınca hata"] = False
except AssertionError as ex:
    SONUC["bulunamayınca hata"] = "bulunamadı" in str(ex)
SONUC["bulunamayınca ekran görüntüsü kaydedildi"] = any(f.startswith("bulunamadi_") for f in os.listdir(gecici))
try:
    kut.goruntuyu_bul("olmayan_sablon", zaman_asimi=0)
    SONUC["eksik şablon anlaşılır hata"] = False
except FileNotFoundError as ex:
    SONUC["eksik şablon anlaşılır hata"] = "goruntuler" in str(ex)
SONUC["Görüntü Var Mı / Sayısı"] = kut.goruntu_var_mi("demo_giris_dugmesi") and kut.goruntu_sayisi(
    "demo_giris_dugmesi") == 1
oku = kut.ekrandaki_yaziyi_oku("40,60,400,60")
SONUC["Ekrandaki Yazıyı Oku (bölge)"] = "Kullanıcı" in oku and "Parola" not in oku
adlar = {getattr(getattr(ag.AlamountGoruntu, f), "robot_name", None) for f in dir(ag.AlamountGoruntu)}
SONUC["Türkçe anahtar kelime adları"] = {"Görüntüye Tıkla", "Yazıya Tıkla", "Tuşa Bas", "Yaz"} <= adlar

print("\n=========== GÖRÜNTÜ OTOMASYONU ===========")
for k_, v in SONUC.items():
    print(("✅" if v else "❌"), k_)
print(f"{sum(SONUC.values())}/{len(SONUC)} geçti")
sys.exit(0 if all(SONUC.values()) else 1)
