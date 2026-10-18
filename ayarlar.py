# -*- coding: utf-8 -*-
"""Ortak ayarlar: PCA varsayılanları + belge/OCR/işe giriş/LLM/robot bölümleri."""

import os
import shutil
import sys

import pca_analiz

EK_CONFIG = """
; =====================================================================
;  BELGE İŞLEME / OCR / İŞE GİRİŞ / ROBOT / LLM
; =====================================================================

[OCR]
; Tesseract yolu. Paketle gelen sürüm: tesseract\\tesseract.exe
; Boş bırakılırsa PATH ve C:\\Program Files\\Tesseract-OCR aranır.
tesseract_yolu = tesseract\\tesseract.exe
; Dil(ler): tur, eng ya da tur+eng
dil = tur+eng
; PDF sayfalarını görsele çevirirken çözünürlük (OCR için 300 önerilir)
dpi = 300
; Tesseract sayfa bölümleme modu. 3 = otomatik, 4 = tek sütun, 6 = tek blok, 11 = dağınık metin
psm_belge = 4
psm_kimlik = 11
; Sayfada bu kadar karakterden az metin katmanı varsa taranmış kabul edilir ve OCR yapılır
min_metin_karakter = 40
; Görselleri gri/eşikleme ile iyileştir
on_isleme = evet
; Ara görselleri (sayfa PNG'leri, kırpılmış kimlik) çıktı klasörüne kaydet
ara_gorselleri_kaydet = evet

[ISE_GIRIS]
; Personel PDF'lerinin bırakılacağı klasör. Dosya adında 11 haneli TC olmalı (ör. 12345678901.pdf)
giris = input\\ise_giris
; Puantaj Excel dosyası (tam yol ya da exe klasörüne göre)
puantaj = input\\ise_giris\\PUANTAJ BİLGİLERİ.xlsx
puantaj_sayfa = GİRİŞ
; Çıktı klasörü
cikti = output\\ise_giris
; İşlenen PDF'i arşive taşı
arsive_tasi = evet
; Kurallar (checklist): Sedef istisnası uygulanacak birim adları (virgülle)
sedef_birimleri = SEDEF
; Loglarda TC'yi maskele (KVKK)
tc_maskele = evet

[LLM]
; Ajan katmanı (opsiyonel). Düzen değişince / OCR'ın okuyamadığı alanlarda Claude'a sorar.
; DİKKAT: Etkinleştirilirse kişisel veriler (kimlik görüntüsü, OCR metni) Anthropic API'sine gönderilir.
; KVKK açısından kurum onayı alınmadan açmayın.
aktif = hayir
; API anahtarı ANTHROPIC_API_KEY ortam değişkeninden okunur. İsterseniz buraya yazabilirsiniz.
api_anahtari =
model = claude-opus-5-5
; low | medium | high  (düşük = daha ucuz/hızlı)
effort = medium
; Kimlik kartı görüntüsünü de gönder (görsel okuma)
gorsel_gonder = evet
; Yalnızca kural/OCR ile bulunamayan alanlar için çağır
sadece_eksikler = evet

[ROBOT]
; Robot Framework görev dosyalarının klasörü
gorev_klasoru = gorevler
; Robot log/rapor klasörü
cikti = logs\\robot
; Mikro giriş robotunda gerçek tuş/tıklama yerine yalnızca log yaz (güvenli deneme)
kuru_calisma = evet

; =====================================================================
;  KONTROL MERKEZİ (yalnızca merkez makinesinde: AlamountRPA.exe merkez)
;  Herhangi bir değer yerine varlik:AD (parola) ya da varlik:AD.kullanici yazılabilir;
;  değer merkezin şifreli kasasından okunur.
; =====================================================================

[MERKEZ]
; Veritabanı, kasa anahtarı ve robot raporları burada tutulur — YEDEKLEYİN
veri_klasoru = merkez_veri
adres = 0.0.0.0
port = 8765
; Bildirimlerdeki bağlantılar için panelin adresi (ör. https://rpa-sunucu:8765)
panel_url =
; HTTPS için PEM sertifika ve anahtar dosyaları (önerilir)
ssl_sertifika =
ssl_anahtar =
; Bu kadar saniye nabız gelmeyen robot çevrimdışı sayılır
cevrimdisi_esik_sn = 90
; Robotu bu kadar saniye sessiz kalan 'çalışıyor' iş başarısız sayılır (deneme hakkı varsa yeniden kuyruğa alınır)
sahipsiz_is_esik_sn = 300
; Biten iş, kuyruk öğesi ve denetim kayıtları kaç gün saklansın
saklama_gun = 90

[BILDIRIM]
; Bildirim gönderilecek olaylar (virgülle):
;   is_basarisiz, is_basarili, robot_cevrimdisi, robot_cevrimici, oge_basarisiz
olaylar = is_basarisiz, robot_cevrimdisi, robot_cevrimici, oge_basarisiz
; E-posta: [EMAIL] bölümündeki SMTP ayarları kullanılır
eposta = hayir
; Boşsa [EMAIL] alicilar kullanılır
eposta_alicilar =
; Teams: kanal > Workflows > "Post to a channel when a webhook request is received" ile alınan URL
; (URL'yi varlık olarak saklamak için: teams_webhook = varlik:TEAMS_WEBHOOK)
teams_webhook =

[MCP]
; LLM entegrasyonu (Microsoft Copilot, Claude Desktop vb.): merkez üzerinde /mcp uç noktası.
; Kullanıcılar panelde "MCP / LLM" sayfasından kendi anahtarlarını alır; LLM o kullanıcının rolüyle çalışır.
aktif = hayir
; Kişisel veriler (ad soyad, TC, iş logları) LLM'e gönderilsin mi? hayir: TC maskelenir, ad ve loglar gönderilmez.
; DİKKAT: LLM bulut tabanlıysa gönderilen her şey sağlayıcının sunucularına gider (KVKK).
kisisel_veri_paylas = hayir

; =====================================================================
;  ROBOT AJANI (robot makinelerinde: AlamountRPA.exe ajan)
; =====================================================================

[AJAN]
; Kontrol Merkezi adresi, ör. http://rpa-sunucu:8765
merkez_url =
; Panelde Robotlar > Robot ekle ile alınan ad ve anahtar
robot_adi =
; Anahtarı dosyaya yazmak istemezseniz ALAMOUNT_ROBOT_ANAHTARI ortam değişkenini kullanın
robot_anahtari =
nabiz_sn = 15
; Merkez kendinden imzalı sertifika kullanıyorsa: ca_dosyasi = C:\\AlamountRPA\\merkez.crt
ca_dosyasi =
ssl_dogrula = evet
"""

TAM_CONFIG = pca_analiz.DEFAULT_CONFIG + EK_CONFIG


class Ayarlar(pca_analiz.Settings):
    """pca_analiz.Settings'in tüm bölümleri tanıyan sürümü."""

    def __init__(self, path):
        import configparser

        self.path = path
        self.base = os.path.dirname(os.path.abspath(path))
        cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";", "#"))
        cp.read_string(TAM_CONFIG)
        if os.path.exists(path):
            with open(path, encoding="utf-8-sig") as f:
                cp.read_file(f)
        self.cp = cp

    def yol(self, sec, key, olustur=False):
        p = self.get(sec, key)
        if not p:
            return ""
        p = pca_analiz.resolve(p, self.base)
        if olustur:
            os.makedirs(p, exist_ok=True)
        return p


def varsayilan_config_yolu():
    return os.path.join(pca_analiz.app_dir(), "config.ini")


def ayarlari_yukle(path=None):
    return Ayarlar(path or varsayilan_config_yolu())


def tesseract_bul(ayarlar):
    """Tesseract çalıştırılabilir dosyasını bulur; bulunamazsa None."""
    adaylar = []
    p = ayarlar.yol("OCR", "tesseract_yolu")
    if p:
        adaylar.append(p)
    w = shutil.which("tesseract")
    if w:
        adaylar.append(w)
    if sys.platform.startswith("win"):
        for k in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(k)
            if base:
                adaylar.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
                adaylar.append(os.path.join(base, "Programs", "Tesseract-OCR", "tesseract.exe"))
    for a in adaylar:
        if a and os.path.isfile(a):
            return a
    return None
