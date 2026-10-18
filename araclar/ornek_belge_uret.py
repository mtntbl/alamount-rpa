# -*- coding: utf-8 -*-
"""
Test için KURGUSAL personel belgeleri üretir (gerçek kişi değildir):
  ornek_veri/ise_giris/PUANTAJ BİLGİLERİ.xlsx
  ornek_veri/ise_giris/<TC>.pdf   (metin katmanlı + taranmış sayfalar + fotoğraflı kimlik kartı)

Kullanım: python araclar/ornek_belge_uret.py [hedef_klasor]
"""

import io
import os
import random
import sys

import pymupdf as fitz
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_ADAYLARI = [
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def font(boyut):
    for f in FONT_ADAYLARI:
        if os.path.exists(f):
            return ImageFont.truetype(f, boyut)
    return ImageFont.load_default()


def tc_uret(ilk9):
    d = [int(c) for c in ilk9]
    d10 = (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10
    d11 = (sum(d) + d10) % 10
    return ilk9 + str(d10) + str(d11)


PERSONELLER = [
    dict(tc=tc_uret("123456780"), ad="DENEME", soyad="PERSONEL", dogum="14.03.1990", emekli="EMEKLİ DEĞİL",
         birim="SEDEF", giris="20.10.2026", meslek="MONTAJ YARDIMCISI", egitim="LİSE",
         iban="TR330006100519786457841326", tel="0532 111 22 33", cins="E", seri="A12B34567",
         dyeri="ÜSKÜDAR", medeni="Bekar", nuf=("İSTANBUL", "ÜSKÜDAR", "ACIBADEM", "45", "112", "7"),
         adres="KOZYATAĞI MAH. DEĞİRMEN SK. NO: 12 İÇ KAPI NO: 5 KADIKÖY / İSTANBUL",
         sertifika="ÇELİK YAPILANDIRMACI"),
    dict(tc=tc_uret("234567891"), ad="ÖRNEK", soyad="ÇALIŞAN", dogum="02.11.1968", emekli="EMEKLİ",
         birim="ADA", giris="21.10.2026", meslek="KAYNAKÇI", egitim="ORTAOKUL",
         iban="TR320010009999901234567890", tel="05051234567", cins="E", seri="B98C76543",
         dyeri="TUZLA", medeni="Evli", nuf=("KOCAELİ", "GEBZE", "OSMAN YILMAZ", "12", "301", "3"),
         adres="AYDINLI MAH. ATATÜRK CAD. NO: 7 İÇ KAPI NO: 2 TUZLA / İSTANBUL", sertifika=None),
]


def puantaj_yaz(yol):
    wb = Workbook()
    ws = wb.active
    ws.title = "GİRİŞ"
    ws.append(["PUANTAJ BİLGİLERİ - YENİ GİRİŞLER (KURGUSAL TEST VERİSİ)"])
    ws.append([])
    ws.append(["SNO", "TC KİMLİK NO", "ADI SOYADI", "DOĞUM TARİHİ", "EMEKLİ Mİ DEĞİLMİ", "BİRİM",
               "İŞE GİRİŞ TARİHİ", "MESLEK", "EĞİTİM DURUMU", "IBN NO", "TELEFON NUMARASI"])
    for i, p in enumerate(PERSONELLER, 1):
        ws.append([i, int(p["tc"]), f"{p['ad']} {p['soyad']}", p["dogum"], p["emekli"], p["birim"], p["giris"],
                   p["meslek"], p["egitim"], p["iban"], p["tel"]])
    wb.save(yol)


def metin_sayfasi_ttf(doc, satirlar):
    """Türkçe karakterli metin katmanı için TTF font gömerek yazar."""
    page = doc.new_page(width=595, height=842)
    ff = next((f for f in FONT_ADAYLARI if os.path.exists(f)), None)
    y = 60
    for s, boyut in satirlar:
        if ff:
            page.insert_text((50, y), s, fontsize=boyut, fontname="trf", fontfile=ff)
        else:
            page.insert_text((50, y), s, fontsize=boyut)
        y += boyut + 10


def taranmis_gorsel(satirlar, egim=1.2):
    """A4 @200dpi beyaz sayfaya metin yazar, hafif eğer ve gürültü ekler (tarayıcı taklidi)."""
    W, H = 1654, 2339
    img = Image.new("L", (W, H), 250)
    d = ImageDraw.Draw(img)
    y = 140
    for s, boyut in satirlar:
        d.text((130, y), s, font=font(int(boyut * 2.4)), fill=20)
        y += int(boyut * 2.4) + 26
    img = img.rotate(egim, resample=Image.BICUBIC, fillcolor=250)
    rnd = random.Random(7)
    px = img.load()
    for _ in range(9000):
        x, yy = rnd.randrange(W), rnd.randrange(H)
        px[x, yy] = rnd.choice((120, 200))
    return img.filter(ImageFilter.GaussianBlur(0.6)).convert("RGB")


def kimlik_karti(p, arka=False):
    W, H = 1012, 638  # 85.6x54mm @300dpi
    img = Image.new("RGB", (W, H), (226, 236, 246))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W - 1, 95], fill=(196, 30, 58))
    d.text((30, 22), "TÜRKİYE CUMHURİYETİ KİMLİK KARTI", font=font(38), fill="white")
    d.text((30, 64), "REPUBLIC OF TURKEY IDENTITY CARD", font=font(22), fill="white")
    if not arka:
        d.rectangle([30, 130, 290, 470], fill=(170, 180, 190))
        alanlar = [
            ("T.C. Kimlik No / TR Identity No", p["tc"]),
            ("Soyadı / Surname", p["soyad"]),
            ("Adı / Given Name(s)", p["ad"]),
            ("Doğum Tarihi / Date of Birth", p["dogum"]),
            ("Cinsiyeti / Gender", f"{p['cins']}/{'M' if p['cins'] == 'E' else 'F'}"),
            ("Seri No / Document No", p["seri"]),
            ("Uyruğu / Nationality", "T.C./TUR"),
            ("Geçerlilik Tarihi / Valid Until", "14.03.2034"),
        ]
        y = 115
        for et, v in alanlar:
            d.text((320, y), et, font=font(20), fill=(90, 90, 90))
            d.text((320, y + 22), v, font=font(30), fill="black")
            y += 62
    else:
        y = 130
        for et, v in [("Anne Adı / Mother's Name", "AYŞE"), ("Baba Adı / Father's Name", "MEHMET"),
                      ("Veren Makam / Issued By", f"{p['nuf'][1]} İLÇE NÜFUS MÜD.")]:
            d.text((40, y), et, font=font(22), fill=(90, 90, 90))
            d.text((40, y + 26), v, font=font(32), fill="black")
            y += 90
        d.text((40, 520), f"I<TUR{p['seri']}<<<<<<<<<<<<<<<", font=font(30), fill="black")
    d.rectangle([0, 0, W - 1, H - 1], outline=(60, 60, 60), width=3)
    return img


def kimlik_fotokopi_sayfasi(p):
    """Kimlik ön/arka yüzünü A4 sayfaya hafif eğik 'yapıştırılmış' gibi yerleştirir."""
    W, H = 2480, 3508
    sayfa = Image.new("RGB", (W, H), (245, 245, 242))
    for i, (kart, aci) in enumerate(((kimlik_karti(p), 3), (kimlik_karti(p, arka=True), -2))):
        k = kart.rotate(aci, expand=True, resample=Image.BICUBIC, fillcolor=(245, 245, 242))
        sayfa.paste(k, (420, 380 + i * 1350))
    return sayfa.filter(ImageFilter.GaussianBlur(0.8))


def gorsel_sayfa(doc, img, dpi):
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    w, h = img.size
    page = doc.new_page(width=w * 72 / dpi, height=h * 72 / dpi)
    page.insert_image(page.rect, stream=buf.getvalue())


def pdf_yaz(p, yol):
    doc = fitz.open()
    ad = f"{p['ad']} {p['soyad']}"
    metin_sayfasi_ttf(doc, [
        ("T.C. ADALET BAKANLIĞI", 14), ("ADLİ SİCİL KAYDI", 16),
        (f"T.C. Kimlik No: {p['tc']}", 11), (f"Adı Soyadı: {ad}", 11),
        ("Adli sicil kaydı bulunmamaktadır.", 11), ("Bu belge kurgusal test verisidir.", 9),
    ])
    gorsel_sayfa(doc, taranmis_gorsel([
        ("T.C. İÇİŞLERİ BAKANLIĞI", 14), ("Nüfus ve Vatandaşlık İşleri Genel Müdürlüğü", 11),
        ("YERLEŞİM YERİ VE DİĞER ADRES BELGESİ", 15), ("", 8),
        (f"T.C. Kimlik No: {p['tc']}", 11), (f"Adı Soyadı: {ad}", 11), ("", 8),
        (f"Adres: {p['adres']}", 10), ("", 8),
        ("Beyan tarihi: 01.09.2026", 10),
    ]), 200)
    il, ilce, mah, cilt, hane, bsn = p["nuf"]
    gorsel_sayfa(doc, taranmis_gorsel([
        ("NÜFUS KAYIT ÖRNEĞİ", 16), ("", 8),
        (f"T.C. Kimlik No: {p['tc']}", 11), (f"Adı: {p['ad']}", 11), (f"Soyadı: {p['soyad']}", 11),
        ("Baba Adı: MEHMET", 11), ("Anne Adı: AYŞE", 11),
        (f"Doğum Yeri: {p['dyeri']}", 11), (f"Doğum Tarihi: {p['dogum']}", 11),
        (f"Cinsiyeti: {'Erkek' if p['cins'] == 'E' else 'Kadın'}", 11), (f"Medeni Hali: {p['medeni']}", 11),
        ("Dini: İSLAM", 11), (f"İl: {il}", 11), (f"İlçe: {ilce}", 11), (f"Mahalle/Köy: {mah}", 11),
        (f"Cilt No: {cilt}", 11), (f"Aile Sıra No: {hane}", 11), (f"Birey Sıra No: {bsn}", 11),
    ], egim=-0.8), 200)
    gorsel_sayfa(doc, kimlik_fotokopi_sayfasi(p), 300)
    metin_sayfasi_ttf(doc, [
        ("T.C. MİLLÎ EĞİTİM BAKANLIĞI", 14), ("e-MEZUN BELGESİ / DİPLOMA", 16),
        (f"Adı Soyadı: {ad}", 11), (f"Öğrenim Durumu: {p['egitim']} MEZUNU", 11),
    ])
    if p.get("sertifika"):
        metin_sayfasi_ttf(doc, [
            ("MESLEKİ YETERLİLİK KURUMU", 14), ("MESLEKİ YETERLİLİK BELGESİ / SERTİFİKA", 15),
            (f"Adı Soyadı: {ad}", 11), (f"Yeterlilik: {p['sertifika']}", 11),
        ])
    doc.save(yol, deflate=True)


def main():
    hedef = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ornek_veri", "ise_giris")
    os.makedirs(hedef, exist_ok=True)
    puantaj_yaz(os.path.join(hedef, "PUANTAJ BİLGİLERİ.xlsx"))
    for p in PERSONELLER:
        pdf_yaz(p, os.path.join(hedef, f"{p['tc']}.pdf"))
        print("Üretildi:", p["tc"], p["ad"], p["soyad"])


if __name__ == "__main__":
    main()
