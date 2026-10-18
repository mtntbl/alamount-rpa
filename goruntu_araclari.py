# -*- coding: utf-8 -*-
"""
Görüntü otomasyonu yardımcı araçları:
  AlamountRPA.exe goruntu-yakala AD     ekrandan şablon keser → gorevler\\goruntuler\\AD.png
  AlamountRPA.exe goruntu-dene AD       şablonun şu anki ekranda bulunup bulunmadığını gösterir
  AlamountRPA.exe goruntu-demo          yalnızca piksellerden oluşan 'uzak masaüstü' giriş ekranı (örnek görev için)
"""

import datetime as dt
import json
import os
import time

import AlamountGoruntu as ag


def _klasor(ayarlar, klasor=None):
    k = klasor or os.path.join(ayarlar.yol("ROBOT", "gorev_klasoru"), "goruntuler")
    os.makedirs(k, exist_ok=True)
    return k


def _ad_temizle(ad):
    ad = os.path.splitext(os.path.basename(ad))[0]
    if not ad or any(c in ad for c in '\\/:*?"<>|'):
        raise SystemExit(f"Geçersiz şablon adı: {ad}")
    return ad


def yakala(ayarlar, ad, klasor=None, gecikme=3):
    """Ekranın görüntüsünü alır, fareyle seçilen alanı şablon olarak kaydeder."""
    import tkinter as tk

    from PIL import Image, ImageEnhance, ImageTk

    ad = _ad_temizle(ad)
    hedef = os.path.join(_klasor(ayarlar, klasor), ad + ".png")
    ag.dpi_farkinda_ol()
    for i in range(int(gecikme), 0, -1):
        print(f"  Hedef ekranı açın... {i}", flush=True)
        time.sleep(1)
    ekran = ag.Ekran(0)
    img, (sol, ust) = ekran.goruntu()
    h, w = img.shape[:2]
    asil = Image.fromarray(img[:, :, ::-1])
    soluk = ImageEnhance.Brightness(asil).enhance(0.55)

    secim = {}
    kok = tk.Tk()
    kok.overrideredirect(True)
    kok.geometry(f"{w}x{h}+{sol}+{ust}")
    kok.attributes("-topmost", True)
    tuval = tk.Canvas(kok, width=w, height=h, highlightthickness=0, cursor="crosshair")
    tuval.pack()
    arka = ImageTk.PhotoImage(soluk)
    tuval.create_image(0, 0, image=arka, anchor="nw")
    tuval.create_text(20, 20, anchor="nw", fill="white", font=("Segoe UI", 14, "bold"),
                      text=f"'{ad}' için alanı fareyle seçin  ·  Esc: vazgeç")
    durum = {"bas": None, "kutu": None, "parca": None}

    def bas(e):
        durum["bas"] = (e.x, e.y)

    def surukle(e):
        if not durum["bas"]:
            return
        x0, y0 = durum["bas"]
        x1, x2, y1, y2 = min(x0, e.x), max(x0, e.x), min(y0, e.y), max(y0, e.y)
        if durum["kutu"]:
            tuval.delete(durum["kutu"])
        if x2 - x1 > 1 and y2 - y1 > 1:
            durum["parca"] = ImageTk.PhotoImage(asil.crop((x1, y1, x2, y2)))
            tuval.delete("parca")
            tuval.create_image(x1, y1, image=durum["parca"], anchor="nw", tags="parca")
        durum["kutu"] = tuval.create_rectangle(x1, y1, x2, y2, outline="#04BAF3", width=2)

    def birak(e):
        if not durum["bas"]:
            return
        x0, y0 = durum["bas"]
        x1, x2, y1, y2 = min(x0, e.x), max(x0, e.x), min(y0, e.y), max(y0, e.y)
        if x2 - x1 >= 6 and y2 - y1 >= 6:
            secim["kutu"] = (x1, y1, x2, y2)
            kok.destroy()
        else:
            durum["bas"] = None

    tuval.bind("<ButtonPress-1>", bas)
    tuval.bind("<B1-Motion>", surukle)
    tuval.bind("<ButtonRelease-1>", birak)
    kok.bind("<Escape>", lambda e: kok.destroy())
    kok.focus_force()
    kok.mainloop()

    if "kutu" not in secim:
        print("Vazgeçildi.")
        return 1
    x1, y1, x2, y2 = secim["kutu"]
    parca = img[y1:y2, x1:x2]
    ag.resim_yaz(hedef, parca)
    bulunan = ag.sablon_eslesmeleri(img, parca, 0.85)
    print(f"\nKaydedildi: {hedef}  ({x2 - x1}x{y2 - y1} piksel)")
    if len(bulunan) > 1:
        print(f"  ! Bu görüntü ekranda {len(bulunan)} kez var. Daha ayırt edici (biraz daha geniş) bir alan seçin"
              f" ya da görevde sira=2 gibi bir değer verin.")
    print(f"\nGörevde kullanımı:\n    Görüntüye Tıkla    {ad}\n    Görüntü Görünene Kadar Bekle    {ad}")
    return 0


def dene(ayarlar, ad, guven=0.85, klasor=None):
    """Şablonu şu anki ekranda arar ve sonuçları yazar."""
    ag.dpi_farkinda_ol()
    yol = ad if os.path.isfile(ad) else os.path.join(_klasor(ayarlar, klasor), _ad_temizle(ad) + ".png")
    if not os.path.isfile(yol):
        print(f"Şablon yok: {yol}")
        return 1
    sablon = ag.resim_oku(yol)
    img, (sol, ust) = ag.Ekran(0).goruntu()
    t = time.time()
    bulunan = ag.sablon_eslesmeleri(img, sablon, 0.5)
    sure = time.time() - t
    iyi = [b for b in bulunan if b[4] >= float(guven)]
    print(f"Şablon: {yol}  ({sablon.shape[1]}x{sablon.shape[0]})  ·  arama {sure:.2f} sn")
    for x, y, w, h, skor in bulunan[:5]:
        isaret = "OK" if skor >= float(guven) else "--"
        print(f"  [{isaret}] merkez ({sol + x + w // 2}, {ust + y + h // 2})  boyut {w}x{h}  skor {skor:.3f}")
    if not bulunan:
        print("  Ekranda benzer bir alan yok.")
    print("Sonuç:", f"{len(iyi)} eşleşme (eşik {float(guven):g})" if iyi else "BULUNAMADI — hedef ekran açık mı?")
    return 0 if iyi else 1


def demo(ayarlar, cikti, sure=120):
    """Citrix benzetimi: UI Automation öğesi olmayan, yalnızca çizimden oluşan bir giriş ekranı."""
    import tkinter as tk

    ag.dpi_farkinda_ol()
    kok = tk.Tk()
    kok.title("Alamount Uzak Masaüstü (demo)")
    kok.geometry("560x400+80+80")
    kok.resizable(False, False)
    kok.attributes("-topmost", True)
    zemin = "#f4f6fa"
    tuval = tk.Canvas(kok, width=560, height=400, bg=zemin, highlightthickness=0)
    tuval.pack()
    yazi = ("DejaVu Sans", 13) if os.name != "nt" else ("Segoe UI", 13)
    kalin = (yazi[0], 13, "bold")
    tuval.create_rectangle(0, 0, 560, 54, fill="#022351", outline="")
    tuval.create_text(24, 27, anchor="w", text="Alamount Uzak Masaüstü", fill="white", font=(yazi[0], 15, "bold"))
    alanlar = {"kullanici": {"etiket": "Kullanıcı adı", "y": 92, "deger": "", "gizli": False},
               "parola": {"etiket": "Parola", "y": 182, "deger": "", "gizli": True}}
    for a in alanlar.values():
        tuval.create_text(60, a["y"], anchor="w", text=a["etiket"], fill="#1d2433", font=kalin)
        a["kutu"] = tuval.create_rectangle(60, a["y"] + 20, 500, a["y"] + 58, fill="white", outline="#9aa5b8", width=2)
        a["metin"] = tuval.create_text(72, a["y"] + 39, anchor="w", text="", fill="#1d2433", font=yazi)
    dugme_yolu = os.path.join(ayarlar.yol("ROBOT", "gorev_klasoru"), "goruntuler", "demo_giris_dugmesi.png")
    dugme_img = tk.PhotoImage(file=dugme_yolu) if os.path.isfile(dugme_yolu) else None
    if dugme_img:
        tuval.create_image(60, 280, image=dugme_img, anchor="nw")
        dugme = (60, 280, 60 + dugme_img.width(), 280 + dugme_img.height())
    else:
        dugme = (60, 280, 240, 324)
        tuval.create_rectangle(*dugme, fill="#022351", outline="")
        tuval.create_text(150, 302, text="Giriş Yap", fill="white", font=kalin)
    durum = {"odak": None, "bitti": False}

    def odakla(ad):
        durum["odak"] = ad
        for k, a in alanlar.items():
            tuval.itemconfigure(a["kutu"], outline="#04BAF3" if k == ad else "#9aa5b8")

    def ciz():
        for a in alanlar.values():
            tuval.itemconfigure(a["metin"], text="•" * len(a["deger"]) if a["gizli"] else a["deger"])

    def gir():
        k, p = alanlar["kullanici"]["deger"], alanlar["parola"]["deger"]
        if not k or not p:
            tuval.delete("uyari")
            tuval.create_text(260, 302, anchor="w", text="Alanları doldurun", fill="#c0392b", font=yazi,
                              tags="uyari")
            return
        durum["bitti"] = True
        tuval.delete("all")
        tuval.create_rectangle(0, 0, 560, 54, fill="#022351", outline="")
        tuval.create_text(24, 27, anchor="w", text="Alamount Uzak Masaüstü", fill="white",
                          font=(yazi[0], 15, "bold"))
        tuval.create_text(60, 120, anchor="w", text=f"Hoş geldiniz, {k}", fill="#1d2433", font=(yazi[0], 18, "bold"))
        tuval.create_text(60, 170, anchor="w", text="Bekleyen fatura sayısı: 7", fill="#1d2433", font=yazi)
        tuval.create_text(60, 205, anchor="w", text="Çıkmak için Esc", fill="#5b6475", font=yazi)
        with open(cikti, "w", encoding="utf-8") as f:
            json.dump({"kullanici": k, "parola_uzunlugu": len(p), "zaman": dt.datetime.now().isoformat()}, f,
                      ensure_ascii=False)

    def tikla(e):
        if durum["bitti"]:
            return
        tuval.focus_set()
        for ad, a in alanlar.items():
            if 60 <= e.x <= 500 and a["y"] + 20 <= e.y <= a["y"] + 58:
                odakla(ad)
                return
        if dugme[0] <= e.x <= dugme[2] and dugme[1] <= e.y <= dugme[3]:
            gir()

    def tus(e):
        if e.keysym == "Escape":
            kok.destroy()
            return
        if durum["bitti"]:
            return
        if e.keysym in ("Return", "KP_Enter"):
            gir()
        elif e.keysym == "Tab":
            odakla("parola" if durum["odak"] == "kullanici" else "kullanici")
            return "break"
        elif durum["odak"]:
            a = alanlar[durum["odak"]]
            if e.keysym == "BackSpace":
                a["deger"] = a["deger"][:-1]
            elif e.char and e.char.isprintable():
                a["deger"] += e.char
            ciz()

    tuval.bind("<Button-1>", tikla)
    kok.bind("<Key>", tus)
    kok.after(int(sure * 1000), kok.destroy)
    kok.lift()
    kok.focus_force()
    tuval.focus_set()
    kok.mainloop()
    return 0
