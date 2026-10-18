# -*- coding: utf-8 -*-
"""
Uçtan uca test: 1 Kontrol Merkezi + 2 robot ajanı (ortak klasör) + Teams webhook taklidi.
Kuyruk dağıtımı, iş kuralı/sistem hatası, yeniden deneme, iptal, varlık kasası, zamanlama, çevrimdışı tespiti,
roller, CSRF ve bildirimleri doğrular. Kaynak koddan (Python) çalışır; Tesseract kurulu olmalı.
Kullanım: python testler/e2e_merkez.py <rpa_klasoru> <gecici_calisma_klasoru>
"""
import http.cookiejar
import http.server
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

RPA, W = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, RPA)
import ayarlar  # noqa: E402

PORT, TEAMS_PORT = 18765, 18999
URL = f"http://127.0.0.1:{PORT}"
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
SHARED = os.path.join(W, "ortak")
for d in ("ise_giris", "output", "archive", "error"):
    os.makedirs(os.path.join(SHARED, d))
for f in os.listdir(os.path.join(RPA, "ornek_veri", "ise_giris")):
    shutil.copy(os.path.join(RPA, "ornek_veri", "ise_giris", f), os.path.join(SHARED, "ise_giris"))
# iş kuralı hatası üretecek dosya: geçerli TC ama Puantaj'da yok
shutil.copy(os.path.join(SHARED, "ise_giris", "12345678028.pdf"), os.path.join(SHARED, "ise_giris", "10000000146.pdf"))

TEST_GOREVLER = {
    "bekle_test": "*** Tasks ***\nUzun Gorev\n    Log    basladi    console=True\n    Sleep    120s\n",
    "hata_test": "*** Tasks ***\nHatali Gorev\n    Fail    bilerek hata\n",
    "varlik_test": ("*** Settings ***\nLibrary    AlamountRPA\n*** Tasks ***\nVarlik Oku\n"
                    "    ${p}=    Varlık Al    TEST_GIRIS\n    ${k}=    Varlık Al    TEST_GIRIS    kullanici_adi\n"
                    "    Should Be Equal    ${p}    Çok-Gizli-1\n    Should Be Equal    ${k}    mikro_user\n"
                    "    Log    varlik dogru    console=True\n"),
}


def kur(ad, ek):
    d = os.path.join(W, ad)
    os.makedirs(d)
    shutil.copytree(os.path.join(RPA, "gorevler"), os.path.join(d, "gorevler"))
    for g, icerik in TEST_GOREVLER.items():
        open(os.path.join(d, "gorevler", g + ".robot"), "w", encoding="utf-8").write(icerik)
    cfg = ayarlar.TAM_CONFIG
    cfg = cfg.replace("tesseract_yolu = tesseract\\tesseract.exe", "tesseract_yolu =")
    for (sec, key), val in ek.items():
        cfg = re.sub(rf"(\[{sec}\][\s\S]*?\n){key}\s*=[^\n]*", lambda m: m.group(1) + f"{key} = {val}", cfg, count=1)
    open(os.path.join(d, "config.ini"), "w", encoding="utf-8").write(cfg)
    return d


merkez_dir = kur("merkez", {("MERKEZ", "port"): PORT, ("MERKEZ", "cevrimdisi_esik_sn"): 20,
                            ("MERKEZ", "panel_url"): URL, ("MERKEZ", "sahipsiz_is_esik_sn"): 40,
                            ("BILDIRIM", "teams_webhook"): f"http://127.0.0.1:{TEAMS_PORT}/hook",
                            ("BILDIRIM", "olaylar"): "is_basarisiz, is_basarili, robot_cevrimdisi, robot_cevrimici, oge_basarisiz"})

# ---------------------------------------------------------------- Teams mock
TEAMS = []


class Hook(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        TEAMS.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


threading.Thread(target=http.server.HTTPServer(("127.0.0.1", TEAMS_PORT), Hook).serve_forever, daemon=True).start()

PY = sys.executable
BOT = os.path.join(RPA, "alamount_rpa.py")
LOGS = []


def baslat(ad, d, *args):
    f = open(os.path.join(W, f"{ad}.out"), "w")
    LOGS.append(f)
    return subprocess.Popen([PY, BOT, "--config", os.path.join(d, "config.ini"), *args], stdout=f,
                            stderr=subprocess.STDOUT, cwd=d)


sifre = subprocess.run([PY, BOT, "--config", os.path.join(merkez_dir, "config.ini"), "merkez-parola", "admin"],
                       capture_output=True, text=True, cwd=merkez_dir).stdout.strip().split(": ")[-1]
merkez = baslat("merkez", merkez_dir, "merkez")
for _ in range(60):
    try:
        urllib.request.urlopen(URL + "/api/saglik", timeout=2)
        break
    except Exception:
        time.sleep(0.5)
print("merkez ayakta")

# ---------------------------------------------------------------- panel istemcisi
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def get(yol):
    r = op.open(URL + yol)
    return r.status, r.read().decode()


def csrf():
    return re.search(r'name="csrf" value="([^"]+)"', get("/isler")[1]).group(1)


def post(yol, veri, csrf_ekle=True):
    if csrf_ekle:
        veri = dict(veri, csrf=csrf())
    r = op.open(URL + yol, urllib.parse.urlencode(veri, doseq=True).encode())
    return r.status, r.geturl(), r.read().decode()


def db(sql, p=()):
    c = sqlite3.connect(os.path.join(merkez_dir, "merkez_veri", "merkez.db"))
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, p).fetchall()]
    finally:
        c.commit()
        c.close()


def bekle(kosul, sn, aciklama):
    t = time.time()
    while time.time() - t < sn:
        if kosul():
            print(f"  ✓ {aciklama} ({time.time() - t:.0f} sn)")
            return True
        time.sleep(1)
    print(f"  ✗ ZAMAN AŞIMI: {aciklama}")
    return False


SONUC = {}

# yetkisiz erişim
SONUC["girişsiz panel → giriş sayfası"] = "/giris" in op.open(URL + "/").geturl()
try:
    post("/giris", {"ad": "admin", "sifre": "yanlis"}, False)
    SONUC["yanlış parola reddedildi"] = False
except urllib.error.HTTPError as e:
    SONUC["yanlış parola reddedildi"] = e.code == 401
post("/giris", {"ad": "admin", "sifre": sifre}, False)
SONUC["admin girişi"] = "Pano" in get("/")[1]
SONUC["panelde Alamount RPA logosu"] = "/marka/logo.png" in get("/")[1] and op.open(URL + "/marka/logo.png").status == 200
# CSRF koruması
try:
    st, url, body = post("/isler/yeni", {"surec": "pca", "csrf": "sahte"}, False)
    SONUC["CSRF koruması"] = "Güvenlik doğrulaması" in body
except urllib.error.HTTPError as e:
    SONUC["CSRF koruması"] = e.code == 403

# robotlar
anahtarlar = {}
for ad in ("ROBOT-1", "ROBOT-2"):
    body = post("/robotlar/yeni", {"ad": ad, "aciklama": "test"})[2]
    anahtarlar[ad] = re.search(r"robot_anahtari = ([\w\-]+)", body).group(1)
robot_dirs = {}
for ad in anahtarlar:
    robot_dirs[ad] = kur(ad.lower(), {
        ("AJAN", "merkez_url"): URL, ("AJAN", "robot_adi"): ad, ("AJAN", "robot_anahtari"): anahtarlar[ad],
        ("AJAN", "nabiz_sn"): 5, ("ISE_GIRIS", "giris"): os.path.join(SHARED, "ise_giris"),
        ("ISE_GIRIS", "puantaj"): os.path.join(SHARED, "ise_giris", "PUANTAJ BİLGİLERİ.xlsx"),
        ("ISE_GIRIS", "cikti"): os.path.join(SHARED, "output"),
        ("KLASORLER", "arsiv"): os.path.join(SHARED, "archive"), ("KLASORLER", "hata"): os.path.join(SHARED, "error")})
ajanlar = {ad: baslat(ad, d, "ajan") for ad, d in robot_dirs.items()}
SONUC["iki robot çevrimiçi"] = bekle(lambda: len(db("SELECT * FROM robotlar WHERE durum IN ('bosta','mesgul')")) == 2,
                                     30, "robotlar nabız gönderdi")

# varlık
post("/varliklar/kaydet", {"ad": "TEST_GIRIS", "tur": "kimlik", "kullanici_adi": "mikro_user",
                           "deger": "Çok-Gizli-1", "aciklama": "test"})
SONUC["varlık şifreli saklanıyor"] = "Çok-Gizli" not in json.dumps(db("SELECT * FROM varliklar"), ensure_ascii=False)

# 1) kuyruk: dağıt + iki robot paralel işle
post("/isler/yeni", {"surec": "ise-giris-dagit", "hedef_robot": "ROBOT-1", "max_deneme": 1})
bekle(lambda: db("SELECT COUNT(*) n FROM kuyruk_ogeleri")[0]["n"] == 3, 60, "3 PDF kuyruğa eklendi")
post("/isler/yeni", {"surec": "ise-giris-isle", "hedef_robot": "ROBOT-1"})
post("/isler/yeni", {"surec": "ise-giris-isle", "hedef_robot": "ROBOT-2"})
bekle(lambda: db("SELECT COUNT(*) n FROM kuyruk_ogeleri WHERE durum IN ('basarili','basarisiz')")[0]["n"] == 3,
      240, "kuyruk öğeleri işlendi")
og = db("SELECT referans, durum, robot, hata_turu, deneme, hata FROM kuyruk_ogeleri ORDER BY referans")
for o in og:
    print("   ", o)
SONUC["kuyruk: 2 başarılı, 1 iş kuralı hatası (yeniden denenmedi)"] = (
    [o["durum"] for o in og] == ["basarisiz", "basarili", "basarili"] and og[0]["hata_turu"] == "is" and og[0]["deneme"] == 1)
SONUC["kuyruk iki robota dağıldı"] = len({o["robot"] for o in og}) == 2
SONUC["dağıtıcı tekrar çalışınca kopya eklemiyor"] = True
post("/isler/yeni", {"surec": "ise-giris-dagit"})
time.sleep(12)
SONUC["dağıtıcı tekrar çalışınca kopya eklemiyor"] = db("SELECT COUNT(*) n FROM kuyruk_ogeleri")[0]["n"] == 3
SONUC["ortak klasörde 2 Excel"] = len([1 for r, _, fs in os.walk(os.path.join(SHARED, "output")) for f in fs
                                       if f.endswith(".xlsx")]) == 2
SONUC["işlenen PDF'ler arşivde/hata klasöründe"] = (len(os.listdir(os.path.join(SHARED, "archive", "ise_giris"))) == 2
                                                    and "10000000146.pdf" in os.listdir(os.path.join(SHARED, "error", "ise_giris")))

# 2) varlık görevi
post("/isler/yeni", {"surec": "robot:varlik_test"})
bekle(lambda: db("SELECT durum FROM isler WHERE surec='robot:varlik_test'")[0]["durum"] in ("basarili", "basarisiz"),
      60, "varlık görevi bitti")
j = db("SELECT * FROM isler WHERE surec='robot:varlik_test'")[0]
SONUC["Robot görevi varlığı kasadan okudu"] = j["durum"] == "basarili"
SONUC["Robot raporu (log.html) merkeze yüklendi"] = any("log.html" in r for r in json.loads(j["raporlar"]))
if SONUC["Robot raporu (log.html) merkeze yüklendi"]:
    ad = json.loads(j["raporlar"])[0]
    st, body = get(f"/raporlar/{j['id']}/{urllib.parse.quote(ad)}")
    SONUC["rapor panelden açılıyor"] = st == 200 and "<html" in body.lower()

# 3) yeniden deneme: hata_test, 2 hak
post("/isler/yeni", {"surec": "robot:hata_test", "max_deneme": 2})
bekle(lambda: db("SELECT durum FROM isler WHERE surec='robot:hata_test'")[0]["durum"] == "bekliyor"
      and db("SELECT deneme FROM isler WHERE surec='robot:hata_test'")[0]["deneme"] == 1, 60, "1. deneme başarısız → yeniden kuyrukta")
db("UPDATE isler SET sonraki_deneme=0 WHERE surec='robot:hata_test'")
bekle(lambda: db("SELECT durum FROM isler WHERE surec='robot:hata_test'")[0]["durum"] == "basarisiz", 60, "2. deneme → başarısız")
SONUC["yeniden deneme + son başarısızlık"] = db("SELECT deneme, durum FROM isler WHERE surec='robot:hata_test'")[0] == {"deneme": 2, "durum": "basarisiz"}

# 4) iptal
post("/isler/yeni", {"surec": "robot:bekle_test", "hedef_robot": "ROBOT-2"})
bekle(lambda: db("SELECT durum FROM isler WHERE surec='robot:bekle_test'")[0]["durum"] == "calisiyor", 60, "uzun görev başladı")
time.sleep(4)
jid = db("SELECT id FROM isler WHERE surec='robot:bekle_test'")[0]["id"]
post(f"/isler/{jid}/iptal", {})
SONUC["çalışan iş iptal edildi"] = bekle(lambda: db("SELECT durum FROM isler WHERE id=?", (jid,))[0]["durum"] == "iptal",
                                         40, "iptal robota ulaştı")

# 5) geçersiz süreç reddi (beyaz liste)
st, url, body = post("/isler/yeni", {"surec": "robot:../../etc/passwd"})
SONUC["geçersiz süreç reddedildi"] = "hata=" in url and not db("SELECT * FROM isler WHERE surec LIKE '%passwd%'")
st, url, body = post("/isler/yeni", {"surec": "robot:varlik_test", "degiskenler": "X:1\n--exitonfailure"})
SONUC["geçersiz değişken reddedildi"] = "hata=" in url

# 6) zamanlama (her dakika)
post("/zamanlamalar/yeni", {"ad": "dakikalik", "surec": "robot:varlik_test", "cron": "* * * * *", "max_deneme": 1})
SONUC["zamanlama iş üretti"] = bekle(lambda: db("SELECT COUNT(*) n FROM isler WHERE zamanlama_id IS NOT NULL")[0]["n"] >= 1,
                                     80, "zamanlama tetiklendi")
post(f"/zamanlamalar/{db('SELECT id FROM zamanlamalar')[0]['id']}/degistir", {})

# 7) robot çevrimdışı bildirimi
ajanlar["ROBOT-2"].terminate()
SONUC["çevrimdışı robot tespit edildi"] = bekle(lambda: db("SELECT durum FROM robotlar WHERE ad='ROBOT-2'")[0]["durum"] == "cevrimdisi",
                                                60, "ROBOT-2 çevrimdışı")

# 8) tüm panel sayfaları
sayfalar = ["/", "/isler", "/isler?durum=basarisiz", f"/isler/{jid}", "/kuyruklar", "/kuyruklar/ise_giris",
            "/zamanlamalar", "/robotlar", "/varliklar", "/kullanicilar", "/denetim"]
SONUC["tüm panel sayfaları 200"] = all(get(s)[0] == 200 for s in sayfalar)
# izleyici rolü
post("/kullanicilar/yeni", {"ad": "izleyen", "rol": "izleyici", "sifre": "Izleyici123"})
jar.clear()
post("/giris", {"ad": "izleyen", "sifre": "Izleyici123"}, False)
try:
    get("/varliklar")
    SONUC["izleyici varlıklara erişemiyor"] = False
except urllib.error.HTTPError as e:
    SONUC["izleyici varlıklara erişemiyor"] = e.code == 403
try:
    post("/isler/yeni", {"surec": "pca"})
    SONUC["izleyici iş başlatamıyor"] = False
except urllib.error.HTTPError as e:
    SONUC["izleyici iş başlatamıyor"] = e.code == 403
SONUC["izleyici panoyu görüyor"] = get("/")[0] == 200

time.sleep(3)
olaylar = [m["attachments"][0]["content"]["body"][1]["text"] for m in TEAMS]
SONUC["Teams kartında Alamount RPA başlığı"] = all(m["attachments"][0]["content"]["body"][0]["text"] == "ALAMOUNT RPA" for m in TEAMS)
print("Teams bildirimleri:", olaylar)
SONUC["Teams: iş başarısız"] = "İş başarısız" in olaylar
SONUC["Teams: kuyruk öğesi başarısız"] = "Kuyruk öğesi başarısız" in olaylar
SONUC["Teams: robot çevrimdışı"] = "Robot çevrimdışı" in olaylar
SONUC["Teams: iş tamamlandı"] = "İş tamamlandı" in olaylar
SONUC["denetim kaydı tutuluyor"] = len(db("SELECT * FROM denetim")) > 10

for p in list(ajanlar.values()) + [merkez]:
    p.terminate()
print("\n=========== SONUÇ ===========")
for k, v in SONUC.items():
    print(("✅" if v else "❌"), k)
print(f"{sum(SONUC.values())}/{len(SONUC)} geçti")
sys.exit(0 if all(SONUC.values()) else 1)
