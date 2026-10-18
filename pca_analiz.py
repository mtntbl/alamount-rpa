# -*- coding: utf-8 -*-
"""
Alamount RPA · PCA analizi
==========================
PCA_Example.ipynb'deki analizi otomatikleştirir:

  1. config.ini'deki giriş klasörünü tarar (*.txt / *.csv / *.xlsx).
  2. Her dosyayı okur, istenmeyen sütunları atar, metin sütunlarını LabelEncoder ile sayıya çevirir.
  3. StandardScaler + PCA uygular.
  4. Çıktı klasörüne Excel raporu ve grafikler (3B saçılım, kümülatif varyans) yazar.
  5. İşlenen dosyayı arşive, hatalıyı hata klasörüne taşır, log tutar.
  6. (İsteğe bağlı) Sonuçları e-posta ile gönderir.

Kullanım:
  AlamountRPA.exe pca                -> config.ini'deki moda göre çalışır
  AlamountRPA.exe pca --once          -> klasördeki dosyaları bir kez işler ve çıkar (Görev Zamanlayıcı için)
  AlamountRPA.exe pca --watch         -> klasörü sürekli izler
  AlamountRPA.exe pca --config X.ini  -> farklı konfigürasyon dosyası
  AlamountRPA.exe init              -> varsayılan config.ini ve klasörleri oluşturur
"""

import argparse
import configparser
import fnmatch
import logging
import os
import shutil
import smtplib
import sys
import time
import traceback
from datetime import datetime
from email.message import EmailMessage
from logging.handlers import TimedRotatingFileHandler

import matplotlib

matplotlib.use("Agg")  # ekransız ortamda (Görev Zamanlayıcı) çalışabilmek için

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.preprocessing import LabelEncoder, StandardScaler  # noqa: E402

from marka import SURUM as VERSION, URUN
log = logging.getLogger("alamount")

# config.ini'de "varlik:AD" / "varlik:AD.kullanici" değerleri bu fonksiyonla çözülür (merkez ya da ajan ayarlar)
VARLIK_COZUCU = None

DEFAULT_CONFIG = """\
; =====================================================================
;  Alamount RPA - Konfigürasyon
;  Göreli yollar AlamountRPA.exe'nin bulunduğu klasöre göredir.
;  evet/hayir, true/false, 1/0 değerleri kabul edilir.
; =====================================================================

[GENEL]
; once  : klasördeki dosyaları bir kez işle ve kapan (Görev Zamanlayıcı için önerilir)
; watch : klasörü sürekli izle
mod = once
; watch modunda klasörün kaç saniyede bir kontrol edileceği
kontrol_araligi_sn = 60
; Dosya hâlâ kopyalanıyor olabilir; son değişiklikten en az kaç saniye geçmiş olmalı
dosya_bekleme_sn = 5
; Log seviyesi: DEBUG, INFO, WARNING, ERROR
log_seviyesi = INFO

[KLASORLER]
giris = input
cikti = output
arsiv = archive
hata  = error
log   = logs

[VERI]
; Noktalı virgülle ayrılmış dosya desenleri
dosya_desenleri = *.txt;*.csv;*.xlsx;*.xls
; Metin dosyası ayırıcı: tab, virgul, noktali_virgul, pipe, auto ya da tek karakter
ayirici = tab
; Karakter kodlaması: auto (utf-8 -> cp1254 -> latin-1 dener), utf-8, cp1254 ...
kodlama = auto
; Excel dosyalarında okunacak sayfa (ad ya da 0'dan başlayan sıra)
excel_sayfa = 0
; Analizden çıkarılacak sütunlar (virgülle). Sütun adlarındaki ' ve " işaretleri otomatik temizlenir.
cikarilacak_sutunlar = TASKCENTER_DESCRIPTION, CODE_DESCRIPTION
; LabelEncoder uygulanacak sütunlar:
;   auto -> sayısal olmayan tüm sütunlar
;   all  -> tüm sütunlar (orijinal notebook davranışı)
;   ya da virgülle sütun listesi
kodlanacak_sutunlar = auto
; Boş değerler: sil (satırı at) | sifir (0 ile doldur) | ortalama (sütun ortalaması)
bos_deger = ortalama

[PCA]
bilesen_sayisi = 3
standartlastir = evet

[GRAFIK]
grafik_uret = evet
; Noktaları renklendirmek için kullanılacak sütun (ham değer kullanılır, kodlanmış değil)
renk_sutunu = DURATION_SECONDS
; renk_sutunu < esik -> renk_alti, aksi halde renk_ustu
renk_esigi = 3600
renk_alti = red
renk_ustu = blue
dpi = 120

[CIKTI]
excel_rapor = evet
; PCA skorlarına orijinal satırları da ekle
orijinal_veriyi_ekle = evet
; Her dosya için zaman damgalı alt klasör oluştur
alt_klasor = evet
; İşlenen dosyayı arşive taşı (hayir ise giriş klasöründe kalır ve tekrar işlenmez diye .done işareti konur)
arsive_tasi = evet

[EMAIL]
aktif = hayir
smtp_sunucu = smtp.office365.com
smtp_port = 587
; guvenlik: starttls | ssl | yok
guvenlik = starttls
kullanici = kullanici@firma.com
; Şifreyi buraya yazmak istemezseniz ALAMOUNT_SMTP_SIFRE ortam değişkenini kullanın
sifre =
gonderen = kullanici@firma.com
; Virgülle birden fazla alıcı
alicilar = alici1@firma.com, alici2@firma.com
konu = Alamount RPA · PCA Raporu - {dosya}
; Hata durumunda da e-posta gönder
hata_bildir = evet
"""


# --------------------------------------------------------------------------- yardımcılar
def app_dir():
    """exe (veya script) klasörü."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resolve(path, base):
    path = os.path.expandvars(os.path.expanduser(path.strip()))
    if os.sep == "/":  # config.ini Windows ayırıcısıyla yazılmış olabilir
        path = path.replace("\\", "/")
    return path if os.path.isabs(path) else os.path.join(base, path)


def split_list(value, sep=","):
    return [v.strip() for v in (value or "").split(sep) if v.strip()]


def clean_col(name):
    return str(name).strip().strip("'\"").strip()


class Settings:
    def __init__(self, path):
        self.path = path
        self.base = os.path.dirname(os.path.abspath(path))
        cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";", "#"))
        cp.read_string(DEFAULT_CONFIG)  # varsayılanlar
        with open(path, encoding="utf-8-sig") as f:
            cp.read_file(f)
        self.cp = cp

    def get(self, sec, key):
        deger = self.cp.get(sec, key, fallback="").strip()
        if deger.lower().startswith("varlik:"):
            ad, _, alan = deger[7:].strip().partition(".")
            if VARLIK_COZUCU is None:
                raise RuntimeError(f"[{sec}] {key} = {deger}: varlıklar yalnızca Kontrol Merkezi'ne bağlıyken çözülebilir")
            return VARLIK_COZUCU(ad, alan)
        return deger

    def getbool(self, sec, key):
        v = self.get(sec, key).lower()
        return v in ("1", "true", "evet", "yes", "e", "on", "acik", "açık")

    def getint(self, sec, key):
        return int(float(self.get(sec, key)))

    def getfloat(self, sec, key):
        return float(self.get(sec, key))

    def folder(self, key):
        p = resolve(self.get("KLASORLER", key), self.base)
        os.makedirs(p, exist_ok=True)
        return p


def setup_logging(settings):
    log_dir = settings.folder("log")
    level = getattr(logging, settings.get("GENEL", "log_seviyesi").upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(level)
    log.handlers.clear()
    fh = TimedRotatingFileHandler(
        os.path.join(log_dir, "alamount_rpa.log"), when="midnight", backupCount=30, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    log.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(sh)


# --------------------------------------------------------------------------- veri okuma
SEPARATORS = {"tab": "\t", "\\t": "\t", "virgul": ",", "noktali_virgul": ";", "pipe": "|", "auto": None}


def read_input(path, settings):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls", ".xlsm"):
        sheet = settings.get("VERI", "excel_sayfa") or 0
        if str(sheet).isdigit():
            sheet = int(sheet)
        df = pd.read_excel(path, sheet_name=sheet)
    else:
        sep_cfg = settings.get("VERI", "ayirici")
        sep = SEPARATORS.get(sep_cfg.lower(), sep_cfg)
        enc_cfg = settings.get("VERI", "kodlama").lower()
        encodings = ["utf-8-sig", "cp1254", "latin-1"] if enc_cfg in ("", "auto") else [enc_cfg]
        last_err = None
        for enc in encodings:
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, engine="python" if sep is None else "c")
                log.debug("Dosya %s kodlamasıyla okundu", enc)
                break
            except UnicodeDecodeError as e:
                last_err = e
        else:
            raise last_err
    df.columns = [clean_col(c) for c in df.columns]
    if df.empty:
        raise ValueError("Dosyada veri yok")
    return df


def prepare(df, settings):
    """Analiz matrisini hazırlar. (X, ham_df) döner; ham_df X ile aynı satırları içerir."""
    raw = df.copy()
    drop = [clean_col(c) for c in split_list(settings.get("VERI", "cikarilacak_sutunlar"))]
    missing = [c for c in drop if c not in raw.columns]
    if missing:
        log.warning("Çıkarılacak sütun(lar) dosyada yok, atlandı: %s", ", ".join(missing))
    X = raw.drop(columns=[c for c in drop if c in raw.columns])

    enc_cfg = settings.get("VERI", "kodlanacak_sutunlar")
    if enc_cfg.lower() == "auto":
        enc_cols = [c for c in X.columns if not pd.api.types.is_numeric_dtype(X[c])]
    elif enc_cfg.lower() == "all":
        enc_cols = list(X.columns)
    else:
        enc_cols = [clean_col(c) for c in split_list(enc_cfg) if clean_col(c) in X.columns]
    for c in enc_cols:
        X[c] = LabelEncoder().fit_transform(X[c].astype(str))
    log.info("LabelEncoder uygulanan sütunlar: %s", ", ".join(enc_cols) or "-")

    # Kalan sayısal olmayanları sayıya zorla
    for c in X.columns:
        if not pd.api.types.is_numeric_dtype(X[c]):
            X[c] = pd.to_numeric(X[c], errors="coerce")

    # Sabit (varyansı sıfır) ya da tamamen boş sütunları at
    const = [c for c in X.columns if X[c].nunique(dropna=True) <= 1]
    if const:
        log.warning("Sabit/boş sütunlar analizden çıkarıldı: %s", ", ".join(const))
        X = X.drop(columns=const)

    strategy = settings.get("VERI", "bos_deger").lower()
    if X.isna().any().any():
        if strategy == "sil":
            keep = X.dropna().index
            X, raw = X.loc[keep], raw.loc[keep]
        elif strategy == "sifir":
            X = X.fillna(0)
        else:
            X = X.fillna(X.mean(numeric_only=True))
    if X.shape[1] < 2 or X.shape[0] < 2:
        raise ValueError(f"PCA için yetersiz veri: {X.shape[0]} satır, {X.shape[1]} sütun")
    return X.reset_index(drop=True), raw.reset_index(drop=True)


# --------------------------------------------------------------------------- analiz
def run_pca(X, settings):
    data = X.values.astype(float)
    if settings.getbool("PCA", "standartlastir"):
        data = StandardScaler().fit_transform(data)
    n = min(settings.getint("PCA", "bilesen_sayisi"), X.shape[1], X.shape[0])
    pca = PCA(n_components=n).fit(data)
    scores = pd.DataFrame(pca.transform(data), columns=[f"PC{i + 1}" for i in range(n)])
    full = PCA().fit(data)  # kümülatif varyans için tüm bileşenler
    variance = pd.DataFrame(
        {
            "Bilesen": [f"PC{i + 1}" for i in range(len(full.explained_variance_ratio_))],
            "Aciklanan_Varyans_Orani": full.explained_variance_ratio_,
            "Kumulatif_Varyans": np.cumsum(full.explained_variance_ratio_),
        }
    )
    loadings = pd.DataFrame(pca.components_.T, index=X.columns, columns=scores.columns)
    loadings.index.name = "Sutun"
    return pca, scores, variance, loadings


def make_colors(raw, settings):
    col = clean_col(settings.get("GRAFIK", "renk_sutunu"))
    if col and col in raw.columns:
        vals = pd.to_numeric(raw[col], errors="coerce")
        thr = settings.getfloat("GRAFIK", "renk_esigi")
        lo, hi = settings.get("GRAFIK", "renk_alti"), settings.get("GRAFIK", "renk_ustu")
        return [lo if v < thr else hi for v in vals.fillna(thr)], f"{col} < {thr:g}: {lo} / >= {thr:g}: {hi}"
    if col:
        log.warning("Renk sütunu '%s' bulunamadı, tek renk kullanılıyor", col)
    return "#04BAF3", ""


def save_plots(scores, variance, raw, settings, out_dir, stem):
    files = []
    dpi = settings.getint("GRAFIK", "dpi")
    colors, legend = make_colors(raw, settings)

    fig = plt.figure(figsize=(9, 7))
    if scores.shape[1] >= 3:
        ax = fig.add_subplot(111, projection="3d")
        ax.scatter(scores["PC1"], scores["PC2"], scores["PC3"], c=colors, s=12, alpha=0.7)
        ax.set_zlabel("PC3")
    else:
        ax = fig.add_subplot(111)
        ax.scatter(scores["PC1"], scores["PC2"], c=colors, s=12, alpha=0.7)
    ax.set_xlabel("PC1")
    ax.set_ylabel("PC2")
    ax.set_title(f"PCA - {stem}\n{legend}", fontsize=10, color="#022351")
    fig.text(0.99, 0.01, URUN, ha="right", va="bottom", fontsize=8, color="#04BAF3")
    p = os.path.join(out_dir, f"{stem}_pca_scatter.png")
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    files.append(p)

    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(1, len(variance) + 1)
    ax.bar(x, variance["Aciklanan_Varyans_Orani"], color="#04BAF3", alpha=0.75, label="Bileşen")
    ax.step(x, variance["Kumulatif_Varyans"], where="mid", color="#022351", label="Kümülatif")
    ax.set_xlabel("Bileşen")
    ax.set_ylabel("Açıklanan varyans oranı")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(x)
    ax.legend()
    ax.set_title(f"Açıklanan Varyans - {stem}", color="#022351")
    fig.text(0.99, 0.01, URUN, ha="right", va="bottom", fontsize=8, color="#04BAF3")
    p = os.path.join(out_dir, f"{stem}_variance.png")
    fig.savefig(p, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    files.append(p)
    return files


def save_excel(scores, variance, loadings, raw, pca, src, settings, out_dir, stem):
    p = os.path.join(out_dir, f"{stem}_pca_rapor.xlsx")
    summary = pd.DataFrame(
        {
            "Alan": [
                "Kaynak dosya", "İşlem zamanı", "Satır sayısı", "Analize giren sütunlar",
                "Bileşen sayısı", "Seçili bileşenlerin açıkladığı toplam varyans", f"{URUN} sürümü",
            ],
            "Deger": [
                os.path.basename(src), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(scores),
                ", ".join(loadings.index), pca.n_components_,
                round(float(np.sum(pca.explained_variance_ratio_)), 6), VERSION,
            ],
        }
    )
    sc = pd.concat([scores, raw], axis=1) if settings.getbool("CIKTI", "orijinal_veriyi_ekle") else scores
    with pd.ExcelWriter(p, engine="openpyxl") as w:
        summary.to_excel(w, sheet_name="Ozet", index=False)
        variance.to_excel(w, sheet_name="Varyans", index=False)
        loadings.to_excel(w, sheet_name="Yukler")
        sc.to_excel(w, sheet_name="PCA_Skorlari", index=False)
        w.book.properties.creator = URUN
        for ws in w.book.worksheets:
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
    return p


# --------------------------------------------------------------------------- e-posta
def send_mail(settings, subject, body, attachments=()):
    if not settings.getbool("EMAIL", "aktif"):
        return
    try:
        msg = EmailMessage()
        msg["From"] = settings.get("EMAIL", "gonderen") or settings.get("EMAIL", "kullanici")
        msg["To"] = ", ".join(split_list(settings.get("EMAIL", "alicilar")))
        msg["Subject"] = subject
        msg.set_content(body)
        for a in attachments:
            with open(a, "rb") as f:
                sub = "png" if a.lower().endswith(".png") else "octet-stream"
                main = "image" if sub == "png" else "application"
                msg.add_attachment(f.read(), maintype=main, subtype=sub, filename=os.path.basename(a))
        host, port = settings.get("EMAIL", "smtp_sunucu"), settings.getint("EMAIL", "smtp_port")
        sec = settings.get("EMAIL", "guvenlik").lower()
        smtp = smtplib.SMTP_SSL(host, port, timeout=60) if sec == "ssl" else smtplib.SMTP(host, port, timeout=60)
        with smtp:
            if sec == "starttls":
                smtp.starttls()
            user = settings.get("EMAIL", "kullanici")
            pwd = settings.get("EMAIL", "sifre") or os.environ.get("ALAMOUNT_SMTP_SIFRE", "")
            if user and pwd:
                smtp.login(user, pwd)
            smtp.send_message(msg)
        log.info("E-posta gönderildi: %s", msg["To"])
    except Exception as e:  # e-posta hatası işlemi durdurmasın
        log.error("E-posta gönderilemedi: %s", e)


# --------------------------------------------------------------------------- iş akışı
def unique_path(path):
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    return f"{root}_{datetime.now():%Y%m%d_%H%M%S}{ext}"


def process_file(path, settings):
    name = os.path.basename(path)
    stem = os.path.splitext(name)[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.info("İşleniyor: %s", name)
    started = time.time()
    try:
        out_dir = settings.folder("cikti")
        if settings.getbool("CIKTI", "alt_klasor"):
            out_dir = os.path.join(out_dir, f"{stem}_{ts}")
            os.makedirs(out_dir, exist_ok=True)

        df = read_input(path, settings)
        log.info("Okundu: %d satır, %d sütun", *df.shape)
        X, raw = prepare(df, settings)
        pca, scores, variance, loadings = run_pca(X, settings)
        total = float(np.sum(pca.explained_variance_ratio_))
        log.info("PCA tamam: %d bileşen, toplam açıklanan varyans %.4f", pca.n_components_, total)

        outputs = []
        if settings.getbool("CIKTI", "excel_rapor"):
            outputs.append(save_excel(scores, variance, loadings, raw, pca, path, settings, out_dir, stem))
        if settings.getbool("GRAFIK", "grafik_uret"):
            outputs += save_plots(scores, variance, raw, settings, out_dir, stem)
        for o in outputs:
            log.info("Çıktı: %s", o)

        if settings.getbool("CIKTI", "arsive_tasi"):
            dest = unique_path(os.path.join(settings.folder("arsiv"), name))
            shutil.move(path, dest)
            log.info("Arşive taşındı: %s", dest)
        else:
            open(path + ".done", "w").close()

        cum = ", ".join(f"{v:.3f}" for v in variance["Kumulatif_Varyans"])
        send_mail(
            settings,
            settings.get("EMAIL", "konu").replace("{dosya}", name),
            f"{name} dosyası işlendi.\n\nSatır: {len(scores)}\nBileşen: {pca.n_components_}\n"
            f"Toplam açıklanan varyans: {total:.4f}\nKümülatif varyans: {cum}\n"
            f"Süre: {time.time() - started:.1f} sn\nÇıktı klasörü: {out_dir}\n",
            outputs,
        )
        return True
    except Exception as e:
        log.error("HATA (%s): %s\n%s", name, e, traceback.format_exc())
        try:
            if os.path.exists(path):
                dest = unique_path(os.path.join(settings.folder("hata"), name))
                shutil.move(path, dest)
                with open(dest + ".hata.txt", "w", encoding="utf-8") as f:
                    f.write(traceback.format_exc())
                log.info("Hata klasörüne taşındı: %s", dest)
        except Exception as move_err:
            log.error("Dosya hata klasörüne taşınamadı: %s", move_err)
        if settings.getbool("EMAIL", "hata_bildir"):
            send_mail(settings, f"Alamount RPA · PCA HATA - {name}", f"{name} işlenemedi:\n\n{traceback.format_exc()}")
        return False


def find_files(settings):
    in_dir = settings.folder("giris")
    patterns = split_list(settings.get("VERI", "dosya_desenleri"), ";")
    wait = settings.getfloat("GENEL", "dosya_bekleme_sn")
    now = time.time()
    found = []
    for n in sorted(os.listdir(in_dir)):
        p = os.path.join(in_dir, n)
        if not os.path.isfile(p) or n.startswith(("~$", ".")) or os.path.exists(p + ".done"):
            continue
        if not any(fnmatch.fnmatch(n.lower(), pat.lower()) for pat in patterns):
            continue
        if now - os.path.getmtime(p) < wait:
            log.debug("Henüz yazılıyor olabilir, sonraki tura bırakıldı: %s", n)
            continue
        found.append(p)
    return found


def run_once(settings):
    files = find_files(settings)
    if not files:
        log.info("İşlenecek dosya yok (%s)", settings.folder("giris"))
        return 0, 0
    ok = sum(process_file(f, settings) for f in files)
    log.info("Tur bitti: %d başarılı, %d hatalı", ok, len(files) - ok)
    return ok, len(files) - ok


def init_files(config_path):
    if not os.path.exists(config_path):
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG)
        print(f"Oluşturuldu: {config_path}")
    s = Settings(config_path)
    for k in ("giris", "cikti", "arsiv", "hata", "log"):
        print(f"Klasör hazır: {s.folder(k)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=f"Alamount RPA v{VERSION}")
    ap.add_argument("--config", default=os.path.join(app_dir(), "config.ini"), help="config.ini yolu")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--once", action="store_true", help="Bir kez çalış ve çık")
    g.add_argument("--watch", action="store_true", help="Klasörü sürekli izle")
    ap.add_argument("--init", action="store_true", help="Varsayılan config.ini ve klasörleri oluştur")
    ap.add_argument("--file", help="Yalnızca bu dosyayı işle")
    args = ap.parse_args(argv)

    if args.init:
        init_files(args.config)
        return 0
    if not os.path.exists(args.config):
        print(f"config.ini bulunamadı: {args.config}\nOluşturmak için: AlamountRPA.exe init")
        init_files(args.config)

    settings = Settings(args.config)
    setup_logging(settings)
    mode = "watch" if args.watch else "once" if args.once else settings.get("GENEL", "mod").lower()
    log.info("Alamount RPA · PCA v%s başladı | mod=%s | config=%s", VERSION, mode, args.config)

    if args.file:
        return 0 if process_file(os.path.abspath(args.file), settings) else 1
    if mode == "watch":
        interval = settings.getfloat("GENEL", "kontrol_araligi_sn")
        log.info("İzleme modu: %s klasörü %g sn'de bir kontrol ediliyor (Ctrl+C ile durdurun)",
                 settings.folder("giris"), interval)
        try:
            while True:
                try:
                    run_once(settings)
                except Exception as e:
                    log.error("Tur hatası: %s", e)
                time.sleep(interval)
        except KeyboardInterrupt:
            log.info("Kullanıcı tarafından durduruldu")
            return 0
    _, failed = run_once(settings)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
