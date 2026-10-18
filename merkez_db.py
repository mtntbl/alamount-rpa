# -*- coding: utf-8 -*-
"""
Kontrol Merkezi veri katmanı (SQLite, WAL).
Tablolar: kullanicilar, oturumlar, robotlar, isler, kuyruk_ogeleri, zamanlamalar, varliklar, denetim.
Tüm yazmalar tek kilit altında yapılır; iş/öğe alma işlemleri atomiktir.
"""

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time

from cryptography.fernet import Fernet, InvalidToken

from cron import Cron

SEMA = """
CREATE TABLE IF NOT EXISTS kullanicilar (
    id INTEGER PRIMARY KEY, ad TEXT UNIQUE NOT NULL, sifre_hash TEXT NOT NULL,
    rol TEXT NOT NULL DEFAULT 'izleyici', aktif INTEGER NOT NULL DEFAULT 1, olusturma REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS oturumlar (
    token TEXT PRIMARY KEY, kullanici_id INTEGER NOT NULL, csrf TEXT NOT NULL, bitis REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS robotlar (
    id INTEGER PRIMARY KEY, ad TEXT UNIQUE NOT NULL, anahtar_hash TEXT NOT NULL, aciklama TEXT DEFAULT '',
    aktif INTEGER NOT NULL DEFAULT 1, son_gorulme REAL, makine TEXT DEFAULT '', surum TEXT DEFAULT '',
    durum TEXT DEFAULT 'bilinmiyor', calisan_is INTEGER, cevrimdisi_bildirildi INTEGER DEFAULT 0, olusturma REAL
);
CREATE TABLE IF NOT EXISTS isler (
    id INTEGER PRIMARY KEY, surec TEXT NOT NULL, argumanlar TEXT DEFAULT '[]', hedef_robot TEXT DEFAULT '',
    durum TEXT NOT NULL DEFAULT 'bekliyor', oncelik INTEGER DEFAULT 5, robot TEXT DEFAULT '',
    deneme INTEGER DEFAULT 0, max_deneme INTEGER DEFAULT 1, max_sure_dk INTEGER DEFAULT 120,
    olusturan TEXT DEFAULT '', olusturma REAL NOT NULL, baslama REAL, bitis REAL, sonraki_deneme REAL,
    cikis_kodu INTEGER, ozet TEXT DEFAULT '', log TEXT DEFAULT '', raporlar TEXT DEFAULT '[]',
    iptal_istendi INTEGER DEFAULT 0, zamanlama_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_isler_durum ON isler(durum, oncelik, id);
CREATE TABLE IF NOT EXISTS kuyruk_ogeleri (
    id INTEGER PRIMARY KEY, kuyruk TEXT NOT NULL, referans TEXT NOT NULL, imza TEXT DEFAULT '',
    veri TEXT DEFAULT '{}', durum TEXT NOT NULL DEFAULT 'yeni', oncelik INTEGER DEFAULT 5,
    deneme INTEGER DEFAULT 0, max_deneme INTEGER DEFAULT 3, robot TEXT DEFAULT '', is_id INTEGER,
    olusturma REAL NOT NULL, baslama REAL, bitis REAL, sonraki_deneme REAL,
    sonuc TEXT DEFAULT '{}', hata TEXT DEFAULT '', hata_turu TEXT DEFAULT ''
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_kuyruk_ref ON kuyruk_ogeleri(kuyruk, referans, imza);
CREATE INDEX IF NOT EXISTS ix_kuyruk_durum ON kuyruk_ogeleri(kuyruk, durum, oncelik, id);
CREATE TABLE IF NOT EXISTS zamanlamalar (
    id INTEGER PRIMARY KEY, ad TEXT NOT NULL, surec TEXT NOT NULL, argumanlar TEXT DEFAULT '[]',
    cron TEXT NOT NULL, hedef_robot TEXT DEFAULT '', max_deneme INTEGER DEFAULT 1, aktif INTEGER DEFAULT 1,
    sonraki REAL, son_calisma REAL, olusturan TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS varliklar (
    id INTEGER PRIMARY KEY, ad TEXT UNIQUE NOT NULL, tur TEXT NOT NULL DEFAULT 'metin',
    kullanici_adi TEXT DEFAULT '', deger_sifreli TEXT NOT NULL, aciklama TEXT DEFAULT '', guncelleme REAL
);
CREATE TABLE IF NOT EXISTS api_anahtarlari (
    id INTEGER PRIMARY KEY, kullanici_id INTEGER NOT NULL, ad TEXT NOT NULL, anahtar_hash TEXT UNIQUE NOT NULL,
    on_ek TEXT NOT NULL, olusturma REAL NOT NULL, son_kullanim REAL, aktif INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS denetim (
    id INTEGER PRIMARY KEY, zaman REAL NOT NULL, kim TEXT, eylem TEXT, detay TEXT
);
"""

ROLLER = ("yonetici", "operator", "izleyici")
IS_SON_DURUMLAR = ("basarili", "basarisiz", "iptal")
OGE_SON_DURUMLAR = ("basarili", "basarisiz")
LOG_SINIRI = 400_000  # karakter; aşılırsa baştan kırpılır


def simdi():
    return time.time()


# --------------------------------------------------------------------------- parola
def sifre_hashle(sifre, tuz=None, tur=200_000):
    tuz = tuz or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", sifre.encode(), bytes.fromhex(tuz), tur).hex()
    return f"pbkdf2${tur}${tuz}${h}"


def sifre_dogrula(sifre, kayit):
    try:
        _, tur, tuz, h = kayit.split("$")
        return hmac.compare_digest(sifre_hashle(sifre, tuz, int(tur)).split("$")[3], h)
    except Exception:
        return False


def anahtar_hashle(anahtar):
    return hashlib.sha256(anahtar.encode()).hexdigest()


# --------------------------------------------------------------------------- kasa
class Kasa:
    """Varlık değerlerini Fernet (AES-128-CBC + HMAC) ile şifreler. Anahtar dosyası veri klasöründedir."""

    def __init__(self, anahtar_yolu):
        if not os.path.exists(anahtar_yolu):
            with open(anahtar_yolu, "wb") as f:
                f.write(Fernet.generate_key())
            try:
                os.chmod(anahtar_yolu, 0o600)
            except OSError:
                pass
        with open(anahtar_yolu, "rb") as f:
            self.f = Fernet(f.read().strip())

    def sifrele(self, metin):
        return self.f.encrypt((metin or "").encode()).decode()

    def coz(self, sifreli):
        try:
            return self.f.decrypt(sifreli.encode()).decode()
        except InvalidToken:
            raise ValueError("Varlık çözülemedi (kasa anahtarı değişmiş olabilir)")


# --------------------------------------------------------------------------- veritabanı
class Veritabani:
    def __init__(self, klasor):
        os.makedirs(klasor, exist_ok=True)
        self.klasor = klasor
        self.yol = os.path.join(klasor, "merkez.db")
        self.kilit = threading.RLock()
        self.kasa = Kasa(os.path.join(klasor, "kasa.key"))
        with self._baglan() as c:
            c.executescript(SEMA)
            sutunlar = {r[1] for r in c.execute("PRAGMA table_info(robotlar)")}
            if "oturum" not in sutunlar:  # v3.3: robotun Windows oturum durumu
                c.execute("ALTER TABLE robotlar ADD COLUMN oturum TEXT DEFAULT ''")

    def _baglan(self):
        c = sqlite3.connect(self.yol, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=30000")
        return c

    def sorgu(self, sql, params=()):
        with self._baglan() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def tek(self, sql, params=()):
        r = self.sorgu(sql, params)
        return r[0] if r else None

    def yaz(self, sql, params=()):
        with self.kilit, self._baglan() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid if cur.lastrowid else cur.rowcount

    def islem(self, fn):
        """fn(conn) tek bir IMMEDIATE işlem içinde çalışır (atomik)."""
        with self.kilit:
            c = self._baglan()
            try:
                c.execute("BEGIN IMMEDIATE")
                sonuc = fn(c)
                c.execute("COMMIT")
                return sonuc
            except Exception:
                c.execute("ROLLBACK")
                raise
            finally:
                c.close()

    # ------------------------------------------------------------------ denetim
    def denetle(self, kim, eylem, detay=""):
        self.yaz("INSERT INTO denetim(zaman, kim, eylem, detay) VALUES(?,?,?,?)",
                 (simdi(), kim, eylem, detay if isinstance(detay, str) else json.dumps(detay, ensure_ascii=False)))

    # ------------------------------------------------------------------ kullanıcılar
    def kullanici_ekle(self, ad, sifre, rol="izleyici"):
        if rol not in ROLLER:
            raise ValueError("Geçersiz rol")
        if len(sifre) < 8:
            raise ValueError("Parola en az 8 karakter olmalı")
        return self.yaz("INSERT INTO kullanicilar(ad, sifre_hash, rol, olusturma) VALUES(?,?,?,?)",
                        (ad.strip(), sifre_hashle(sifre), rol, simdi()))

    def kullanici_sifre(self, kid, sifre):
        if len(sifre) < 8:
            raise ValueError("Parola en az 8 karakter olmalı")
        self.yaz("UPDATE kullanicilar SET sifre_hash=? WHERE id=?", (sifre_hashle(sifre), kid))
        self.yaz("DELETE FROM oturumlar WHERE kullanici_id=?", (kid,))

    def giris(self, ad, sifre, sure_sa=12):
        k = self.tek("SELECT * FROM kullanicilar WHERE ad=? AND aktif=1", (ad.strip(),))
        if not k or not sifre_dogrula(sifre, k["sifre_hash"]):
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.yaz("INSERT INTO oturumlar VALUES(?,?,?,?)", (token, k["id"], csrf, simdi() + sure_sa * 3600))
        return token

    def oturum(self, token):
        if not token:
            return None
        return self.tek("""SELECT k.id, k.ad, k.rol, o.csrf FROM oturumlar o JOIN kullanicilar k ON k.id=o.kullanici_id
                           WHERE o.token=? AND o.bitis>? AND k.aktif=1""", (token, simdi()))

    def cikis(self, token):
        self.yaz("DELETE FROM oturumlar WHERE token=?", (token,))

    # ------------------------------------------------------------------ MCP / API anahtarları
    def api_anahtari_olustur(self, kullanici_id, ad):
        """Kullanıcıya bağlı MCP anahtarı üretir; anahtarın kendisi yalnızca bir kez döner."""
        anahtar = "alm_" + secrets.token_urlsafe(32)
        self.yaz("""INSERT INTO api_anahtarlari(kullanici_id, ad, anahtar_hash, on_ek, olusturma)
                    VALUES(?,?,?,?,?)""", (kullanici_id, ad.strip()[:60] or "MCP", anahtar_hashle(anahtar),
                                           anahtar[:8], simdi()))
        return anahtar

    def api_anahtari_dogrula(self, anahtar):
        """Geçerli anahtarın sahibini (id, ad, rol) döner; değilse None."""
        if not anahtar or not anahtar.startswith("alm_"):
            return None
        k = self.tek("""SELECT k.id, k.ad, k.rol, a.id anahtar_id FROM api_anahtarlari a
                        JOIN kullanicilar k ON k.id=a.kullanici_id
                        WHERE a.anahtar_hash=? AND a.aktif=1 AND k.aktif=1""", (anahtar_hashle(anahtar),))
        if k:
            self.yaz("UPDATE api_anahtarlari SET son_kullanim=? WHERE id=?", (simdi(), k["anahtar_id"]))
        return k

    def api_anahtarlari(self, kullanici_id=None):
        sql = """SELECT a.*, k.ad kullanici FROM api_anahtarlari a JOIN kullanicilar k ON k.id=a.kullanici_id
                 WHERE a.aktif=1"""
        if kullanici_id is not None:
            return self.sorgu(sql + " AND a.kullanici_id=? ORDER BY a.id DESC", (kullanici_id,))
        return self.sorgu(sql + " ORDER BY a.id DESC")

    def api_anahtari_iptal(self, anahtar_id, kullanici_id=None):
        if kullanici_id is None:
            return self.yaz("UPDATE api_anahtarlari SET aktif=0 WHERE id=?", (anahtar_id,))
        return self.yaz("UPDATE api_anahtarlari SET aktif=0 WHERE id=? AND kullanici_id=?", (anahtar_id, kullanici_id))

    # ------------------------------------------------------------------ robotlar
    def robot_ekle(self, ad, aciklama=""):
        anahtar = secrets.token_urlsafe(32)
        self.yaz("INSERT INTO robotlar(ad, anahtar_hash, aciklama, olusturma) VALUES(?,?,?,?)",
                 (ad.strip(), anahtar_hashle(anahtar), aciklama, simdi()))
        return anahtar

    def robot_anahtar_yenile(self, rid):
        anahtar = secrets.token_urlsafe(32)
        self.yaz("UPDATE robotlar SET anahtar_hash=? WHERE id=?", (anahtar_hashle(anahtar), rid))
        return anahtar

    def robot_dogrula(self, ad, anahtar):
        r = self.tek("SELECT * FROM robotlar WHERE ad=? AND aktif=1", (ad,))
        if r and hmac.compare_digest(r["anahtar_hash"], anahtar_hashle(anahtar)):
            return r
        return None

    def nabiz(self, ad, makine, surum, durum, calisan_is, oturum=None):
        self.yaz("""UPDATE robotlar SET son_gorulme=?, makine=?, surum=?, durum=?, calisan_is=?,
                    oturum=COALESCE(?, oturum) WHERE ad=?""", (simdi(), makine, surum, durum, calisan_is, oturum, ad))
        iptal = self.sorgu("SELECT id FROM isler WHERE robot=? AND durum='calisiyor' AND iptal_istendi=1", (ad,))
        return [r["id"] for r in iptal]

    # ------------------------------------------------------------------ işler
    def is_ekle(self, surec, argumanlar=(), hedef_robot="", oncelik=5, max_deneme=1, max_sure_dk=120,
                olusturan="", zamanlama_id=None):
        return self.yaz("""INSERT INTO isler(surec, argumanlar, hedef_robot, oncelik, max_deneme, max_sure_dk,
                           olusturan, olusturma, zamanlama_id) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (surec, json.dumps(list(argumanlar), ensure_ascii=False), hedef_robot or "", int(oncelik),
                         max(1, int(max_deneme)), max(1, int(max_sure_dk)), olusturan, simdi(), zamanlama_id))

    def is_al(self, robot):
        """Robota uygun, en öncelikli bekleyen işi atomik olarak 'calisiyor' yapar."""
        def fn(c):
            r = c.execute("""SELECT * FROM isler WHERE durum='bekliyor' AND (hedef_robot='' OR hedef_robot=?)
                             AND (sonraki_deneme IS NULL OR sonraki_deneme<=?)
                             ORDER BY oncelik, id LIMIT 1""", (robot, simdi())).fetchone()
            if not r:
                return None
            c.execute("""UPDATE isler SET durum='calisiyor', robot=?, baslama=?, bitis=NULL, deneme=deneme+1,
                         cikis_kodu=NULL, iptal_istendi=0 WHERE id=?""", (robot, simdi(), r["id"]))
            d = dict(r)
            d["deneme"] += 1
            return d
        return self.islem(fn)

    def is_log_ekle(self, is_id, metin):
        def fn(c):
            r = c.execute("SELECT log FROM isler WHERE id=?", (is_id,)).fetchone()
            if r is None:
                return
            log = (r["log"] or "") + metin
            if len(log) > LOG_SINIRI:
                log = "…[log kırpıldı]…\n" + log[-LOG_SINIRI:]
            c.execute("UPDATE isler SET log=? WHERE id=?", (log, is_id))
        self.islem(fn)

    def is_rapor_ekle(self, is_id, dosya):
        def fn(c):
            r = c.execute("SELECT raporlar FROM isler WHERE id=?", (is_id,)).fetchone()
            lst = json.loads(r["raporlar"] or "[]") if r else []
            if dosya not in lst:
                lst.append(dosya)
            c.execute("UPDATE isler SET raporlar=? WHERE id=?", (json.dumps(lst), is_id))
        self.islem(fn)

    def is_bitir(self, is_id, basarili, cikis_kodu=None, ozet="", iptal=False):
        """Sonucu yazar; başarısızsa ve deneme hakkı varsa işi yeniden kuyruğa alır. Son durumu döner."""
        def fn(c):
            r = c.execute("SELECT * FROM isler WHERE id=?", (is_id,)).fetchone()
            if not r or r["durum"] in IS_SON_DURUMLAR:
                return r["durum"] if r else None
            if iptal or r["iptal_istendi"]:
                durum = "iptal"
            elif basarili:
                durum = "basarili"
            elif r["deneme"] < r["max_deneme"]:
                bekle = 60 * (2 ** (r["deneme"] - 1))  # 1, 2, 4… dk
                c.execute("""UPDATE isler SET durum='bekliyor', robot='', sonraki_deneme=?, cikis_kodu=?,
                             ozet=?, log=log||? WHERE id=?""",
                          (simdi() + bekle, cikis_kodu, ozet,
                           f"\n=== Deneme {r['deneme']} başarısız; {bekle // 60} dk sonra yeniden denenecek ===\n", is_id))
                return "yeniden"
            else:
                durum = "basarisiz"
            c.execute("UPDATE isler SET durum=?, bitis=?, cikis_kodu=?, ozet=? WHERE id=?",
                      (durum, simdi(), cikis_kodu, ozet, is_id))
            return durum
        return self.islem(fn)

    def is_iptal(self, is_id):
        """Bekleyen işi hemen iptal eder; çalışan işe iptal isteği koyar (robot nabızda alır)."""
        def fn(c):
            r = c.execute("SELECT durum FROM isler WHERE id=?", (is_id,)).fetchone()
            if not r:
                return None
            if r["durum"] == "bekliyor":
                c.execute("UPDATE isler SET durum='iptal', bitis=? WHERE id=?", (simdi(), is_id))
                return "iptal"
            if r["durum"] == "calisiyor":
                c.execute("UPDATE isler SET iptal_istendi=1 WHERE id=?", (is_id,))
                return "iptal_istendi"
            return r["durum"]
        return self.islem(fn)

    def is_yeniden(self, is_id, olusturan):
        r = self.tek("SELECT * FROM isler WHERE id=?", (is_id,))
        if not r:
            return None
        return self.is_ekle(r["surec"], json.loads(r["argumanlar"]), r["hedef_robot"], r["oncelik"],
                            r["max_deneme"], r["max_sure_dk"], olusturan)

    # ------------------------------------------------------------------ kuyruk
    def oge_ekle(self, kuyruk, referans, veri=None, imza="", oncelik=5, max_deneme=3):
        """Aynı (kuyruk, referans, imza) zaten varsa eklemez ve None döner."""
        try:
            return self.yaz("""INSERT INTO kuyruk_ogeleri(kuyruk, referans, imza, veri, oncelik, max_deneme, olusturma)
                               VALUES(?,?,?,?,?,?,?)""",
                            (kuyruk, str(referans), imza or "", json.dumps(veri or {}, ensure_ascii=False),
                             int(oncelik), max(1, int(max_deneme)), simdi()))
        except sqlite3.IntegrityError:
            return None

    def oge_al(self, kuyruk, robot, is_id=None):
        def fn(c):
            r = c.execute("""SELECT * FROM kuyruk_ogeleri WHERE kuyruk=? AND durum='yeni'
                             AND (sonraki_deneme IS NULL OR sonraki_deneme<=?) ORDER BY oncelik, id LIMIT 1""",
                          (kuyruk, simdi())).fetchone()
            if not r:
                return None
            c.execute("""UPDATE kuyruk_ogeleri SET durum='isleniyor', robot=?, is_id=?, baslama=?, deneme=deneme+1
                         WHERE id=?""", (robot, is_id, simdi(), r["id"]))
            d = dict(r)
            d["deneme"] += 1
            d["veri"] = json.loads(d["veri"] or "{}")
            d["son_deneme"] = d["deneme"] >= d["max_deneme"]
            return d
        return self.islem(fn)

    def oge_bitir(self, oge_id, durum, sonuc=None, hata="", hata_turu=""):
        """durum: basarili | is_hatasi | sistem_hatasi. Sistem hatasında hak varsa yeniden 'yeni' yapar."""
        def fn(c):
            r = c.execute("SELECT * FROM kuyruk_ogeleri WHERE id=?", (oge_id,)).fetchone()
            if not r or r["durum"] != "isleniyor":
                return r["durum"] if r else None
            sonuc_js = json.dumps(sonuc or {}, ensure_ascii=False)
            if durum == "basarili":
                yeni = "basarili"
            elif durum == "sistem_hatasi" and r["deneme"] < r["max_deneme"]:
                c.execute("""UPDATE kuyruk_ogeleri SET durum='yeni', robot='', sonraki_deneme=?, hata=?, hata_turu=?
                             WHERE id=?""", (simdi() + 30 * r["deneme"], hata, "sistem", oge_id))
                return "yeniden"
            else:
                yeni = "basarisiz"
            c.execute("""UPDATE kuyruk_ogeleri SET durum=?, bitis=?, sonuc=?, hata=?, hata_turu=? WHERE id=?""",
                      (yeni, simdi(), sonuc_js, hata, hata_turu or ("is" if durum == "is_hatasi" else
                                                                     "sistem" if durum != "basarili" else ""), oge_id))
            return yeni
        return self.islem(fn)

    def oge_yeniden(self, oge_id):
        return self.yaz("""UPDATE kuyruk_ogeleri SET durum='yeni', deneme=0, sonraki_deneme=NULL, robot='', hata=''
                           WHERE id=? AND durum IN ('basarisiz','basarili')""", (oge_id,))

    def kuyruk_ozet(self):
        return self.sorgu("""SELECT kuyruk,
            SUM(durum='yeni') yeni, SUM(durum='isleniyor') isleniyor,
            SUM(durum='basarili') basarili, SUM(durum='basarisiz') basarisiz, COUNT(*) toplam
            FROM kuyruk_ogeleri GROUP BY kuyruk ORDER BY kuyruk""")

    # ------------------------------------------------------------------ zamanlamalar
    def zamanlama_ekle(self, ad, surec, cron_ifade, argumanlar=(), hedef_robot="", max_deneme=1, olusturan=""):
        sonraki = Cron(cron_ifade).sonraki().timestamp()
        return self.yaz("""INSERT INTO zamanlamalar(ad, surec, argumanlar, cron, hedef_robot, max_deneme, sonraki,
                           olusturan) VALUES(?,?,?,?,?,?,?,?)""",
                        (ad, surec, json.dumps(list(argumanlar), ensure_ascii=False), cron_ifade, hedef_robot or "",
                         max(1, int(max_deneme)), sonraki, olusturan))

    def zamanlamalari_tetikle(self):
        """Zamanı gelen zamanlamalar için iş oluşturur. Oluşan iş id'lerini döner."""
        def fn(c):
            olusan = []
            for z in c.execute("SELECT * FROM zamanlamalar WHERE aktif=1 AND sonraki<=?", (simdi(),)).fetchall():
                acik = c.execute("SELECT COUNT(*) n FROM isler WHERE zamanlama_id=? AND durum IN ('bekliyor','calisiyor')",
                                 (z["id"],)).fetchone()["n"]
                if not acik:  # önceki çalışma bitmediyse üst üste binmesin
                    cur = c.execute("""INSERT INTO isler(surec, argumanlar, hedef_robot, max_deneme, olusturan,
                                       olusturma, zamanlama_id) VALUES(?,?,?,?,?,?,?)""",
                                    (z["surec"], z["argumanlar"], z["hedef_robot"], z["max_deneme"],
                                     f"zamanlama:{z['ad']}", simdi(), z["id"]))
                    olusan.append(cur.lastrowid)
                sonraki = Cron(z["cron"]).sonraki(dt.datetime.now()).timestamp()
                c.execute("UPDATE zamanlamalar SET sonraki=?, son_calisma=? WHERE id=?", (sonraki, simdi(), z["id"]))
            return olusan
        return self.islem(fn)

    # ------------------------------------------------------------------ varlıklar
    def varlik_kaydet(self, ad, deger, tur="metin", kullanici_adi="", aciklama=""):
        if tur not in ("metin", "kimlik"):
            raise ValueError("Varlık türü metin ya da kimlik olmalı")
        sifreli = self.kasa.sifrele(deger)
        var = self.tek("SELECT id FROM varliklar WHERE ad=?", (ad,))
        if var:
            self.yaz("""UPDATE varliklar SET tur=?, kullanici_adi=?, deger_sifreli=?, aciklama=?, guncelleme=?
                        WHERE id=?""", (tur, kullanici_adi, sifreli, aciklama, simdi(), var["id"]))
            return var["id"]
        return self.yaz("""INSERT INTO varliklar(ad, tur, kullanici_adi, deger_sifreli, aciklama, guncelleme)
                           VALUES(?,?,?,?,?,?)""", (ad, tur, kullanici_adi, sifreli, aciklama, simdi()))

    def varlik_oku(self, ad):
        v = self.tek("SELECT * FROM varliklar WHERE ad=?", (ad,))
        if not v:
            return None
        return {"ad": v["ad"], "tur": v["tur"], "kullanici_adi": v["kullanici_adi"],
                "deger": self.kasa.coz(v["deger_sifreli"])}

    # ------------------------------------------------------------------ bakım
    def cevrimdisi_robotlar(self, esik_sn):
        """Eşikten uzun süredir nabız göndermeyen ve henüz bildirilmemiş robotları işaretleyip döner."""
        def fn(c):
            rows = c.execute("""SELECT * FROM robotlar WHERE aktif=1 AND son_gorulme IS NOT NULL
                                AND son_gorulme<? AND cevrimdisi_bildirildi=0""", (simdi() - esik_sn,)).fetchall()
            for r in rows:
                c.execute("UPDATE robotlar SET durum='cevrimdisi', cevrimdisi_bildirildi=1 WHERE id=?", (r["id"],))
            return [dict(r) for r in rows]
        return self.islem(fn)

    def cevrimici_oldu(self, ad):
        """Daha önce çevrimdışı bildirilmiş robot geri geldiyse True döner."""
        def fn(c):
            r = c.execute("SELECT cevrimdisi_bildirildi FROM robotlar WHERE ad=?", (ad,)).fetchone()
            if r and r["cevrimdisi_bildirildi"]:
                c.execute("UPDATE robotlar SET cevrimdisi_bildirildi=0 WHERE ad=?", (ad,))
                return True
            return False
        return self.islem(fn)

    def sahipsiz_isler(self, esik_sn):
        """Robotu uzun süredir sessiz olan 'calisiyor' işleri döner."""
        return self.sorgu("""SELECT i.* FROM isler i LEFT JOIN robotlar r ON r.ad=i.robot
                             WHERE i.durum='calisiyor' AND (r.son_gorulme IS NULL OR r.son_gorulme<?)""",
                          (simdi() - esik_sn,))

    def sahipsiz_ogeler(self, esik_sn):
        """İşlenirken robotu kaybolan kuyruk öğelerini yeniden 'yeni' yapar."""
        return self.yaz("""UPDATE kuyruk_ogeleri SET durum='yeni', robot='', hata='Robot bağlantısı koptu'
                           WHERE durum='isleniyor' AND robot IN
                           (SELECT ad FROM robotlar WHERE son_gorulme<?)""", (simdi() - esik_sn,))

    def temizle(self, gun):
        sinir = simdi() - gun * 86400
        self.yaz("DELETE FROM isler WHERE bitis IS NOT NULL AND bitis<?", (sinir,))
        self.yaz("DELETE FROM kuyruk_ogeleri WHERE bitis IS NOT NULL AND bitis<?", (sinir,))
        self.yaz("DELETE FROM denetim WHERE zaman<?", (sinir,))
        self.yaz("DELETE FROM oturumlar WHERE bitis<?", (simdi(),))
