# -*- coding: utf-8 -*-
"""
Kuyruk tabanlı işe giriş (çok robotlu):
  ise-giris-dagit : giriş klasöründeki (ortak ağ klasörü) her PDF için 'ise_giris' kuyruğuna öğe ekler
  ise-giris-isle  : kuyruktan öğe alır, işler, sonucu bildirir; kuyruk boşalınca biter
Aynı anda birden fazla robot 'isle' çalıştırabilir; her öğeyi yalnızca bir robot alır.
Hata türleri: iş kuralı (TC Puantaj'da yok vb.) → yeniden denenmez; sistem hatası → deneme hakkı kadar tekrar.
"""

import logging
import os
import re
import shutil

import belge_ocr as bo
import ise_giris
from merkez_istemci import MerkezIstemci

log = logging.getLogger("alamount")
KUYRUK = "ise_giris"


def _tasi(yol, hedef_klasor):
    os.makedirs(hedef_klasor, exist_ok=True)
    hedef = os.path.join(hedef_klasor, os.path.basename(yol))
    if os.path.exists(hedef):
        kok, uz = os.path.splitext(hedef)
        hedef = f"{kok}_{int(os.path.getmtime(yol))}{uz}"
    shutil.move(yol, hedef)
    return hedef


def dagit(ayarlar):
    ist = MerkezIstemci.ayarlardan(ayarlar)
    giris = ayarlar.yol("ISE_GIRIS", "giris", olustur=True)
    eklenen = atlanan = 0
    for f in sorted(os.listdir(giris)):
        yol = os.path.join(giris, f)
        if not (f.lower().endswith(".pdf") and os.path.isfile(yol)):
            continue
        st = os.stat(yol)
        m = re.search(r"(?<!\d)(\d{11})(?!\d)", f)
        referans = m.group(1) if m else os.path.splitext(f)[0]
        imza = f"{f}|{st.st_size}|{int(st.st_mtime)}"
        r = ist.kuyruga_ekle(KUYRUK, referans, {"pdf": yol, "dosya": f}, imza=imza, max_deneme=3)
        if r and r.get("eklendi"):
            eklenen += 1
            log.info("Kuyruğa eklendi: %s", bo.tc_maskele(referans) if m else referans)
        else:
            atlanan += 1
    log.info("Dağıtım bitti: %d yeni öğe, %d zaten kuyrukta", eklenen, atlanan)
    return 0


def isle(ayarlar):
    ist = MerkezIstemci.ayarlardan(ayarlar)
    puantaj_yolu = ayarlar.yol("ISE_GIRIS", "puantaj")
    arsiv = os.path.join(ayarlar.folder("arsiv"), "ise_giris")
    hata_kl = os.path.join(ayarlar.folder("hata"), "ise_giris")
    puantaj, puantaj_zaman = None, None
    basarili = basarisiz = 0
    while True:
        o = ist.kuyruktan_al(KUYRUK)
        if not o:
            break
        pdf = o["veri"].get("pdf", "")
        ref = o["referans"]
        gizli = bo.tc_maskele(ref) if ref.isdigit() else ref
        log.info("Öğe #%s alındı: %s (deneme %s/%s)", o["id"], gizli, o["deneme"], o["max_deneme"])
        try:
            if not os.path.isfile(pdf):
                raise LookupError(f"PDF bulunamadı (taşınmış olabilir): {pdf}")
            if not os.path.isfile(puantaj_yolu):
                raise FileNotFoundError(f"Puantaj dosyası bulunamadı: {puantaj_yolu}")
            if puantaj is None or os.path.getmtime(puantaj_yolu) != puantaj_zaman:
                puantaj = ise_giris.puantaj_oku(puantaj_yolu, ayarlar.get("ISE_GIRIS", "puantaj_sayfa"))
                puantaj_zaman = os.path.getmtime(puantaj_yolu)
            tc = ref if bo.tc_gecerli_mi(ref) else None
            if not tc:
                tc = next((t for t in bo.tc_bul(bo.pdf_metne_cevir(pdf, ayarlar)) if t in puantaj), None)
                if not tc:
                    raise LookupError("Dosya adında ve PDF içinde Puantaj'la eşleşen TC bulunamadı")
            r = ise_giris.hazirla(tc, pdf, puantaj_yolu, ayarlar, puantaj=puantaj)
            if ayarlar.getbool("ISE_GIRIS", "arsive_tasi"):
                _tasi(pdf, arsiv)
            ist.oge_bitir(o["id"], "basarili", {"excel": r["excel"], "ad_soyad": r["ad_soyad"], **r["ozet"],
                                                "uyari": len(r["uyarilar"])})
            basarili += 1
        except (LookupError, ValueError) as e:  # iş kuralı: tekrar denemek düzeltmez
            log.error("Öğe #%s iş kuralı hatası: %s", o["id"], e)
            if os.path.isfile(pdf):
                _tasi(pdf, hata_kl)
            ist.oge_bitir(o["id"], "is_hatasi", hata=str(e))
            basarisiz += 1
        except Exception as e:  # sistem: ağ, dosya kilidi, OCR çökmesi...
            log.exception("Öğe #%s sistem hatası", o["id"])
            if o.get("son_deneme") and os.path.isfile(pdf):
                _tasi(pdf, hata_kl)
            ist.oge_bitir(o["id"], "sistem_hatasi", hata=f"{type(e).__name__}: {e}")
            basarisiz += 1
    log.info("Kuyruk boş. Bu çalışmada: %d başarılı, %d hatalı", basarili, basarisiz)
    return 0
