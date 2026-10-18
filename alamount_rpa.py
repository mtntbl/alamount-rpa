# -*- coding: utf-8 -*-
"""
Alamount RPA — tek giriş noktası (AlamountRPA.exe)

  AlamountRPA.exe                         etkileşimli menü
  AlamountRPA.exe pca [--once|--watch|--file X]
  AlamountRPA.exe ise-giris               input\\ise_giris klasörünü işler
  AlamountRPA.exe ise-giris --tc 12345678901 --pdf X.pdf [--puantaj Y.xlsx]
  AlamountRPA.exe ocr belge.pdf [--cikti metin.txt]
  AlamountRPA.exe robot <görev> [robot seçenekleri]   (ör. robot mikro_personel_giris --variable KURU_CALISMA:hayir)
  AlamountRPA.exe gorevler                görev listesini yazar
  AlamountRPA.exe goruntu-yakala AD       ekrandan şablon keser (Citrix/RDP görüntü otomasyonu)
  AlamountRPA.exe goruntu-dene AD         şablonu şu anki ekranda arar
  AlamountRPA.exe kontrol                 kurulum kontrolü (Tesseract, dil paketleri, kütüphaneler)
  AlamountRPA.exe mcp                     yerel MCP sunucusu (bu bilgisayardaki araçlar)
  AlamountRPA.exe mcp --merkez URL        Claude Desktop ↔ Kontrol Merkezi köprüsü (ALAMOUNT_MCP_ANAHTARI)
  AlamountRPA.exe merkez                  Kontrol Merkezi (web paneli + robot API'si)
  AlamountRPA.exe merkez-parola admin     panel kullanıcısının parolasını sıfırlar
  AlamountRPA.exe merkez-mcp-anahtar ayse  kullanıcıya MCP anahtarı üretir (merkez makinesinde)
  AlamountRPA.exe merkez-robot ROBOT-1    robot ekler / anahtarını yeniler (merkez makinesinde)
  AlamountRPA.exe merkez-is pca [--robot R] [--degisken AD:deger] [--bekle 30]   iş başlatır
  AlamountRPA.exe ajan                    robot ajanı (merkezden iş alır)
  AlamountRPA.exe oturum-kur --kullanici .\\robot1   gözetimsiz robot: Windows oturumunu robot açar (yönetici)
  AlamountRPA.exe oturum-durum            oturumlar, otomatik oturum açma ve ajan durumu
  AlamountRPA.exe oturum-kaldir           gözetimsiz oturum ayarlarını geri alır (yönetici)
  AlamountRPA.exe kuyruk ise-giris-dagit  PDF'leri merkez kuyruğuna ekler
  AlamountRPA.exe kuyruk ise-giris-isle   merkez kuyruğundan alıp işler
  AlamountRPA.exe init                    eksik config.ini ve klasörleri oluşturur
Ortak seçenek: --config C:\\yol\\config.ini
"""

import argparse
import datetime as dt
import glob
import logging
import os
import sys

import ayarlar as ay
import pca_analiz

import marka
from marka import SURUM as VERSION
log = logging.getLogger("alamount")


AFIS = r"""
     _    _                                   _     ____  ____   _
    / \  | | __ _ _ __ ___   ___  _   _ _ __ | |_  |  _ \|  _ \ / \
   / _ \ | |/ _` | '_ ` _ \ / _ \| | | | '_ \| __| | |_) | |_) / _ \
  / ___ \| | (_| | | | | | | (_) | |_| | | | | |_  |  _ <|  __/ ___ \
 /_/   \_\_|\__,_|_| |_| |_|\___/ \__,_|_| |_|\__| |_| \_\_| /_/   \_\
"""


def _konsol_basligi(alt=""):
    """Windows konsol penceresinin başlığını ayarlar."""
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(f"{marka.URUN}{' · ' + alt if alt else ''}")
        except Exception:
            pass


def _konsol_utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def init(config_yolu):
    if not os.path.exists(config_yolu):
        with open(config_yolu, "w", encoding="utf-8") as f:
            f.write(ay.TAM_CONFIG)
        print(f"Oluşturuldu: {config_yolu}")
    a = ay.ayarlari_yukle(config_yolu)
    for k in ("giris", "cikti", "arsiv", "hata", "log"):
        a.folder(k)
    for sec, key in (("ISE_GIRIS", "giris"), ("ISE_GIRIS", "cikti"), ("ROBOT", "cikti")):
        a.yol(sec, key, olustur=True)
    print("Klasörler hazır.")
    return a


def gorev_yolu(ayarlar, gorev):
    if os.path.isfile(gorev):
        return os.path.abspath(gorev)
    klasor = ayarlar.yol("ROBOT", "gorev_klasoru")
    ad = gorev if gorev.endswith(".robot") else gorev + ".robot"
    p = os.path.join(klasor, ad)
    if not os.path.isfile(p):
        raise FileNotFoundError(f"Görev bulunamadı: {p}")
    return p


def gorevleri_listele(ayarlar):
    klasor = ayarlar.yol("ROBOT", "gorev_klasoru")
    return sorted(os.path.splitext(os.path.basename(p))[0] for p in glob.glob(os.path.join(klasor, "*.robot")))


def robot_calistir(ayarlar, gorev, ek_argumanlar=()):
    """Robot Framework görevini bu exe içindeki Python ile çalıştırır."""
    from robot import run_cli

    yol = gorev_yolu(ayarlar, gorev)
    cikti = os.path.join(ayarlar.yol("ROBOT", "cikti", olustur=True),
                         f"{os.path.splitext(os.path.basename(yol))[0]}_{dt.datetime.now():%Y%m%d_%H%M%S}")
    os.environ["ALAMOUNT_RPA_CONFIG"] = ayarlar.path
    gorev_adi = os.path.splitext(os.path.basename(yol))[0]
    args = ["--outputdir", cikti, "--pythonpath", os.path.dirname(yol),
            "--logtitle", f"{marka.URUN} · {gorev_adi} · Log", "--reporttitle", f"{marka.URUN} · {gorev_adi} · Rapor",
            *ek_argumanlar, yol]
    log.info("Robot görevi: %s → %s", os.path.basename(yol), cikti)
    kod = run_cli(args, exit=False)
    log.info("Robot görevi bitti (kod %s). Rapor: %s", kod, os.path.join(cikti, "log.html"))
    return kod


def kontrol(ayarlar):
    """Kurulum kontrolü."""
    sorun = 0

    def satir(ok, ad, detay=""):
        nonlocal sorun
        sorun += 0 if ok else 1
        print(f"  [{'OK' if ok else '!!'}] {ad}{' - ' + detay if detay else ''}")

    print(f"Alamount RPA v{VERSION}  |  config: {ayarlar.path}")
    import belge_ocr as bo

    m = bo.OcrMotoru(ayarlar)
    satir(m.hazir, "Tesseract OCR", m.cmd or "bulunamadı ([OCR] tesseract_yolu)")
    if m.hazir:
        diller = m.diller()
        for d in (ayarlar.get("OCR", "dil") or "tur").split("+"):
            satir(d in diller, f"Tesseract dil paketi '{d}'", "" if d in diller else "tessdata klasörüne ekleyin")
    for mod, ad in (("robot", "Robot Framework"), ("RPA.Browser.Selenium", "RPA.Browser"),
                    ("RPA.Excel.Files", "RPA.Excel"), ("RPA.PDF", "RPA.PDF"), ("pymupdf", "pymupdf"),
                    ("cv2", "opencv"), ("anthropic", "anthropic"), ("mcp", "MCP")):
        try:
            __import__(mod)
            satir(True, ad)
        except Exception as e:
            satir(False, ad, str(e)[:80])
    baglayicilar = ("RPA.Email.ImapSmtp", "RPA.Email.Exchange", "RPA.Outlook.Application", "RPA.SAP", "RPA.Database",
                    "RPA.HTTP", "RPA.FTP", "RPA.Cloud.Azure", "RPA.MSGraph", "RPA.Salesforce", "AlamountBaglayicilar")
    eksik = []
    for mod in baglayicilar:
        try:
            __import__(mod)
        except Exception:
            eksik.append(mod)
    satir(not eksik, f"Bağlayıcılar {len(baglayicilar) - len(eksik)}/{len(baglayicilar)}", ", ".join(eksik))
    try:
        import AlamountGoruntu  # noqa: F401
        import mss  # noqa: F401

        satir(True, "Görüntü otomasyonu (Citrix/RDP)")
    except Exception as e:
        satir(False, "Görüntü otomasyonu", str(e)[:80])
    if sys.platform.startswith("win"):
        try:
            __import__("RPA.Windows")
            satir(True, "RPA.Windows (UI Automation)")
        except Exception as e:
            satir(False, "RPA.Windows", str(e)[:80])
    else:
        print("  [--] RPA.Windows yalnızca Windows'ta")
    puantaj = ayarlar.yol("ISE_GIRIS", "puantaj")
    if os.path.isfile(puantaj):
        satir(True, "Puantaj dosyası", puantaj)
    else:  # kurulum hatası değil; dosya işe giriş öncesi konur
        print(f"  [--] Puantaj dosyası henüz yok - {puantaj}")
    llm = ayarlar.getbool("LLM", "aktif")
    anahtar = bool(ayarlar.get("LLM", "api_anahtari") or os.environ.get("ANTHROPIC_API_KEY"))
    print(f"  [--] LLM katmanı: {'AÇIK' if llm else 'kapalı'}" + (f", API anahtarı {'var' if anahtar else 'YOK'}" if llm else ""))
    if ayarlar.get("OTURUM", "mod") not in ("", "yok"):
        print(f"  [--] Gözetimsiz oturum: {ayarlar.get('OTURUM', 'mod')} ({ayarlar.get('OTURUM', 'kullanici')})")
    print(f"  Görevler: {', '.join(gorevleri_listele(ayarlar)) or '-'}")
    return 1 if sorun else 0


def ise_giris_cli(ayarlar, args):
    import ise_giris

    if args.tc:
        if not args.pdf:
            raise SystemExit("--tc ile birlikte --pdf verilmeli")
        r = ise_giris.hazirla(args.tc, args.pdf, args.puantaj or ayarlar.yol("ISE_GIRIS", "puantaj"), ayarlar)
        sonuclar = [r]
    else:
        sonuclar = ise_giris.klasoru_isle(ayarlar)
    hata = 0
    for r in sonuclar:
        if "hata" in r:
            hata += 1
            print(f"HATA  {r['dosya']}: {r['hata']}")
        else:
            print(f"HAZIR {r['excel']}")
            print("      " + ", ".join(f"{k}: {v}" for k, v in r["ozet"].items()))
            for u in r["uyarilar"]:
                print(f"      ! {u}")
    return 1 if hata else 0


def menu(config_yolu):
    secenekler = [
        ("PCA analizi (input klasörü)", ["pca", "--once"]),
        ("İşe giriş belgelerini hazırla (input\\ise_giris)", ["ise-giris"]),
        ("Mikro'ya giriş — KURU ÇALIŞMA (yalnızca log)", ["robot", "mikro_personel_giris", "--variable", "KURU_CALISMA:evet"]),
        ("Mikro'ya giriş — GERÇEK (Mikro açık olmalı)", ["robot", "mikro_personel_giris", "--variable", "KURU_CALISMA:hayir"]),
        ("Mikro ekran keşfi (locator çıkarma)", ["robot", "mikro_ekran_kesfi"]),
        ("Örnek: Not Defteri otomasyonu", ["robot", "ornek_masaustu_notepad"]),
        ("Örnek: Tarayıcı formu doldurma", ["robot", "ornek_tarayici"]),
        ("Örnek: Citrix/uzak masaüstü (görüntü + OCR)", ["robot", "ornek_citrix_goruntu"]),
        ("Kurulum kontrolü", ["kontrol"]),
        ("Kontrol Merkezi'ni başlat (sunucu makinesi)", ["merkez"]),
        ("Robot ajanını başlat (robot makinesi)", ["ajan"]),
    ]
    _konsol_basligi("Menü")
    print(AFIS)
    print(f"  {marka.URUN} v{VERSION} · {marka.SIRKET}\n  " + "─" * 46 + "\n")
    for i, (ad, _) in enumerate(secenekler, 1):
        print(f"  {i:>2}. {ad}")
    print("   0. Çıkış\n")
    try:
        sec = input("  Seçiminiz: ").strip()
    except EOFError:
        return 0
    if not sec.isdigit() or not (1 <= int(sec) <= len(secenekler)):
        return 0
    kod = main(secenekler[int(sec) - 1][1] + ["--config", config_yolu])
    input("\n  Devam etmek için Enter...")
    return kod


def main(argv=None):
    _konsol_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="AlamountRPA", description=f"Alamount RPA v{VERSION}")
    ap.add_argument("--config", default=ay.varsayilan_config_yolu())
    alt = ap.add_subparsers(dest="komut")
    p = alt.add_parser("pca", help="PCA analizi")
    p.add_argument("--once", action="store_true")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--file")
    p = alt.add_parser("ise-giris", help="İşe giriş verisi hazırla")
    p.add_argument("--tc")
    p.add_argument("--pdf")
    p.add_argument("--puantaj")
    p = alt.add_parser("ocr", help="PDF'i metne çevir")
    p.add_argument("dosya")
    p.add_argument("--cikti")
    p = alt.add_parser("robot", help="Robot Framework görevi çalıştır")
    p.add_argument("gorev")
    alt.add_parser("gorevler")
    p = alt.add_parser("goruntu-yakala", help="Ekrandan şablon görüntüsü kes (gorevler\\goruntuler\\AD.png)")
    p.add_argument("ad")
    p.add_argument("--gecikme", type=int, default=3, help="hedef ekranı açmanız için beklenecek saniye")
    p.add_argument("--klasor")
    p = alt.add_parser("goruntu-dene", help="Şablonu şu anki ekranda ara")
    p.add_argument("ad")
    p.add_argument("--guven", type=float, default=0.85)
    p.add_argument("--klasor")
    p = alt.add_parser("goruntu-demo", help="Görüntü otomasyonu demo penceresi (örnek görev açar)")
    p.add_argument("--cikti", required=True)
    p.add_argument("--sure", type=int, default=120)
    alt.add_parser("kontrol")
    p = alt.add_parser("mcp", help="MCP sunucusu (yerel) ya da --merkez ile Kontrol Merkezi köprüsü")
    p.add_argument("--merkez", help="Kontrol Merkezi MCP adresi, ör. https://rpa-sunucu:8765/mcp (Claude Desktop köprüsü)")
    p.add_argument("--anahtar", help="MCP anahtarı (önerilen: ALAMOUNT_MCP_ANAHTARI ortam değişkeni)")
    p.add_argument("--ca-dosyasi", default="", help="Kendinden imzalı sertifika için CA dosyası")
    alt.add_parser("merkez")
    p = alt.add_parser("merkez-parola")
    p.add_argument("kullanici")
    p = alt.add_parser("merkez-mcp-anahtar")
    p.add_argument("kullanici")
    p.add_argument("--ad", default="komut satırı")
    p = alt.add_parser("merkez-robot")
    p.add_argument("robot")
    p = alt.add_parser("merkez-is")
    p.add_argument("surec")
    p.add_argument("--robot", default="")
    p.add_argument("--degisken", action="append", default=[])
    p.add_argument("--deneme", type=int, default=1)
    p.add_argument("--bekle", type=float, default=0, help="dakika; iş bitene kadar bekler")
    alt.add_parser("ajan")
    p = alt.add_parser("oturum-kur", help="Gözetimsiz robot: otomatik oturum açma + ajan + oturum gözetmeni")
    p.add_argument("--kullanici", required=True, help=r"robot Windows kullanıcısı: .\robot1 ya da ALAN\robot1")
    p.add_argument("--parola", help="verilmezse sorulur (önerilen) ya da --parola-varligi ile kasadan alınır")
    p.add_argument("--parola-varligi", default="", help="merkez kasasındaki varlık adı (parola değişince güncellenir)")
    p.add_argument("--yeniden-giris", choices=["evet", "hayir"], default="evet",
                   help="oturum kapatılınca Windows robotla yeniden giriş yapsın")
    alt.add_parser("oturum-durum")
    alt.add_parser("oturum-kaldir")
    p = alt.add_parser("oturum-gozetmen")
    p.add_argument("--tek-sefer", action="store_true")
    p = alt.add_parser("kuyruk")
    p.add_argument("islem", choices=["ise-giris-dagit", "ise-giris-isle"])
    alt.add_parser("init")

    # robot alt komutundan sonraki her şey Robot'a aynen geçer
    robot_ek = []
    if "robot" in argv:
        i = argv.index("robot")
        if i + 1 < len(argv):
            robot_ek = argv[i + 2:]
            argv = argv[:i + 2]
    args = ap.parse_args(argv)

    if args.komut is None:
        return menu(args.config)
    if args.komut == "mcp" and args.merkez:  # Claude Desktop köprüsü: config.ini gerekmez, stdout protokole ait
        import mcp_kopru

        return mcp_kopru.calistir(args.merkez, args.anahtar or os.environ.get("ALAMOUNT_MCP_ANAHTARI", ""),
                                  args.ca_dosyasi)
    _konsol_basligi({"merkez": "Kontrol Merkezi", "ajan": "Robot Ajanı"}.get(args.komut, args.komut))
    if args.komut == "init":
        init(args.config)
        return 0
    if not os.path.exists(args.config):
        init(args.config)
    ayarlar = ay.ayarlari_yukle(args.config)

    if args.komut == "mcp":  # stdout MCP protokolüne ayrılmıştır; log yalnızca dosyaya
        pca_analiz.setup_logging(ayarlar)
        for h in list(log.handlers):
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
                log.removeHandler(h)
        import mcp_sunucu

        mcp_sunucu.calistir(args.config)
        return 0

    pca_analiz.setup_logging(ayarlar)
    if args.komut == "merkez":
        import merkez_sunucu

        merkez_sunucu.calistir(ayarlar)
        return 0
    if args.komut == "merkez-parola":
        import merkez_sunucu

        print(f"{args.kullanici} için yeni parola: {merkez_sunucu.sifre_sifirla(ayarlar, args.kullanici)}")
        return 0
    if args.komut == "merkez-mcp-anahtar":
        import merkez_sunucu

        print(merkez_sunucu.mcp_anahtari_olustur(ayarlar, args.kullanici, args.ad))
        return 0
    if args.komut == "merkez-robot":
        import merkez_sunucu

        print(f"[AJAN]\nrobot_adi = {args.robot}\nrobot_anahtari = {merkez_sunucu.robot_olustur(ayarlar, args.robot)}")
        return 0
    if args.komut == "merkez-is":
        import merkez_sunucu

        return merkez_sunucu.is_olustur(ayarlar, args.surec, args.robot, args.degisken, args.deneme, args.bekle)
    if args.komut == "ajan":
        import ajan

        return ajan.calistir(ayarlar, VERSION)
    if args.komut.startswith("oturum-"):
        import oturum

        if args.komut == "oturum-durum":
            return oturum.durum(ayarlar)
        if args.komut == "oturum-kaldir":
            return oturum.kaldir(ayarlar)
        if args.komut == "oturum-gozetmen":
            return oturum.gozetmen(ayarlar, args.tek_sefer)
        try:
            return oturum.kur(ayarlar, args.kullanici, args.parola, args.parola_varligi, args.yeniden_giris == "evet")
        except ValueError as e:
            print(f"HATA: {e}")
            return 1
    # Ajanın başlattığı işler (ya da [AJAN] ayarlı makine): config'teki varlik:AD değerleri merkezden çözülür
    if os.environ.get("ALAMOUNT_MERKEZ_URL") or ayarlar.cp.get("AJAN", "merkez_url", fallback="").strip():
        import merkez_istemci

        merkez_istemci.varlik_cozucu_kur(ayarlar)
    if args.komut == "kuyruk":
        import kuyruk_isleri

        return kuyruk_isleri.dagit(ayarlar) if args.islem == "ise-giris-dagit" else kuyruk_isleri.isle(ayarlar)
    if args.komut == "pca":
        a = ["--config", args.config] + (["--once"] if args.once else ["--watch"] if args.watch else []) + \
            (["--file", args.file] if args.file else [])
        return pca_analiz.main(a)
    if args.komut == "ise-giris":
        return ise_giris_cli(ayarlar, args)
    if args.komut == "ocr":
        import belge_ocr as bo

        txt = bo.pdf_metne_cevir(args.dosya, ayarlar, args.cikti)
        if not args.cikti:
            print(txt)
        return 0
    if args.komut == "robot":
        return robot_calistir(ayarlar, args.gorev, robot_ek)
    if args.komut == "gorevler":
        print("\n".join(gorevleri_listele(ayarlar)))
        return 0
    if args.komut == "kontrol":
        return kontrol(ayarlar)
    if args.komut in ("goruntu-yakala", "goruntu-dene", "goruntu-demo"):
        import goruntu_araclari as ga

        if args.komut == "goruntu-yakala":
            return ga.yakala(ayarlar, args.ad, args.klasor, args.gecikme)
        if args.komut == "goruntu-dene":
            return ga.dene(ayarlar, args.ad, args.guven, args.klasor)
        return ga.demo(ayarlar, args.cikti, args.sure)
    return 0


if __name__ == "__main__":
    sys.exit(main())
