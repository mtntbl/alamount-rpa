# -*- coding: utf-8 -*-
"""
Belge → görsel → OCR katmanı
  * pymupdf : PDF sayfalarını metin katmanı + görsel olarak alır
  * opencv  : kimlik kartını bulup perspektif düzeltmeli kırpar, OCR öncesi iyileştirme
  * pytesseract + Tesseract : yerel (internetsiz) Türkçe OCR
  * re      : belge türü tespiti ve alan çıkarımı
"""

import logging
import os
import re
import unicodedata

import cv2
import pymupdf as fitz
import numpy as np
import pytesseract
from PIL import Image

from ayarlar import tesseract_bul

log = logging.getLogger("alamount")

KIMLIK_ORAN = 85.6 / 54.0  # ISO/IEC 7810 ID-1


# --------------------------------------------------------------------------- yardımcılar
def tr_upper(s):
    return (s or "").replace("i", "İ").replace("ı", "I").upper()


def sadelestir(s):
    """Türkçe karakterleri ASCII'ye indirip büyük harfe çevirir (anahtar kelime eşleştirme için)."""
    s = tr_upper(s)
    s = s.translate(str.maketrans("ÇĞİÖŞÜÂÎÛ", "CGIOSUAIU"))
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", s)


def tc_gecerli_mi(tc):
    """T.C. Kimlik No algoritma kontrolü."""
    if not re.fullmatch(r"[1-9]\d{10}", tc or ""):
        return False
    d = [int(c) for c in tc]
    if ((sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10) != d[9]:
        return False
    return sum(d[:10]) % 10 == d[10]


def tc_maskele(tc):
    return f"{tc[:3]}******{tc[-2:]}" if tc and len(tc) == 11 else tc


def tc_bul(metin):
    """Metindeki geçerli tüm TC numaraları (sırayla, tekrarsız)."""
    gorulen = []
    for m in re.finditer(r"(?<!\d)([1-9]\d{10})(?!\d)", re.sub(r"(?<=\d) (?=\d)", "", metin or "")):
        if tc_gecerli_mi(m.group(1)) and m.group(1) not in gorulen:
            gorulen.append(m.group(1))
    return gorulen


# --------------------------------------------------------------------------- OCR motoru
class OcrMotoru:
    def __init__(self, ayarlar):
        # Tesseract OpenMP ile tüm çekirdekleri kullanır; aynı anda birden fazla OCR (çok robot, çok iş)
        # çalışınca çekirdekler boğulur ve süre 10 katına çıkar. Tek iş parçacığı bu görsellerde daha hızlıdır.
        os.environ.setdefault("OMP_THREAD_LIMIT", "1")
        self.ayarlar = ayarlar
        self.dil = ayarlar.get("OCR", "dil") or "tur"
        self.dpi = ayarlar.getint("OCR", "dpi")
        self.on_isleme = ayarlar.getbool("OCR", "on_isleme")
        self.cmd = tesseract_bul(ayarlar)
        if self.cmd:
            pytesseract.pytesseract.tesseract_cmd = self.cmd
            log.debug("Tesseract: %s", self.cmd)
        else:
            log.warning("Tesseract bulunamadı; taranmış sayfalar okunamayacak. [OCR] tesseract_yolu ayarını kontrol edin.")

    @property
    def hazir(self):
        return self.cmd is not None

    def diller(self):
        try:
            return set(pytesseract.get_languages(config=""))
        except Exception:
            return set()

    def iyilestir(self, img):
        """Gri ton + gürültü azaltma + Otsu eşikleme + eğim düzeltme."""
        a = np.array(img.convert("RGB"))
        gri = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
        if min(gri.shape) < 1000:  # küçük görselleri büyüt
            k = 1000 / min(gri.shape)
            gri = cv2.resize(gri, None, fx=k, fy=k, interpolation=cv2.INTER_CUBIC)
        gri = cv2.fastNlMeansDenoising(gri, h=10)
        _, bw = cv2.threshold(gri, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        bw = egim_duzelt(bw)
        return Image.fromarray(bw)

    def oku(self, img, psm=None):
        if not self.hazir:
            return ""
        psm = psm or self.ayarlar.getint("OCR", "psm_belge")
        if self.on_isleme:
            img = self.iyilestir(img)
        cfg = f"--oem 1 --psm {psm} --dpi {self.dpi}"
        return pytesseract.image_to_string(img, lang=self.dil, config=cfg)


def egim_duzelt(bw):
    """Metin bloğunun eğimini minAreaRect ile bulup düzeltir (±15° içinde)."""
    ters = cv2.bitwise_not(bw)
    pts = cv2.findNonZero(ters)
    if pts is None or len(pts) < 50:
        return bw
    aci = cv2.minAreaRect(pts)[-1]
    if aci > 45:
        aci -= 90
    if abs(aci) < 0.3 or abs(aci) > 15:
        return bw
    h, w = bw.shape
    M = cv2.getRotationMatrix2D((w // 2, h // 2), aci, 1.0)
    return cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


# --------------------------------------------------------------------------- PDF
def pdf_sayfalari(pdf_yolu, dpi=300):
    """[(sayfa_no, metin_katmani, PIL.Image)] döner."""
    sonuc = []
    with fitz.open(pdf_yolu) as doc:
        for i, page in enumerate(doc, start=1):
            metin = page.get_text("text") or ""
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            sonuc.append((i, metin, img))
    return sonuc


# --------------------------------------------------------------------------- kimlik kartı kırpma
def _siralanmis_koseler(pts):
    pts = pts.reshape(4, 2).astype("float32")
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype="float32")


def kimlik_karti_kirp(img, min_alan_orani=0.03):
    """
    Görseldeki kimlik kartı boyutundaki (≈1.585 en/boy) dörtgenleri bulur ve
    perspektif düzeltmeli kırpılmış PIL görselleri döner (büyükten küçüğe, en fazla 2: ön/arka).
    """
    a = np.array(img.convert("RGB"))
    H, W = a.shape[:2]
    gri = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    gri = cv2.GaussianBlur(gri, (5, 5), 0)
    kenar = cv2.Canny(gri, 30, 120)
    kenar = cv2.dilate(kenar, np.ones((5, 5), np.uint8), iterations=2)
    konturlar, _ = cv2.findContours(kenar, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    adaylar = []
    for c in konturlar:
        alan = cv2.contourArea(c)
        if alan < min_alan_orani * W * H or alan > 0.98 * W * H:
            continue
        rect = cv2.minAreaRect(c)
        (rw, rh) = rect[1]
        if min(rw, rh) == 0:
            continue
        oran = max(rw, rh) / min(rw, rh)
        if abs(oran - KIMLIK_ORAN) > 0.25:
            continue
        if alan / (rw * rh) < 0.8:  # dikdörtgene yeterince benzemiyor
            continue
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        kose = approx if len(approx) == 4 else cv2.boxPoints(rect).astype("int32")
        adaylar.append((alan, _siralanmis_koseler(kose)))

    adaylar.sort(key=lambda x: -x[0])
    sonuc = []
    for _, k in adaylar[:2]:
        gen = int(max(np.linalg.norm(k[0] - k[1]), np.linalg.norm(k[3] - k[2])))
        yuk = int(max(np.linalg.norm(k[0] - k[3]), np.linalg.norm(k[1] - k[2])))
        dst = np.array([[0, 0], [gen - 1, 0], [gen - 1, yuk - 1], [0, yuk - 1]], dtype="float32")
        M = cv2.getPerspectiveTransform(k, dst)
        kart = cv2.warpPerspective(a, M, (gen, yuk))
        if yuk > gen:  # dikey taranmışsa yatay çevir
            kart = cv2.rotate(kart, cv2.ROTATE_90_CLOCKWISE)
        sonuc.append(Image.fromarray(kart))
    return sonuc


# --------------------------------------------------------------------------- belge türü
BELGE_TURLERI = [
    ("kimlik", ["KIMLIK KARTI", "IDENTITY CARD", "IDENTITY CARD", "SERI NO", "DOCUMENT NO", "GECERLILIK"]),
    ("nufus_kayit", ["NUFUS KAYIT ORNEGI", "VUKUATLI", "AILE SIRA", "BIREY SIRA", "CILT"]),
    ("yerlesim", ["YERLESIM YERI", "ADRES BILGILERI", "IKAMETGAH", "YERLESIM YERI VE DIGER ADRES"]),
    ("adli_sicil", ["ADLI SICIL", "ARSIV KAYDI", "SABIKA"]),
    ("diploma", ["DIPLOMA", "MEZUN", "OGRENIM BELGESI", "MEZUNIYET", "E-MEZUN"]),
    ("sertifika", ["SERTIFIKA", "MESLEKI YETERLILIK", "USTALIK", "KALFALIK", "KURS BITIRME", "MYK"]),
]

BELGE_ADLARI = {
    "kimlik": "T.C. Kimlik Kartı",
    "nufus_kayit": "Nüfus Kayıt Örneği",
    "yerlesim": "Yerleşim Yeri Belgesi",
    "adli_sicil": "Adli Sicil Kaydı",
    "diploma": "Diploma / Mezuniyet",
    "sertifika": "Sertifika",
    "diger": "Diğer",
}


def belge_turu(metin):
    s = sadelestir(metin)
    puan = {t: sum(s.count(k) for k in kel) for t, kel in BELGE_TURLERI}
    en = max(puan, key=puan.get)
    return en if puan[en] > 0 else "diger"


# --------------------------------------------------------------------------- alan çıkarımı
TARIH = r"(\d{2})[./\-\s](\d{2})[./\-\s](\d{4})"


def _tarih(m):
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else None


def _etiket(metin, *etiketler, deger=r"([^\n:]{1,80})"):
    """'Etiket : Değer' ya da 'Etiket\\nDeğer' biçimindeki alanı yakalar (Türkçe karakter duyarsız)."""
    # Değer '/' ile başlıyorsa iki dilli etiketin devamıdır (ör. 'Uyruğu / Nationality'), değer sayılmaz.
    deger = r"(?![\s/{(])" + deger
    for e in etiketler:
        desen = r"(?im)^[ \t]*" + _esnek(e) + r"[ \t]*[:;]?[ \t]*" + deger
        m = re.search(desen, metin)
        if m and m.group(1).strip():
            return temizle(m.group(1))
        # Kimlik kartı düzeni: etiket (+ İngilizce karşılığı) bir satırda, değer sonraki dolu satırda
        desen2 = r"(?im)^[ \t]*" + _esnek(e) + r"[ \t]*(?:[/{(][^\n]*)?[:;]?[ \t]*\n\s*" + deger
        m = re.search(desen2, metin)
        if m and m.group(1).strip():
            return temizle(m.group(1))
    return None


def _esnek(etiket):
    """Etiketteki Türkçe harfleri OCR hatalarına toleranslı sınıflara çevirir."""
    esler = {
        "i": "[iİıIl1]", "ı": "[iİıIl1]", "I": "[iİıIl1]", "İ": "[iİıIl1]",
        "s": "[sşSŞ]", "ş": "[sşSŞ]", "S": "[sşSŞ]", "Ş": "[sşSŞ]",
        "c": "[cçCÇ]", "ç": "[cçCÇ]", "C": "[cçCÇ]", "Ç": "[cçCÇ]",
        "g": "[gğGĞ]", "ğ": "[gğGĞ]", "G": "[gğGĞ]", "Ğ": "[gğGĞ]",
        "o": "[oöOÖ0]", "ö": "[oöOÖ0]", "O": "[oöOÖ0]", "Ö": "[oöOÖ0]",
        "u": "[uüUÜ]", "ü": "[uüUÜ]", "U": "[uüUÜ]", "Ü": "[uüUÜ]",
        " ": r"\s*", ".": r"\.?", "/": r"\s*/\s*",
    }
    out = ""
    for ch in etiket:
        if ch in esler:
            out += esler[ch]
        elif ch.isalpha():
            out += f"[{ch.lower()}{ch.upper()}]"
        else:
            out += re.escape(ch)
    return out


def temizle(s):
    s = re.sub(r"\s+", " ", s or "").strip(" .:;,-_|")
    return s or None


def cinsiyet_normalize(v):
    s = sadelestir(v or "")
    if re.search(r"\b(E|M|ERKEK|MALE)\b", s):
        return "Erkek"
    if re.search(r"\b(K|F|KADIN|FEMALE)\b", s):
        return "Kadın"
    return None


def kimlik_alanlari(metin):
    a = {}
    a["seri_no"] = None
    m = re.search(r"\b([A-Z]\d{2}[A-Z]\d{5})\b", metin.replace(" ", ""))
    if m:
        a["seri_no"] = m.group(1)
    else:
        a["seri_no"] = _etiket(metin, "Seri No", "Document No", deger=r"([A-Z0-9 ]{6,12})")
    a["soyadi"] = _etiket(metin, "Soyadı / Surname", "Soyadı", "Surname")
    a["adi"] = _etiket(metin, "Adı / Given Name(s)", "Adı", "Given Name(s)", "Given Names")
    a["dogum_tarihi"] = _tarih(re.search(r"(?i)do[gğ]um\s*tarih[iı].{0,40}?" + TARIH, metin, re.S)) or None
    a["cinsiyet"] = cinsiyet_normalize(_etiket(metin, "Cinsiyeti / Gender", "Cinsiyeti", "Cinsiyet", "Gender",
                                               deger=r"([A-Za-zÇĞİÖŞÜçğıöşü/ ]{1,15})"))
    uyruk = _etiket(metin, "Uyruğu / Nationality", "Uyruğu", "Nationality")
    a["uyruk"] = "T.C." if uyruk and re.search(r"T\.?\s*C|TUR", sadelestir(uyruk)) else uyruk
    a["gecerlilik"] = _tarih(re.search(r"(?i)(?:ge[cç]erl[iı]l[iı]k|valid\s*until).{0,40}?" + TARIH, metin, re.S))
    a["veren_makam"] = _etiket(metin, "Veren Makam", "Verildiği Nüfus İdaresi", "Issued By")
    a["anne_adi"] = _etiket(metin, "Anne Adı", "Mother's Name")
    a["baba_adi"] = _etiket(metin, "Baba Adı", "Father's Name")
    return a


def nufus_kayit_alanlari(metin):
    a = {
        "il": _etiket(metin, "İl", "Nüfusa Kayıtlı Olduğu İl"),
        "ilce": _etiket(metin, "İlçe", "Nüfusa Kayıtlı Olduğu İlçe"),
        "mahalle": _etiket(metin, "Mahalle/Köy", "Mahalle", "Mahalle / Köy"),
        "koy": _etiket(metin, "Köy"),
        "cilt_no": _etiket(metin, "Cilt No", "Cilt", deger=r"(\d{1,6})"),
        "aile_sira_no": _etiket(metin, "Aile Sıra No", "Hane No", deger=r"(\d{1,6})"),
        "sira_no": _etiket(metin, "Birey Sıra No", "BSN", "Sıra No", deger=r"(\d{1,6})"),
        "medeni_hal": None,
        "din": _etiket(metin, "Dini", "Din"),
        "dogum_yeri": _etiket(metin, "Doğum Yeri", "Doğum Yeri ve Tarihi", deger=r"([A-Za-zÇĞİÖŞÜçğıöşü/ ]{2,40})"),
        "dogum_tarihi": _tarih(re.search(r"(?i)do[gğ]um\s*(?:yeri\s*ve\s*)?tarih[iı].{0,60}?" + TARIH, metin, re.S)),
        "cinsiyet": cinsiyet_normalize(_etiket(metin, "Cinsiyeti", "Cinsiyet", deger=r"([A-Za-zÇĞİÖŞÜçğıöşü]{1,8})")),
        "ilk_soyad": _etiket(metin, "Önceki Soyadı", "Kızlık Soyadı", "İlk Soyadı"),
    }
    mh = _etiket(metin, "Medeni Hali", "Medeni Hal", "Medeni Durumu")
    if mh:
        s = sadelestir(mh)
        for k, v in (("BEKAR", "Bekar"), ("EVLI", "Evli"), ("DUL", "Dul"), ("BOSAN", "Boşanmış")):
            if k in s:
                mh = v
                break
    a["medeni_hal"] = mh
    return a


ADRES_PARCALARI = [
    ("mahalle", r"([\wÇĞİÖŞÜçğıöşü\.\s]{2,40}?)\s+MAH(?:ALLES[İI])?\.?"),
    ("cadde", r"([\wÇĞİÖŞÜçğıöşü\.\s]{2,40}?)\s+CAD(?:DES[İI])?\.?"),
    ("sokak", r"([\wÇĞİÖŞÜçğıöşü\.\s]{1,40}?)\s+(?:SK|SOK|SOKA[GĞ]I|SOKAK)\.?"),
    ("bina_no", r"(?:D[İI][ŞS]\s*KAPI\s*NO|B[İI]NA\s*NO|NO)\s*[:.]?\s*([0-9]+[A-Z]?)"),
    ("daire_no", r"(?:[İI][ÇC]\s*KAPI\s*NO|DA[İI]RE(?:\s*NO)?)\s*[:.]?\s*([0-9]+[A-Z]?)"),
]


def adres_coz(adres):
    """'X MAH. Y CAD. Z SK. NO: 5 İÇ KAPI NO: 3 İLÇE / İL' → parçalar."""
    a = {k: None for k, _ in ADRES_PARCALARI}
    if not adres:
        return a
    u = tr_upper(adres)
    for k, desen in ADRES_PARCALARI:
        m = re.search(desen, u)
        if m:
            deger = temizle(m.group(1))
            if k in ("mahalle", "cadde", "sokak") and deger:
                deger = re.split(r"\b(?:MAH|CAD|SK|SOK|NO)\b\.?", deger)[-1].strip() or deger
            a[k] = deger
    m = re.search(r"([A-ZÇĞİÖŞÜ]{2,})\s*/\s*([A-ZÇĞİÖŞÜ]{2,})\s*$", u.strip())
    if m:
        a["ilce"], a["il"] = m.group(1), m.group(2)
    a["ulke"] = "TÜRKİYE"
    return a


def yerlesim_alanlari(metin):
    adres = None
    m = re.search(r"(?is)(?:yerle[sş]im\s*yeri\s*)?adres[iı]?\s*[:;]\s*(.+?)(?:\n\s*\n|beyan|adres\s*no|$)", metin)
    if m:
        adres = temizle(m.group(1))
    a = adres_coz(adres)
    a["tam_adres"] = adres
    return a


def diploma_alanlari(metin):
    s = sadelestir(metin)
    for k, v in (("DOKTORA", "Doktora"), ("YUKSEK LISANS", "Yüksek Lisans"), ("LISANS", "Lisans"),
                 ("ON LISANS", "Ön Lisans"), ("MESLEK YUKSEKOKULU", "Ön Lisans"), ("LISE", "Lise"),
                 ("ORTAOKUL", "Ortaokul"), ("ILKOGRETIM", "İlköğretim"), ("ILKOKUL", "İlkokul")):
        if k in s:
            return {"tahsil": v}
    return {"tahsil": None}


def sertifika_alanlari(metin):
    m = re.search(r"(?im)(?:meslek|yeterlilik|sertifika\s*ad[iı]|alan[iı])\s*[:;]\s*(.+)$", metin)
    return {"sertifika_meslek": temizle(m.group(1)) if m else None}


CIKARICILAR = {
    "kimlik": kimlik_alanlari,
    "nufus_kayit": nufus_kayit_alanlari,
    "yerlesim": yerlesim_alanlari,
    "diploma": diploma_alanlari,
    "sertifika": sertifika_alanlari,
}


# --------------------------------------------------------------------------- tüm PDF
def pdf_coz(pdf_yolu, ayarlar, ara_klasor=None):
    """
    Personel PDF'ini sayfa sayfa işler. Döner:
      {"sayfalar": [{no, tur, kaynak(metin|ocr), metin, kimlik_gorselleri:[yol]}],
       "belgeler": {tur: {alan: değer}}, "tc_listesi": [...]}
    """
    motor = OcrMotoru(ayarlar)
    min_kar = ayarlar.getint("OCR", "min_metin_karakter")
    kaydet = ara_klasor and ayarlar.getbool("OCR", "ara_gorselleri_kaydet")
    if kaydet:
        os.makedirs(ara_klasor, exist_ok=True)

    sonuc = {"sayfalar": [], "belgeler": {}, "tc_listesi": [], "kimlik_gorselleri": []}
    for no, metin, img in pdf_sayfalari(pdf_yolu, ayarlar.getint("OCR", "dpi")):
        kaynak = "metin"
        kartlar = kimlik_karti_kirp(img)
        if len(metin.strip()) < min_kar:
            kaynak = "ocr"
            metin = motor.oku(img)
        kart_metni = ""
        kart_yollari = []
        for j, kart in enumerate(kartlar, start=1):
            if kaydet:
                p = os.path.join(ara_klasor, f"sayfa{no:02d}_kimlik{j}.png")
                kart.save(p)
                kart_yollari.append(p)
            if kaynak == "ocr" or belge_turu(metin) in ("kimlik", "diger"):
                kart_metni += "\n" + motor.oku(kart, psm=ayarlar.getint("OCR", "psm_kimlik"))
        if kaydet:
            img.save(os.path.join(ara_klasor, f"sayfa{no:02d}.png"))
        tum = metin + "\n" + kart_metni
        tur = belge_turu(tum)
        if kartlar and tur == "diger":
            tur = "kimlik"
        sonuc["sayfalar"].append({"no": no, "tur": tur, "kaynak": kaynak, "metin": tum,
                                  "kimlik_gorselleri": kart_yollari, "kart_sayisi": len(kartlar)})
        if tur == "kimlik":
            sonuc["kimlik_gorselleri"] += kart_yollari or ([] if not kaydet else [])
        for tc in tc_bul(tum):
            if tc not in sonuc["tc_listesi"]:
                sonuc["tc_listesi"].append(tc)
        if tur in CIKARICILAR:
            alanlar = CIKARICILAR[tur](tum)
            hedef = sonuc["belgeler"].setdefault(tur, {})
            for k, v in alanlar.items():
                if v and not hedef.get(k):
                    hedef[k] = v
        log.info("Sayfa %d: %s (%s%s)", no, BELGE_ADLARI.get(tur, tur), kaynak,
                 f", {len(kartlar)} kart kırpıldı" if kartlar else "")
    return sonuc


def pdf_metne_cevir(pdf_yolu, ayarlar, cikti_txt=None):
    """Taranmış/normal PDF'i düz metne çevirir (OCR gerekirse)."""
    motor = OcrMotoru(ayarlar)
    min_kar = ayarlar.getint("OCR", "min_metin_karakter")
    parcalar = []
    for no, metin, img in pdf_sayfalari(pdf_yolu, ayarlar.getint("OCR", "dpi")):
        if len(metin.strip()) < min_kar:
            metin = motor.oku(img)
        parcalar.append(f"===== Sayfa {no} =====\n{metin.strip()}\n")
    txt = "\n".join(parcalar)
    if cikti_txt:
        with open(cikti_txt, "w", encoding="utf-8") as f:
            f.write(txt)
    return txt
