# -*- coding: utf-8 -*-
"""
Alamount RPA Kontrol Merkezi — tek makinede çalışır, robotlar (ajanlar) buradan iş alır.
  AlamountRPA.exe merkez

  * Web paneli (rol bazlı): pano, işler, kuyruklar, zamanlamalar, robotlar, varlıklar, kullanıcılar, denetim
  * Robot API'si (/api/...): nabız, iş alma, log/rapor yükleme, kuyruk, varlık
  * Arka plan: zamanlamalar, çevrimdışı robot tespiti, sahipsiz iş kurtarma, eski kayıt temizliği
  * Bildirimler: e-posta + Microsoft Teams
"""

import asyncio
import datetime as dt
import json
import logging
import os
import re
import secrets
import socket
import threading
import time
import urllib.parse

from starlette.applications import Starlette
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

import ayarlar as ay
import marka
import merkez_panel as P
import pca_analiz
import surecler
from bildirim import Bildirici
from cron import Cron, gecerli_mi
from merkez_db import ROLLER, Veritabani

log = logging.getLogger("alamount")
COOKIE = "alamount_oturum"
AD_DESENI = re.compile(r"^[A-Za-z0-9_\-.ÇĞİÖŞÜçğıöşü]{1,60}$")
MAX_RAPOR = 50 * 1024 * 1024


class GuvenlikBasliklari:
    """Tüm yanıtlara güvenlik başlıkları ekleyen ASGI ara katmanı."""

    BASLIKLAR = [(b"x-frame-options", b"DENY"), (b"x-content-type-options", b"nosniff"),
                 (b"referrer-policy", b"same-origin")]

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def gonder(mesaj):
            if mesaj["type"] == "http.response.start":
                mevcut = {k.lower() for k, _ in mesaj.get("headers", [])}
                mesaj["headers"] = list(mesaj.get("headers", [])) + [h for h in self.BASLIKLAR if h[0] not in mevcut]
            await send(mesaj)

        await self.app(scope, receive, gonder)


class Merkez:
    def __init__(self, ayarlar):
        self.ayarlar = ayarlar
        self.db = Veritabani(ayarlar.yol("MERKEZ", "veri_klasoru", olustur=True))
        self.rapor_klasoru = os.path.join(self.db.klasor, "raporlar")
        os.makedirs(self.rapor_klasoru, exist_ok=True)
        self.gorev_klasoru = ayarlar.yol("ROBOT", "gorev_klasoru")
        self.bildirici = Bildirici(ayarlar)
        self.panel_url = (ayarlar.get("MERKEZ", "panel_url") or "").rstrip("/")
        self.https = bool(ayarlar.get("MERKEZ", "ssl_sertifika"))
        self._dur = threading.Event()
        pca_analiz.VARLIK_COZUCU = self._varlik_coz  # config.ini'deki 'varlik:AD' değerleri için

    def _varlik_coz(self, ad, alan):
        v = self.db.varlik_oku(ad)
        if not v:
            raise KeyError(f"Varlık bulunamadı: {ad}")
        return v["kullanici_adi"] if alan == "kullanici" else v["deger"]

    def link(self, yol):
        return f"{self.panel_url}{yol}" if self.panel_url else ""

    # ================================================================== yardımcılar
    def ilk_yonetici(self):
        if self.db.tek("SELECT id FROM kullanicilar LIMIT 1"):
            return None
        sifre = secrets.token_urlsafe(12)
        self.db.kullanici_ekle("admin", sifre, "yonetici")
        yol = os.path.join(self.db.klasor, "ilk_yonetici_parolasi.txt")
        with open(yol, "w", encoding="utf-8") as f:
            f.write(f"Kullanıcı: admin\nParola: {sifre}\nİlk girişten sonra parolayı değiştirin ve bu dosyayı silin.\n")
        return sifre

    def oturum(self, request):
        return self.db.oturum(request.cookies.get(COOKIE))

    async def form(self, request, kullanici):
        f = await request.form()
        if not secrets.compare_digest(str(f.get("csrf", "")), kullanici["csrf"]):
            raise PermissionError("Güvenlik doğrulaması başarısız (sayfayı yenileyip tekrar deneyin)")
        return f

    def yonlendir(self, url, mesaj=None, tur="basari"):
        if mesaj:
            sep = "&" if "?" in url else "?"
            url += f"{sep}{tur}=" + urllib.parse.quote(mesaj)
        return RedirectResponse(url, status_code=303)

    @staticmethod
    def mesaj(request):
        for tur in ("basari", "hata", "uyari"):
            if request.query_params.get(tur):
                return tur, request.query_params[tur]
        return None

    def robot_dogrula(self, request):
        h = request.headers.get("authorization", "")
        if not h.startswith("Bearer ") or ":" not in h[7:]:
            return None
        ad, anahtar = h[7:].split(":", 1)
        return self.db.robot_dogrula(ad, anahtar)

    # ================================================================== robot API
    def api(self, fn):
        async def sar(request):
            robot = self.robot_dogrula(request)
            if not robot:
                return JSONResponse({"hata": "Yetkisiz robot"}, status_code=401)
            try:
                return await fn(request, robot)
            except (ValueError, KeyError) as ex:
                return JSONResponse({"hata": str(ex)}, status_code=400)
            except Exception as ex:
                log.exception("API hatası")
                return JSONResponse({"hata": f"Sunucu hatası: {ex}"}, status_code=500)
        return sar

    async def api_nabiz(self, request, robot):
        d = await request.json()
        iptal = self.db.nabiz(robot["ad"], str(d.get("makine", ""))[:100], str(d.get("surum", ""))[:30],
                              "mesgul" if d.get("calisan_is") else "bosta", d.get("calisan_is"),
                              str(d.get("oturum") or "")[:20])
        if self.db.cevrimici_oldu(robot["ad"]):
            self.bildirici.gonder("robot_cevrimici", f"{robot['ad']} yeniden bağlandı",
                                  {"Robot": robot["ad"], "Makine": d.get("makine", "")}, self.link("/robotlar"))
        return JSONResponse({"iptal": iptal, "sunucu_zamani": time.time()})

    async def api_is_al(self, request, robot):
        j = self.db.is_al(robot["ad"])
        if not j:
            return Response(status_code=204)
        self.db.nabiz(robot["ad"], robot["makine"], robot["surum"], "mesgul", j["id"])
        log.info("İş #%s → %s (%s)", j["id"], robot["ad"], j["surec"])
        return JSONResponse({"id": j["id"], "surec": j["surec"], "argumanlar": json.loads(j["argumanlar"]),
                             "max_sure_dk": j["max_sure_dk"], "deneme": j["deneme"]})

    def _isi_dogrula(self, is_id, robot):
        j = self.db.tek("SELECT * FROM isler WHERE id=?", (is_id,))
        if not j or j["robot"] != robot["ad"]:
            raise ValueError("Bu iş bu robota ait değil")
        return j

    async def api_is_log(self, request, robot):
        is_id = request.path_params["id"]
        self._isi_dogrula(is_id, robot)
        metin = (await request.body()).decode("utf-8", "replace")
        if metin:
            self.db.is_log_ekle(is_id, metin)
        return JSONResponse({"ok": True})

    async def api_is_rapor(self, request, robot):
        is_id = request.path_params["id"]
        self._isi_dogrula(is_id, robot)
        ad = os.path.basename(request.query_params.get("ad", "rapor.html"))
        if not re.match(r"^[\w\-. ]{1,100}$", ad) or not ad.lower().endswith((".html", ".xml", ".txt", ".png", ".log")):
            raise ValueError("Geçersiz rapor adı")
        govde = await request.body()
        if len(govde) > MAX_RAPOR:
            raise ValueError("Rapor çok büyük")
        klasor = os.path.join(self.rapor_klasoru, str(is_id))
        os.makedirs(klasor, exist_ok=True)
        with open(os.path.join(klasor, ad), "wb") as f:
            f.write(govde)
        self.db.is_rapor_ekle(is_id, ad)
        return JSONResponse({"ok": True})

    async def api_is_bitir(self, request, robot):
        is_id = request.path_params["id"]
        j = self._isi_dogrula(is_id, robot)
        d = await request.json()
        sonuc = self.db.is_bitir(is_id, bool(d.get("basarili")), d.get("cikis_kodu"), str(d.get("ozet", ""))[:2000],
                                 iptal=bool(d.get("iptal")))
        self.db.nabiz(robot["ad"], robot["makine"], robot["surum"], "bosta", None)
        log.info("İş #%s bitti: %s (%s)", is_id, sonuc, robot["ad"])
        alanlar = {"İş": f"#{is_id}", "Süreç": j["surec"], "Robot": robot["ad"], "Deneme": j["deneme"],
                   "Özet": d.get("ozet", "") or "-"}
        if sonuc == "basarisiz":
            self.bildirici.gonder("is_basarisiz", f"#{is_id} {j['surec']} başarısız", alanlar, self.link(f"/isler/{is_id}"))
        elif sonuc == "basarili":
            self.bildirici.gonder("is_basarili", f"#{is_id} {j['surec']} tamamlandı", alanlar, self.link(f"/isler/{is_id}"))
        return JSONResponse({"durum": sonuc})

    async def api_kuyruk_ekle(self, request, robot):
        d = await request.json()
        kuyruk = request.path_params["ad"]
        if not AD_DESENI.match(kuyruk):
            raise ValueError("Geçersiz kuyruk adı")
        oid = self.db.oge_ekle(kuyruk, str(d["referans"])[:200], d.get("veri") or {}, str(d.get("imza", ""))[:200],
                               int(d.get("oncelik", 5)), int(d.get("max_deneme", 3)))
        return JSONResponse({"id": oid, "eklendi": oid is not None})

    async def api_kuyruk_al(self, request, robot):
        d = await request.json() if (await request.body()) else {}
        o = self.db.oge_al(request.path_params["ad"], robot["ad"], d.get("is_id"))
        return JSONResponse(o) if o else Response(status_code=204)

    async def api_oge_bitir(self, request, robot):
        oid = request.path_params["id"]
        o = self.db.tek("SELECT * FROM kuyruk_ogeleri WHERE id=?", (oid,))
        if not o or o["robot"] != robot["ad"]:
            raise ValueError("Bu öğe bu robota ait değil")
        d = await request.json()
        durum = d.get("durum")
        if durum not in ("basarili", "is_hatasi", "sistem_hatasi"):
            raise ValueError("durum: basarili | is_hatasi | sistem_hatasi")
        sonuc = self.db.oge_bitir(oid, durum, d.get("sonuc"), str(d.get("hata", ""))[:2000])
        if sonuc == "basarisiz":
            self.bildirici.gonder("oge_basarisiz", f"{o['kuyruk']} / {o['referans']} işlenemedi",
                                  {"Kuyruk": o["kuyruk"], "Referans": o["referans"], "Robot": robot["ad"],
                                   "Hata türü": "İş kuralı" if durum == "is_hatasi" else "Sistem",
                                   "Hata": d.get("hata", "")}, self.link(f"/kuyruklar/{o['kuyruk']}"))
        return JSONResponse({"durum": sonuc})

    async def api_varlik(self, request, robot):
        v = self.db.varlik_oku(request.path_params["ad"])
        if not v:
            return JSONResponse({"hata": "Varlık bulunamadı"}, status_code=404)
        self.db.denetle(f"robot:{robot['ad']}", "varlik_okundu", v["ad"])
        return JSONResponse(v)

    async def marka_dosyasi(self, request):
        ad = request.path_params["ad"]
        if ad not in ("logo.png", "logo_koyu.png", "favicon.png", "simge.png"):
            return Response(status_code=404)
        r = FileResponse(marka.kaynak(ad), media_type="image/png")
        r.headers["Cache-Control"] = "public, max-age=86400"
        return r

    async def saglik(self, request):
        return JSONResponse({"durum": "ok", "urun": marka.URUN, "surum": marka.SURUM, "zaman": time.time()})

    # ================================================================== panel
    def panel(self, rol="izleyici"):
        def sar(fn):
            async def ic(request):
                k = self.oturum(request)
                if not k:
                    return RedirectResponse("/giris", status_code=303)
                if not P.yetkili(k, rol):
                    return HTMLResponse(P.sayfa("Yetki yok", '<div class="hata">Bu sayfa için yetkiniz yok.</div>', k),
                                        status_code=403)
                try:
                    return await fn(request, k)
                except PermissionError as ex:
                    return HTMLResponse(P.sayfa("Hata", f'<div class="hata">{P.e(ex)}</div>', k), status_code=403)
                except (ValueError, KeyError) as ex:
                    geri = urllib.parse.urlparse(request.headers.get("referer", "/")).path or "/"
                    return self.yonlendir(geri, str(ex), "hata")
            return ic
        return sar

    async def giris(self, request):
        if request.method == "GET":
            return HTMLResponse(P.giris_sayfasi())
        f = await request.form()
        token = self.db.giris(str(f.get("ad", "")), str(f.get("sifre", "")))
        if not token:
            await asyncio.sleep(1)
            self.db.denetle(str(f.get("ad", ""))[:60], "giris_basarisiz", request.client.host if request.client else "")
            return HTMLResponse(P.giris_sayfasi("Kullanıcı adı ya da parola hatalı"), status_code=401)
        self.db.denetle(str(f.get("ad")), "giris", request.client.host if request.client else "")
        r = RedirectResponse("/", status_code=303)
        r.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=self.https, max_age=12 * 3600)
        return r

    async def cikis(self, request, k):
        await self.form(request, k)
        self.db.cikis(request.cookies.get(COOKIE))
        r = RedirectResponse("/giris", status_code=303)
        r.delete_cookie(COOKIE)
        return r

    # ------------------------------------------------------------------ pano
    async def pano(self, request, k):
        db = self.db
        bugun = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
        robotlar = db.sorgu("SELECT * FROM robotlar ORDER BY ad")
        esik = time.time() - self.ayarlar.getint("MERKEZ", "cevrimdisi_esik_sn")
        cevrimici = sum(1 for r in robotlar if r["aktif"] and r["son_gorulme"] and r["son_gorulme"] >= esik)
        say = lambda sql, p=(): db.tek(sql, p)["n"]  # noqa: E731
        kpi = [
            (f"{cevrimici}/{sum(1 for r in robotlar if r['aktif'])}", "Çevrimiçi robot"),
            (say("SELECT COUNT(*) n FROM isler WHERE durum='calisiyor'"), "Çalışan iş"),
            (say("SELECT COUNT(*) n FROM isler WHERE durum='bekliyor'"), "Bekleyen iş"),
            (say("SELECT COUNT(*) n FROM isler WHERE durum='basarili' AND bitis>=?", (bugun,)), "Bugün başarılı"),
            (say("SELECT COUNT(*) n FROM isler WHERE durum='basarisiz' AND bitis>=?", (bugun,)), "Bugün başarısız"),
            (say("SELECT COUNT(*) n FROM kuyruk_ogeleri WHERE durum IN ('yeni','isleniyor')"), "Kuyrukta bekleyen öğe"),
            (say("SELECT COUNT(*) n FROM kuyruk_ogeleri WHERE durum='basarisiz' AND bitis>=?", (bugun,)), "Bugün başarısız öğe"),
        ]
        kpi_html = '<div class="kpi">' + "".join(f"<div><b>{P.e(v)}</b><span>{P.e(a)}</span></div>" for v, a in kpi) + "</div>"
        rob = P.tablo(["Robot", "Durum", "Makine", "Son görülme", "Çalışan iş"], [
            [P.e(r["ad"]), P.rozet(self._robot_durum(r, esik)), P.e(r["makine"]), P.zaman(r["son_gorulme"]),
             f'<a href="/isler/{r["calisan_is"]}">#{r["calisan_is"]}</a>' if r["calisan_is"] else "—"]
            for r in robotlar], "Henüz robot eklenmedi — Robotlar sayfasından ekleyin.", kirilmaz={0, 1, 3})
        isler = db.sorgu("SELECT * FROM isler ORDER BY id DESC LIMIT 15")
        kuy = db.kuyruk_ozet()
        govde = (kpi_html + '<div class="kart"><h2 style="margin-top:0">Robotlar</h2>' + rob + "</div>"
                 + '<div class="kart"><h2 style="margin-top:0">Son işler</h2>' + self._is_tablosu(isler) + "</div>"
                 + '<div class="kart"><h2 style="margin-top:0">Kuyruklar</h2>' + self._kuyruk_ozet_tablosu(kuy) + "</div>")
        return HTMLResponse(P.sayfa("Pano", govde, k, "/", yenile=15, mesaj=self.mesaj(request)))

    def cevrimdisi_esik(self):
        return time.time() - self.ayarlar.getint("MERKEZ", "cevrimdisi_esik_sn")

    def _oturum_rozeti(self, r, esik):
        if not r.get("oturum") or not r["son_gorulme"] or r["son_gorulme"] < esik:
            return "—"
        return P.rozet({"acik": "oturum_acik", "kilitli": "oturum_kilitli", "servis": "oturum_servis"}.get(
            r["oturum"], r["oturum"]))

    def _robot_durum(self, r, esik):
        if not r["aktif"]:
            return "pasif"
        if not r["son_gorulme"]:
            return "bilinmiyor"
        if r["son_gorulme"] < esik:
            return "cevrimdisi"
        return "mesgul" if r["calisan_is"] else "bosta"

    def _is_tablosu(self, isler):
        return P.tablo(["#", "Süreç", "Durum", "Robot", "Deneme", "Oluşturma", "Süre", "Oluşturan"], [
            [f'<a href="/isler/{j["id"]}">#{j["id"]}</a>', P.e(j["surec"]), P.rozet(j["durum"]),
             P.e(j["robot"] or (f"→ {j['hedef_robot']}" if j["hedef_robot"] else "herhangi")),
             f'{j["deneme"]}/{j["max_deneme"]}', P.zaman(j["olusturma"]),
             P.sure(j["baslama"], j["bitis"]) if j["baslama"] else "—", P.e(j["olusturan"])]
            for j in isler], "Henüz iş yok", kirilmaz={0, 2, 3, 4, 5, 6})

    def _kuyruk_ozet_tablosu(self, kuy):
        return P.tablo(["Kuyruk", "Yeni", "İşleniyor", "Başarılı", "Başarısız", "Toplam"], [
            [f'<a href="/kuyruklar/{P.e(q["kuyruk"])}">{P.e(q["kuyruk"])}</a>', q["yeni"], q["isleniyor"],
             q["basarili"], q["basarisiz"], q["toplam"]] for q in kuy], "Kuyruk öğesi yok")

    def _robot_secenekleri(self, secili=""):
        return P.secenekler([("", "Herhangi bir robot")] + [
            (r["ad"], r["ad"]) for r in self.db.sorgu("SELECT ad FROM robotlar WHERE aktif=1 ORDER BY ad")], secili)

    def _surec_secenekleri(self, secili=""):
        return P.secenekler(surecler.katalog(self.gorev_klasoru), secili)

    @staticmethod
    def _degiskenler(metin):
        return [s.strip() for s in str(metin or "").splitlines() if s.strip()]

    # ------------------------------------------------------------------ işler
    async def isler(self, request, k):
        durum = request.query_params.get("durum", "")
        sql, p = "SELECT * FROM isler", ()
        if durum:
            sql, p = sql + " WHERE durum=?", (durum,)
        isler = self.db.sorgu(sql + " ORDER BY id DESC LIMIT 200", p)
        filtre = '<p class="filtre">' + " ".join(
            f'<a href="/isler{"?durum=" + d if d else ""}"><b>{P.e(a)}</b></a>' if d == durum else
            f'<a href="/isler{"?durum=" + d if d else ""}">{P.e(a)}</a>'
            for d, a in [("", "Tümü"), ("bekliyor", "Bekleyen"), ("calisiyor", "Çalışan"), ("basarili", "Başarılı"),
                         ("basarisiz", "Başarısız"), ("iptal", "İptal")]) + "</p>"
        yeni = ""
        if P.yetkili(k, "operator"):
            yeni = f"""<div class="kart"><h2 style="margin-top:0">Yeni iş başlat</h2>
<form class="satir" method="post" action="/isler/yeni">{P.csrf_alani(k)}
<label>Süreç<select name="surec">{self._surec_secenekleri()}</select></label>
<label>Robot<select name="hedef_robot">{self._robot_secenekleri()}</select></label>
<label>Öncelik (1 yüksek)<input name="oncelik" type="number" min="1" max="9" value="5" style="width:90px"></label>
<label>Deneme hakkı<input name="max_deneme" type="number" min="1" max="10" value="1" style="width:90px"></label>
<label>Zaman aşımı (dk)<input name="max_sure_dk" type="number" min="1" max="1440" value="120" style="width:110px"></label>
<label style="flex:1 1 260px">Robot değişkenleri (her satıra AD:değer)<textarea name="degiskenler" placeholder="KURU_CALISMA:evet"></textarea></label>
<button>Başlat</button></form></div>"""
        govde = yeni + filtre + self._is_tablosu(isler)
        return HTMLResponse(P.sayfa("İşler", govde, k, "/isler", yenile=20 if not yeni else None, mesaj=self.mesaj(request)))

    async def is_yeni(self, request, k):
        f = await self.form(request, k)
        surec = str(f.get("surec", ""))
        degiskenler = self._degiskenler(f.get("degiskenler"))
        surecler.komut(surec, degiskenler, self.gorev_klasoru)  # doğrula
        is_id = self.db.is_ekle(surec, degiskenler, str(f.get("hedef_robot", "")), int(f.get("oncelik") or 5),
                                int(f.get("max_deneme") or 1), int(f.get("max_sure_dk") or 120), k["ad"])
        self.db.denetle(k["ad"], "is_baslatti", {"is": is_id, "surec": surec, "robot": f.get("hedef_robot", "")})
        return self.yonlendir(f"/isler/{is_id}", f"İş #{is_id} kuyruğa alındı")

    async def is_detay(self, request, k):
        is_id = request.path_params["id"]
        j = self.db.tek("SELECT * FROM isler WHERE id=?", (is_id,))
        if not j:
            return HTMLResponse(P.sayfa("Bulunamadı", "<p>İş bulunamadı.</p>", k), status_code=404)
        eylem = ""
        if P.yetkili(k, "operator"):
            if j["durum"] in ("bekliyor", "calisiyor"):
                eylem += P.dugme_form(f"/isler/{is_id}/iptal", "İptal et", k, "tehlike", "İş iptal edilsin mi?")
            eylem += " " + P.dugme_form(f"/isler/{is_id}/yeniden", "Yeniden çalıştır", k)
        raporlar = json.loads(j["raporlar"] or "[]")
        rap = " · ".join(f'<a href="/raporlar/{is_id}/{P.e(r)}" target="_blank">{P.e(r)}</a>' for r in raporlar) or "—"
        bilgi = P.tablo(["Alan", "Değer"], [
            ["Süreç", P.e(j["surec"])], ["Durum", P.rozet(j["durum"]) + (" (iptal istendi)" if j["iptal_istendi"] else "")],
            ["Robot", P.e(j["robot"] or "—")], ["Hedef robot", P.e(j["hedef_robot"] or "herhangi")],
            ["Değişkenler", P.e(", ".join(json.loads(j["argumanlar"] or "[]")) or "—")],
            ["Deneme", f'{j["deneme"]}/{j["max_deneme"]}'], ["Öncelik", j["oncelik"]],
            ["Oluşturan", P.e(j["olusturan"])], ["Oluşturma", P.zaman(j["olusturma"])],
            ["Başlama", P.zaman(j["baslama"])], ["Bitiş", P.zaman(j["bitis"])],
            ["Süre", P.sure(j["baslama"], j["bitis"]) if j["baslama"] else "—"],
            ["Çıkış kodu", P.e(j["cikis_kodu"]) if j["cikis_kodu"] is not None else "—"],
            ["Özet", P.e(j["ozet"] or "—")], ["Raporlar", rap]])
        ogeler = self.db.sorgu("SELECT * FROM kuyruk_ogeleri WHERE is_id=? ORDER BY id", (is_id,))
        oge_html = ""
        if ogeler:
            oge_html = '<h2>Bu işte işlenen kuyruk öğeleri</h2>' + self._oge_tablosu(ogeler, k, eylemsiz=True)
        govde = (f'<p>{eylem}</p><div class="kart">{bilgi}</div>{oge_html}<h2>Log</h2>'
                 f'<pre>{P.e(j["log"] or "(henüz log yok)")}</pre>')
        yenile = 5 if j["durum"] in ("bekliyor", "calisiyor") else None
        return HTMLResponse(P.sayfa(f"İş #{is_id}", govde, k, "/isler", yenile=yenile, mesaj=self.mesaj(request)))

    async def is_iptal(self, request, k):
        await self.form(request, k)
        is_id = request.path_params["id"]
        s = self.db.is_iptal(is_id)
        self.db.denetle(k["ad"], "is_iptal", {"is": is_id, "sonuc": s})
        return self.yonlendir(f"/isler/{is_id}", "İptal edildi" if s == "iptal" else "İptal isteği robota iletilecek")

    async def is_yeniden(self, request, k):
        await self.form(request, k)
        yeni = self.db.is_yeniden(request.path_params["id"], k["ad"])
        self.db.denetle(k["ad"], "is_yeniden", {"eski": request.path_params["id"], "yeni": yeni})
        return self.yonlendir(f"/isler/{yeni}", f"İş #{yeni} oluşturuldu")

    async def rapor(self, request, k):
        is_id, ad = request.path_params["id"], os.path.basename(request.path_params["ad"])
        yol = os.path.join(self.rapor_klasoru, str(is_id), ad)
        if not os.path.isfile(yol):
            return HTMLResponse("Bulunamadı", status_code=404)
        r = FileResponse(yol)
        r.headers["Content-Security-Policy"] = "sandbox allow-scripts allow-popups"  # rapor HTML'i izole
        return r

    # ------------------------------------------------------------------ kuyruklar
    def _oge_tablosu(self, ogeler, k, eylemsiz=False):
        satirlar = []
        for o in ogeler:
            eylem = ""
            if not eylemsiz and P.yetkili(k, "operator") and o["durum"] in ("basarisiz", "basarili"):
                eylem = P.dugme_form(f"/kuyruklar/oge/{o['id']}/yeniden", "Yeniden işle", k)
            if not eylemsiz and P.yetkili(k, "yonetici"):
                eylem += " " + P.dugme_form(f"/kuyruklar/oge/{o['id']}/sil", "Sil", k, "ikincil", "Öğe silinsin mi?")
            hata = P.e(o["hata"])
            if o["hata_turu"]:
                hata = f'<span class="soluk">[{"İş kuralı" if o["hata_turu"] == "is" else "Sistem"}]</span> ' + hata
            satirlar.append([o["id"], P.e(o["referans"]), P.rozet(o["durum"]), f'{o["deneme"]}/{o["max_deneme"]}',
                             P.e(o["robot"] or "—"),
                             f'<a href="/isler/{o["is_id"]}">#{o["is_id"]}</a>' if o["is_id"] else "—",
                             P.zaman(o["olusturma"]), P.zaman(o["bitis"]), P.oge_sonucu(o["sonuc"]), hata, eylem])
        return P.tablo(["#", "Referans", "Durum", "Deneme", "Robot", "İş", "Eklenme", "Bitiş", "Sonuç", "Hata", ""],
                       satirlar, "Öğe yok", kirilmaz={1, 2, 3, 4, 5, 6, 7, 10})

    async def kuyruklar(self, request, k):
        return HTMLResponse(P.sayfa("Kuyruklar", self._kuyruk_ozet_tablosu(self.db.kuyruk_ozet()), k, "/kuyruklar",
                                    yenile=20, mesaj=self.mesaj(request)))

    async def kuyruk(self, request, k):
        ad = request.path_params["ad"]
        durum = request.query_params.get("durum", "")
        sql, p = "SELECT * FROM kuyruk_ogeleri WHERE kuyruk=?", [ad]
        if durum:
            sql += " AND durum=?"
            p.append(durum)
        ogeler = self.db.sorgu(sql + " ORDER BY id DESC LIMIT 300", p)
        filtre = '<p class="filtre">' + " ".join(
            f'<a href="/kuyruklar/{P.e(ad)}{"?durum=" + d if d else ""}">{"<b>" if d == durum else ""}{P.e(a)}{"</b>" if d == durum else ""}</a>'
            for d, a in [("", "Tümü"), ("yeni", "Yeni"), ("isleniyor", "İşleniyor"), ("basarili", "Başarılı"),
                         ("basarisiz", "Başarısız")]) + "</p>"
        return HTMLResponse(P.sayfa(f"Kuyruk: {ad}", filtre + self._oge_tablosu(ogeler, k), k, "/kuyruklar",
                                    mesaj=self.mesaj(request)))

    async def oge_yeniden(self, request, k):
        await self.form(request, k)
        oid = request.path_params["id"]
        o = self.db.tek("SELECT kuyruk FROM kuyruk_ogeleri WHERE id=?", (oid,))
        self.db.oge_yeniden(oid)
        self.db.denetle(k["ad"], "oge_yeniden", {"oge": oid})
        return self.yonlendir(f"/kuyruklar/{o['kuyruk'] if o else ''}", "Öğe yeniden kuyruğa alındı")

    async def oge_sil(self, request, k):
        await self.form(request, k)
        oid = request.path_params["id"]
        o = self.db.tek("SELECT kuyruk, referans FROM kuyruk_ogeleri WHERE id=?", (oid,))
        self.db.yaz("DELETE FROM kuyruk_ogeleri WHERE id=? AND durum!='isleniyor'", (oid,))
        self.db.denetle(k["ad"], "oge_sil", o or {"oge": oid})
        return self.yonlendir(f"/kuyruklar/{o['kuyruk'] if o else ''}", "Öğe silindi")

    # ------------------------------------------------------------------ zamanlamalar
    async def zamanlamalar(self, request, k):
        zs = self.db.sorgu("SELECT * FROM zamanlamalar ORDER BY ad")
        satirlar = []
        for z in zs:
            eylem = ""
            if P.yetkili(k, "operator"):
                eylem = P.dugme_form(f"/zamanlamalar/{z['id']}/degistir", "Durdur" if z["aktif"] else "Başlat", k)
                eylem += " " + P.dugme_form(f"/zamanlamalar/{z['id']}/simdi", "Şimdi çalıştır", k)
            if P.yetkili(k, "yonetici"):
                eylem += " " + P.dugme_form(f"/zamanlamalar/{z['id']}/sil", "Sil", k, "ikincil", "Zamanlama silinsin mi?")
            satirlar.append([P.e(z["ad"]), P.e(z["surec"]), f'<code>{P.e(z["cron"])}</code>',
                             P.e(z["hedef_robot"] or "herhangi"), P.rozet("cevrimici" if z["aktif"] else "pasif"),
                             P.zaman(z["sonraki"]) if z["aktif"] else "—", P.zaman(z["son_calisma"]), eylem])
        govde = P.tablo(["Ad", "Süreç", "Cron", "Robot", "Durum", "Sonraki", "Son çalışma", ""], satirlar,
                        "Zamanlama yok")
        if P.yetkili(k, "yonetici"):
            govde += f"""<div class="kart" style="margin-top:16px"><h2 style="margin-top:0">Yeni zamanlama</h2>
<form class="satir" method="post" action="/zamanlamalar/yeni">{P.csrf_alani(k)}
<label>Ad<input name="ad" required></label>
<label>Süreç<select name="surec">{self._surec_secenekleri()}</select></label>
<label>Cron<input name="cron" required placeholder="*/15 8-18 * * 1-5" style="width:170px"></label>
<label>Robot<select name="hedef_robot">{self._robot_secenekleri()}</select></label>
<label>Deneme hakkı<input name="max_deneme" type="number" min="1" max="10" value="2" style="width:90px"></label>
<label style="flex:1 1 220px">Robot değişkenleri (AD:değer)<textarea name="degiskenler"></textarea></label>
<button>Ekle</button></form>
<p class="soluk">Cron: dakika saat gün ay haftanın-günü (yerel saat). Örnekler: <code>*/15 * * * *</code> her 15 dk ·
<code>30 8 * * 1-5</code> hafta içi 08:30 · <code>0 7 1 * *</code> her ayın 1'i 07:00 · <code>@gunluk</code></p></div>"""
        return HTMLResponse(P.sayfa("Zamanlamalar", govde, k, "/zamanlamalar", mesaj=self.mesaj(request)))

    async def zamanlama_yeni(self, request, k):
        f = await self.form(request, k)
        cron_ifade = str(f.get("cron", "")).strip()
        if not gecerli_mi(cron_ifade):
            raise ValueError(f"Geçersiz cron ifadesi: {cron_ifade}")
        surec = str(f.get("surec", ""))
        degiskenler = self._degiskenler(f.get("degiskenler"))
        surecler.komut(surec, degiskenler, self.gorev_klasoru)
        zid = self.db.zamanlama_ekle(str(f.get("ad", "")).strip()[:80] or surec, surec, cron_ifade, degiskenler,
                                     str(f.get("hedef_robot", "")), int(f.get("max_deneme") or 1), k["ad"])
        self.db.denetle(k["ad"], "zamanlama_ekle", {"id": zid, "surec": surec, "cron": cron_ifade})
        return self.yonlendir("/zamanlamalar", "Zamanlama eklendi")

    async def zamanlama_degistir(self, request, k):
        await self.form(request, k)
        zid = request.path_params["id"]
        z = self.db.tek("SELECT * FROM zamanlamalar WHERE id=?", (zid,))
        if z:
            aktif = 0 if z["aktif"] else 1
            sonraki = Cron(z["cron"]).sonraki().timestamp() if aktif else z["sonraki"]
            self.db.yaz("UPDATE zamanlamalar SET aktif=?, sonraki=? WHERE id=?", (aktif, sonraki, zid))
            self.db.denetle(k["ad"], "zamanlama_" + ("baslat" if aktif else "durdur"), z["ad"])
        return self.yonlendir("/zamanlamalar")

    async def zamanlama_simdi(self, request, k):
        await self.form(request, k)
        z = self.db.tek("SELECT * FROM zamanlamalar WHERE id=?", (request.path_params["id"],))
        if not z:
            raise ValueError("Zamanlama bulunamadı")
        is_id = self.db.is_ekle(z["surec"], json.loads(z["argumanlar"]), z["hedef_robot"], 5, z["max_deneme"],
                                olusturan=k["ad"], zamanlama_id=z["id"])
        self.db.denetle(k["ad"], "zamanlama_simdi", {"zamanlama": z["ad"], "is": is_id})
        return self.yonlendir(f"/isler/{is_id}", f"İş #{is_id} oluşturuldu")

    async def zamanlama_sil(self, request, k):
        await self.form(request, k)
        z = self.db.tek("SELECT ad FROM zamanlamalar WHERE id=?", (request.path_params["id"],))
        self.db.yaz("DELETE FROM zamanlamalar WHERE id=?", (request.path_params["id"],))
        self.db.denetle(k["ad"], "zamanlama_sil", z["ad"] if z else "")
        return self.yonlendir("/zamanlamalar", "Zamanlama silindi")

    # ------------------------------------------------------------------ robotlar
    async def robotlar(self, request, k, yeni_anahtar=None):
        esik = time.time() - self.ayarlar.getint("MERKEZ", "cevrimdisi_esik_sn")
        satirlar = []
        for r in self.db.sorgu("SELECT * FROM robotlar ORDER BY ad"):
            eylem = ""
            if P.yetkili(k, "yonetici"):
                eylem = P.dugme_form(f"/robotlar/{r['id']}/degistir", "Pasifleştir" if r["aktif"] else "Etkinleştir", k)
                eylem += " " + P.dugme_form(f"/robotlar/{r['id']}/anahtar", "Yeni anahtar", k, "ikincil",
                                            "Eski anahtar geçersiz olacak. Devam edilsin mi?")
                eylem += " " + P.dugme_form(f"/robotlar/{r['id']}/sil", "Sil", k, "ikincil", "Robot silinsin mi?")
            satirlar.append([P.e(r["ad"]), P.rozet(self._robot_durum(r, esik)), self._oturum_rozeti(r, esik),
                             P.e(r["makine"]), P.e(r["surum"]), P.zaman(r["son_gorulme"]), P.e(r["aciklama"]), eylem])
        govde = ""
        if yeni_anahtar:
            ad, anahtar = yeni_anahtar
            url = self.panel_url or f"http://{socket.gethostname()}:{self.ayarlar.get('MERKEZ', 'port')}"
            govde += f"""<div class="uyari"><b>{P.e(ad)}</b> robotunun anahtarı aşağıdadır. <b>Bu anahtar yalnızca bir kez gösterilir.</b>
Robot makinesindeki config.ini dosyasına yazın:<span class="anahtar">[AJAN]<br>merkez_url = {P.e(url)}<br>robot_adi = {P.e(ad)}<br>robot_anahtari = {P.e(anahtar)}</span></div>"""
        govde += P.tablo(["Robot", "Durum", "Windows oturumu", "Makine", "Sürüm", "Son görülme", "Açıklama", ""], satirlar,
                         "Henüz robot yok")
        if P.yetkili(k, "yonetici"):
            govde += f"""<div class="kart" style="margin-top:16px"><h2 style="margin-top:0">Robot ekle</h2>
<form class="satir" method="post" action="/robotlar/yeni">{P.csrf_alani(k)}
<label>Ad (ör. IK-ROBOT-1)<input name="ad" required pattern="[A-Za-z0-9_.\\-]+"></label>
<label style="flex:1 1 260px">Açıklama<input name="aciklama"></label><button>Ekle</button></form></div>"""
        return HTMLResponse(P.sayfa("Robotlar", govde, k, "/robotlar", mesaj=self.mesaj(request)))

    async def robot_yeni(self, request, k):
        f = await self.form(request, k)
        ad = str(f.get("ad", "")).strip()
        if not re.match(r"^[A-Za-z0-9_.\-]{1,60}$", ad):
            raise ValueError("Robot adı yalnızca harf, rakam, _ . - içerebilir")
        if self.db.tek("SELECT id FROM robotlar WHERE ad=?", (ad,)):
            raise ValueError("Bu adda robot zaten var")
        anahtar = self.db.robot_ekle(ad, str(f.get("aciklama", ""))[:200])
        self.db.denetle(k["ad"], "robot_ekle", ad)
        return await self.robotlar(request, k, (ad, anahtar))

    async def robot_anahtar(self, request, k):
        await self.form(request, k)
        r = self.db.tek("SELECT * FROM robotlar WHERE id=?", (request.path_params["id"],))
        if not r:
            raise ValueError("Robot bulunamadı")
        anahtar = self.db.robot_anahtar_yenile(r["id"])
        self.db.denetle(k["ad"], "robot_anahtar_yenile", r["ad"])
        return await self.robotlar(request, k, (r["ad"], anahtar))

    async def robot_degistir(self, request, k):
        await self.form(request, k)
        r = self.db.tek("SELECT * FROM robotlar WHERE id=?", (request.path_params["id"],))
        if r:
            self.db.yaz("UPDATE robotlar SET aktif=? WHERE id=?", (0 if r["aktif"] else 1, r["id"]))
            self.db.denetle(k["ad"], "robot_" + ("pasif" if r["aktif"] else "aktif"), r["ad"])
        return self.yonlendir("/robotlar")

    async def robot_sil(self, request, k):
        await self.form(request, k)
        r = self.db.tek("SELECT * FROM robotlar WHERE id=?", (request.path_params["id"],))
        if r:
            self.db.yaz("DELETE FROM robotlar WHERE id=?", (r["id"],))
            self.db.denetle(k["ad"], "robot_sil", r["ad"])
        return self.yonlendir("/robotlar", "Robot silindi")

    # ------------------------------------------------------------------ varlıklar
    async def varliklar(self, request, k):
        satirlar = [[P.e(v["ad"]), "Kimlik bilgisi" if v["tur"] == "kimlik" else "Metin", P.e(v["kullanici_adi"] or "—"),
                     "••••••", P.e(v["aciklama"]), P.zaman(v["guncelleme"]),
                     P.dugme_form(f"/varliklar/{v['id']}/sil", "Sil", k, "ikincil", "Varlık silinsin mi?")]
                    for v in self.db.sorgu("SELECT * FROM varliklar ORDER BY ad")]
        govde = P.tablo(["Ad", "Tür", "Kullanıcı adı", "Değer", "Açıklama", "Güncelleme", ""], satirlar, "Varlık yok")
        govde += f"""<div class="kart" style="margin-top:16px"><h2 style="margin-top:0">Varlık ekle / güncelle</h2>
<form class="satir" method="post" action="/varliklar/kaydet" autocomplete="off">{P.csrf_alani(k)}
<label>Ad (ör. MIKRO_GIRIS)<input name="ad" required pattern="[A-Za-z0-9_.\\-]+"></label>
<label>Tür<select name="tur"><option value="kimlik">Kimlik bilgisi (kullanıcı + parola)</option><option value="metin">Metin</option></select></label>
<label>Kullanıcı adı<input name="kullanici_adi" autocomplete="off"></label>
<label>Değer / parola<input name="deger" type="password" required autocomplete="new-password"></label>
<label style="flex:1 1 200px">Açıklama<input name="aciklama"></label><button>Kaydet</button></form>
<p class="soluk">Değerler şifreli saklanır, panelde gösterilmez. Robotlar <code>varlik:AD</code> (parola) ve
<code>varlik:AD.kullanici</code> ile config.ini'de ya da Robot görevlerinde <code>Varlık Al</code> anahtar kelimesiyle kullanır.</p></div>"""
        return HTMLResponse(P.sayfa("Varlıklar", govde, k, "/varliklar", mesaj=self.mesaj(request)))

    async def varlik_kaydet(self, request, k):
        f = await self.form(request, k)
        ad = str(f.get("ad", "")).strip()
        if not re.match(r"^[A-Za-z0-9_.\-]{1,60}$", ad):
            raise ValueError("Varlık adı yalnızca harf, rakam, _ . - içerebilir")
        self.db.varlik_kaydet(ad, str(f.get("deger", "")), str(f.get("tur", "metin")),
                              str(f.get("kullanici_adi", ""))[:200], str(f.get("aciklama", ""))[:200])
        self.db.denetle(k["ad"], "varlik_kaydet", ad)
        return self.yonlendir("/varliklar", f"{ad} kaydedildi")

    async def varlik_sil(self, request, k):
        await self.form(request, k)
        v = self.db.tek("SELECT ad FROM varliklar WHERE id=?", (request.path_params["id"],))
        self.db.yaz("DELETE FROM varliklar WHERE id=?", (request.path_params["id"],))
        self.db.denetle(k["ad"], "varlik_sil", v["ad"] if v else "")
        return self.yonlendir("/varliklar", "Varlık silindi")

    # ------------------------------------------------------------------ kullanıcılar
    async def kullanicilar(self, request, k):
        satirlar = []
        for u in self.db.sorgu("SELECT * FROM kullanicilar ORDER BY ad"):
            eylem = ""
            if u["id"] != k["id"]:
                eylem = P.dugme_form(f"/kullanicilar/{u['id']}/degistir", "Pasifleştir" if u["aktif"] else "Etkinleştir", k)
            satirlar.append([P.e(u["ad"]), P.e(u["rol"]), P.rozet("cevrimici" if u["aktif"] else "pasif"),
                             P.zaman(u["olusturma"]), eylem])
        roller = P.secenekler([(r, r) for r in ROLLER], "operator")
        govde = P.tablo(["Kullanıcı", "Rol", "Durum", "Oluşturma", ""], satirlar)
        govde += f"""<div class="kart" style="margin-top:16px"><h2 style="margin-top:0">Kullanıcı ekle</h2>
<form class="satir" method="post" action="/kullanicilar/yeni" autocomplete="off">{P.csrf_alani(k)}
<label>Kullanıcı adı<input name="ad" required></label><label>Rol<select name="rol">{roller}</select></label>
<label>Parola (en az 8)<input name="sifre" type="password" required minlength="8" autocomplete="new-password"></label>
<button>Ekle</button></form>
<p class="soluk">izleyici: yalnızca görüntüler · operator: iş başlatır/iptal eder, öğeleri yeniden işler, zamanlamaları durdurur ·
yonetici: robotlar, varlıklar, zamanlamalar, kullanıcılar</p></div>
<div class="kart"><h2 style="margin-top:0">Parolamı değiştir</h2>
<form class="satir" method="post" action="/kullanicilar/parola" autocomplete="off">{P.csrf_alani(k)}
<label>Yeni parola<input name="sifre" type="password" required minlength="8" autocomplete="new-password"></label><button>Değiştir</button></form></div>"""
        return HTMLResponse(P.sayfa("Kullanıcılar", govde, k, "/kullanicilar", mesaj=self.mesaj(request)))

    async def kullanici_yeni(self, request, k):
        f = await self.form(request, k)
        ad = str(f.get("ad", "")).strip()
        if not AD_DESENI.match(ad):
            raise ValueError("Geçersiz kullanıcı adı")
        if self.db.tek("SELECT id FROM kullanicilar WHERE ad=?", (ad,)):
            raise ValueError("Bu kullanıcı zaten var")
        self.db.kullanici_ekle(ad, str(f.get("sifre", "")), str(f.get("rol", "izleyici")))
        self.db.denetle(k["ad"], "kullanici_ekle", {"ad": ad, "rol": f.get("rol")})
        return self.yonlendir("/kullanicilar", f"{ad} eklendi")

    async def kullanici_degistir(self, request, k):
        await self.form(request, k)
        u = self.db.tek("SELECT * FROM kullanicilar WHERE id=?", (request.path_params["id"],))
        if u and u["id"] != k["id"]:
            self.db.yaz("UPDATE kullanicilar SET aktif=? WHERE id=?", (0 if u["aktif"] else 1, u["id"]))
            self.db.yaz("DELETE FROM oturumlar WHERE kullanici_id=?", (u["id"],))
            self.db.denetle(k["ad"], "kullanici_" + ("pasif" if u["aktif"] else "aktif"), u["ad"])
        return self.yonlendir("/kullanicilar")

    async def parola(self, request, k):
        f = await self.form(request, k)
        self.db.kullanici_sifre(k["id"], str(f.get("sifre", "")))
        self.db.denetle(k["ad"], "parola_degisti", "")
        r = self.yonlendir("/giris")
        r.delete_cookie(COOKIE)
        return r

    # ------------------------------------------------------------------ MCP / LLM bağlantısı
    def _mcp_url(self, request):
        kok = self.panel_url or f"{request.url.scheme}://{request.url.netloc}"
        return kok.rstrip("/") + "/mcp"

    async def mcp_baglanti(self, request, k, yeni_anahtar=None):
        aktif = self.ayarlar.getbool("MCP", "aktif")
        url = self._mcp_url(request)
        govde = ""
        if not aktif:
            govde += ('<div class="uyari">MCP şu an <b>kapalı</b>. Açmak için merkez makinesindeki config.ini dosyasında '
                      '<code>[MCP] aktif = evet</code> yapıp Kontrol Merkezi\'ni yeniden başlatın.</div>')
        if yeni_anahtar:
            govde += (f'<div class="uyari"><b>Yeni MCP anahtarınız</b> — yalnızca şimdi gösterilir, güvenli bir yere kaydedin:'
                      f'<span class="anahtar">{P.e(yeni_anahtar)}</span>Bu anahtarla bağlanan LLM, '
                      f'<b>{P.e(k["ad"])}</b> hesabının <b>{P.e(k["rol"])}</b> yetkileriyle çalışır.</div>')
        kisisel = self.ayarlar.getbool("MCP", "kisisel_veri_paylas")
        govde += f"""<div class="kart"><h2 style="margin-top:0">Bağlantı bilgileri</h2>
<p>MCP adresi: <span class="anahtar">{P.e(url)}</span></p>
<p class="soluk">Kimlik doğrulama: <code>Authorization: Bearer &lt;anahtar&gt;</code> ya da <code>X-API-Key: &lt;anahtar&gt;</code>.
Kişisel veri paylaşımı: <b>{"açık" if kisisel else "kapalı (TC maskeli, ad soyad ve loglar gönderilmez)"}</b>.</p></div>"""
        satirlar = [[P.e(a["ad"]), f'<code>{P.e(a["on_ek"])}…</code>', P.zaman(a["olusturma"]), P.zaman(a["son_kullanim"]),
                     P.dugme_form(f"/mcp-baglanti/{a['id']}/iptal", "İptal et", k, "ikincil", "Anahtar iptal edilsin mi?")]
                    for a in self.db.api_anahtarlari(k["id"])]
        govde += ('<div class="kart"><h2 style="margin-top:0">MCP anahtarlarım</h2>'
                  + P.tablo(["Ad", "Anahtar", "Oluşturma", "Son kullanım", ""], satirlar, "Henüz anahtar yok")
                  + f"""<form class="satir" method="post" action="/mcp-baglanti/yeni" style="margin-top:12px">{P.csrf_alani(k)}
<label>Anahtar adı (ör. Copilot, Claude Desktop)<input name="ad" required maxlength="60"></label><button>Anahtar oluştur</button></form></div>""")
        exe = r"C:\\AlamountRPA\\AlamountRPA.exe"
        govde += f"""<div class="kart"><h2 style="margin-top:0">Microsoft Copilot Studio</h2>
<ol><li>Copilot Studio'da ajanınızı açın → <b>Araçlar (Tools)</b> → <b>Araç ekle</b> → <b>Model Context Protocol</b> → <b>Yeni</b>.</li>
<li>Sunucu URL'si: <code>{P.e(url)}</code></li>
<li>Kimlik doğrulama: <b>API anahtarı</b> → tür <b>Üst bilgi (Header)</b> → üst bilgi adı <code>X-API-Key</code>.</li>
<li>Bağlantı oluştururken yukarıda aldığınız anahtarı girin.</li></ol>
<p class="soluk">Copilot Studio bulutta çalışır: merkez adresinin internetten <b>HTTPS</b> ile erişilebilir olması gerekir
(ör. kurumsal ters vekil sunucu / güvenlik duvarı kuralı). Microsoft 365 Copilot'ta bu ajan üzerinden kullanılır.</p></div>
<div class="kart"><h2 style="margin-top:0">GitHub Copilot (VS Code)</h2>
<p>Çalışma alanında <code>.vscode/mcp.json</code>:</p>
<pre>{P.e(json.dumps({"inputs": [{"type": "promptString", "id": "alamount-anahtar", "description": "Alamount RPA MCP anahtarı", "password": True}],
                 "servers": {"alamount-rpa": {"type": "http", "url": url,
                                              "headers": {"Authorization": "Bearer ${input:alamount-anahtar}"}}}},
                ensure_ascii=False, indent=2))}</pre></div>
<div class="kart"><h2 style="margin-top:0">Claude Desktop</h2>
<p><code>%APPDATA%\\Claude\\claude_desktop_config.json</code> dosyasına ekleyin (Alamount RPA o bilgisayarda kurulu olmalı;
aşağıdaki komut yerel bir köprü açıp merkeze bağlanır):</p>
<pre>{P.e(json.dumps({"mcpServers": {"alamount-rpa": {"command": exe.replace(chr(92) * 2, chr(92)),
                                                    "args": ["mcp", "--merkez", url],
                                                    "env": {"ALAMOUNT_MCP_ANAHTARI": "alm_..."}}}},
                ensure_ascii=False, indent=2))}</pre>
<p class="soluk">Claude Desktop'u yeniden başlatın; araçlar "alamount-rpa" adıyla görünür.</p></div>
<div class="kart"><h2 style="margin-top:0">LLM'in yapabildikleri</h2>
<p>durum_ozeti, surecleri_listele, isleri_listele, is_detayi, kuyruk_ogeleri, zamanlamalari_listele (herkes) ·
is_baslat, is_iptal_et, ogeyi_yeniden_isle, zamanlama_durdur_baslat (operator) · zamanlama_ekle (yonetici).
Varlık kasası ve kullanıcı yönetimi MCP'den erişilemez. Her çağrı Denetim kaydına "(MCP)" ile yazılır.</p></div>"""
        return HTMLResponse(P.sayfa("MCP / LLM bağlantısı", govde, k, "/mcp-baglanti", mesaj=self.mesaj(request)))

    async def mcp_anahtar_yeni(self, request, k):
        f = await self.form(request, k)
        anahtar = self.db.api_anahtari_olustur(k["id"], str(f.get("ad", "")))
        self.db.denetle(k["ad"], "mcp_anahtar_olustur", str(f.get("ad", ""))[:60])
        return await self.mcp_baglanti(request, k, anahtar)

    async def mcp_anahtar_iptal(self, request, k):
        await self.form(request, k)
        self.db.api_anahtari_iptal(request.path_params["id"], k["id"])
        self.db.denetle(k["ad"], "mcp_anahtar_iptal", str(request.path_params["id"]))
        return self.yonlendir("/mcp-baglanti", "Anahtar iptal edildi")

    async def denetim(self, request, k):
        satirlar = [[P.zaman(d["zaman"]), P.e(d["kim"]), P.e(d["eylem"]), P.e(d["detay"])]
                    for d in self.db.sorgu("SELECT * FROM denetim ORDER BY id DESC LIMIT 500")]
        return HTMLResponse(P.sayfa("Denetim kaydı", P.tablo(["Zaman", "Kim", "Eylem", "Detay"], satirlar), k, "/denetim"))

    # ================================================================== arka plan
    def arka_plan(self):
        esik = self.ayarlar.getint("MERKEZ", "cevrimdisi_esik_sn")
        sahipsiz = self.ayarlar.getint("MERKEZ", "sahipsiz_is_esik_sn")
        son_temizlik = 0
        while not self._dur.wait(10):
            try:
                for is_id in self.db.zamanlamalari_tetikle():
                    log.info("Zamanlama iş #%s oluşturdu", is_id)
                for r in self.db.cevrimdisi_robotlar(esik):
                    log.warning("Robot çevrimdışı: %s", r["ad"])
                    self.bildirici.gonder("robot_cevrimdisi", f"{r['ad']} yanıt vermiyor",
                                          {"Robot": r["ad"], "Makine": r["makine"],
                                           "Son görülme": P.zaman(r["son_gorulme"])}, self.link("/robotlar"))
                for j in self.db.sahipsiz_isler(sahipsiz):
                    sonuc = self.db.is_bitir(j["id"], False, None, "Robot bağlantısı koptu")
                    log.warning("Sahipsiz iş #%s → %s", j["id"], sonuc)
                    if sonuc == "basarisiz":
                        self.bildirici.gonder("is_basarisiz", f"#{j['id']} {j['surec']}: robot bağlantısı koptu",
                                              {"İş": f"#{j['id']}", "Robot": j["robot"]}, self.link(f"/isler/{j['id']}"))
                    self.db.yaz("UPDATE robotlar SET calisan_is=NULL WHERE ad=? AND calisan_is=?", (j["robot"], j["id"]))
                self.db.sahipsiz_ogeler(sahipsiz)
                if time.time() - son_temizlik > 6 * 3600:
                    self.db.temizle(self.ayarlar.getint("MERKEZ", "saklama_gun"))
                    son_temizlik = time.time()
            except Exception:
                log.exception("Arka plan döngüsü hatası")

    # ================================================================== uygulama
    def uygulama(self):
        api, pnl = self.api, self.panel
        R = Route
        rotalar = [
            R("/api/saglik", self.saglik),
            R("/marka/{ad}", self.marka_dosyasi),
            R("/api/nabiz", api(self.api_nabiz), methods=["POST"]),
            R("/api/is/al", api(self.api_is_al), methods=["POST"]),
            R("/api/is/{id:int}/log", api(self.api_is_log), methods=["POST"]),
            R("/api/is/{id:int}/rapor", api(self.api_is_rapor), methods=["POST"]),
            R("/api/is/{id:int}/bitir", api(self.api_is_bitir), methods=["POST"]),
            R("/api/kuyruk/oge/{id:int}/bitir", api(self.api_oge_bitir), methods=["POST"]),
            R("/api/kuyruk/{ad}/ekle", api(self.api_kuyruk_ekle), methods=["POST"]),
            R("/api/kuyruk/{ad}/al", api(self.api_kuyruk_al), methods=["POST"]),
            R("/api/varlik/{ad}", api(self.api_varlik)),
            R("/giris", self.giris, methods=["GET", "POST"]),
            R("/cikis", pnl()(self.cikis), methods=["POST"]),
            R("/", pnl()(self.pano)),
            R("/isler", pnl()(self.isler)),
            R("/isler/yeni", pnl("operator")(self.is_yeni), methods=["POST"]),
            R("/isler/{id:int}", pnl()(self.is_detay)),
            R("/isler/{id:int}/iptal", pnl("operator")(self.is_iptal), methods=["POST"]),
            R("/isler/{id:int}/yeniden", pnl("operator")(self.is_yeniden), methods=["POST"]),
            R("/raporlar/{id:int}/{ad}", pnl()(self.rapor)),
            R("/kuyruklar", pnl()(self.kuyruklar)),
            R("/kuyruklar/oge/{id:int}/yeniden", pnl("operator")(self.oge_yeniden), methods=["POST"]),
            R("/kuyruklar/oge/{id:int}/sil", pnl("yonetici")(self.oge_sil), methods=["POST"]),
            R("/kuyruklar/{ad}", pnl()(self.kuyruk)),
            R("/zamanlamalar", pnl()(self.zamanlamalar)),
            R("/zamanlamalar/yeni", pnl("yonetici")(self.zamanlama_yeni), methods=["POST"]),
            R("/zamanlamalar/{id:int}/degistir", pnl("operator")(self.zamanlama_degistir), methods=["POST"]),
            R("/zamanlamalar/{id:int}/simdi", pnl("operator")(self.zamanlama_simdi), methods=["POST"]),
            R("/zamanlamalar/{id:int}/sil", pnl("yonetici")(self.zamanlama_sil), methods=["POST"]),
            R("/robotlar", pnl()(self.robotlar)),
            R("/robotlar/yeni", pnl("yonetici")(self.robot_yeni), methods=["POST"]),
            R("/robotlar/{id:int}/anahtar", pnl("yonetici")(self.robot_anahtar), methods=["POST"]),
            R("/robotlar/{id:int}/degistir", pnl("yonetici")(self.robot_degistir), methods=["POST"]),
            R("/robotlar/{id:int}/sil", pnl("yonetici")(self.robot_sil), methods=["POST"]),
            R("/varliklar", pnl("yonetici")(self.varliklar)),
            R("/varliklar/kaydet", pnl("yonetici")(self.varlik_kaydet), methods=["POST"]),
            R("/varliklar/{id:int}/sil", pnl("yonetici")(self.varlik_sil), methods=["POST"]),
            R("/kullanicilar", pnl("yonetici")(self.kullanicilar)),
            R("/kullanicilar/yeni", pnl("yonetici")(self.kullanici_yeni), methods=["POST"]),
            R("/kullanicilar/parola", pnl()(self.parola), methods=["POST"]),
            R("/kullanicilar/{id:int}/degistir", pnl("yonetici")(self.kullanici_degistir), methods=["POST"]),
            R("/denetim", pnl("yonetici")(self.denetim)),
            R("/mcp-baglanti", pnl()(self.mcp_baglanti)),
            R("/mcp-baglanti/yeni", pnl()(self.mcp_anahtar_yeni), methods=["POST"]),
            R("/mcp-baglanti/{id:int}/iptal", pnl()(self.mcp_anahtar_iptal), methods=["POST"]),
        ]
        panel = GuvenlikBasliklari(Starlette(routes=rotalar))
        if not self.ayarlar.getbool("MCP", "aktif"):
            return panel
        import merkez_mcp

        mcp_uygulama = merkez_mcp.MerkezMCP(self)

        async def yonlendirici(scope, receive, send):
            """'/mcp' → MCP sunucusu (yaşam döngüsü dahil), diğer her şey → panel."""
            if scope["type"] == "lifespan" or (scope["type"] == "http" and scope["path"].rstrip("/") == "/mcp"):
                return await mcp_uygulama(scope, receive, send)
            return await panel(scope, receive, send)

        log.info("MCP uç noktası etkin: /mcp (kişisel veri paylaşımı: %s)",
                 "açık" if self.ayarlar.getbool("MCP", "kisisel_veri_paylas") else "kapalı")
        return yonlendirici

    def calistir(self):
        import uvicorn

        sifre = self.ilk_yonetici()
        if sifre:
            print("\n" + "=" * 60 + f"\n İLK YÖNETİCİ HESABI OLUŞTURULDU\n Kullanıcı: admin\n Parola   : {sifre}\n"
                  f" (Ayrıca: {os.path.join(self.db.klasor, 'ilk_yonetici_parolasi.txt')})\n" + "=" * 60 + "\n")
        threading.Thread(target=self.arka_plan, daemon=True, name="arka_plan").start()
        host, port = self.ayarlar.get("MERKEZ", "adres") or "0.0.0.0", self.ayarlar.getint("MERKEZ", "port")
        cert, key = self.ayarlar.yol("MERKEZ", "ssl_sertifika"), self.ayarlar.yol("MERKEZ", "ssl_anahtar")
        log.info("Alamount RPA Kontrol Merkezi v%s: %s://%s:%s  (veri: %s)", marka.SURUM, "https" if cert else "http", host, port, self.db.klasor)
        if not cert:
            log.warning("HTTPS kapalı: robot anahtarları ve varlıklar ağda şifresiz gider. "
                        "[MERKEZ] ssl_sertifika / ssl_anahtar ayarlarını kullanın.")
        uvicorn.run(self.uygulama(), host=host, port=port, log_config=None, access_log=False,
                    ssl_certfile=cert or None, ssl_keyfile=key or None)


def calistir(ayarlar):
    Merkez(ayarlar).calistir()


def sifre_sifirla(ayarlar, kullanici):
    m = Merkez(ayarlar)
    u = m.db.tek("SELECT id FROM kullanicilar WHERE ad=?", (kullanici,))
    sifre = secrets.token_urlsafe(12)
    if u:
        m.db.kullanici_sifre(u["id"], sifre)
        m.db.yaz("UPDATE kullanicilar SET aktif=1 WHERE id=?", (u["id"],))
    else:
        m.db.kullanici_ekle(kullanici, sifre, "yonetici")
    m.db.denetle("komut_satiri", "parola_sifirla", kullanici)
    return sifre


def robot_olustur(ayarlar, ad):
    """Komut satırından robot ekler (varsa anahtarını yeniler) ve anahtarı döner."""
    if not re.match(r"^[A-Za-z0-9_.\-]{1,60}$", ad):
        raise ValueError("Robot adı yalnızca harf, rakam, _ . - içerebilir")
    db = Veritabani(ayarlar.yol("MERKEZ", "veri_klasoru", olustur=True))
    r = db.tek("SELECT id FROM robotlar WHERE ad=?", (ad,))
    anahtar = db.robot_anahtar_yenile(r["id"]) if r else db.robot_ekle(ad, "komut satırı")
    db.denetle("komut_satiri", "robot_anahtar", ad)
    return anahtar


def is_olustur(ayarlar, surec, robot="", degiskenler=(), max_deneme=1, bekle_dk=0):
    """Komut satırından iş başlatır. bekle_dk>0 ise bitmesini bekler; çıkış kodu: 0 başarılı, 1 değil."""
    db = Veritabani(ayarlar.yol("MERKEZ", "veri_klasoru", olustur=True))
    surecler.komut(surec, list(degiskenler), ayarlar.yol("ROBOT", "gorev_klasoru"))
    is_id = db.is_ekle(surec, list(degiskenler), robot, max_deneme=max_deneme, olusturan="komut_satiri")
    print(f"İş #{is_id} kuyruğa alındı ({surec})")
    if not bekle_dk:
        return 0
    son = time.time() + bekle_dk * 60
    while time.time() < son:
        j = db.tek("SELECT durum, robot, ozet FROM isler WHERE id=?", (is_id,))
        if j["durum"] in ("basarili", "basarisiz", "iptal"):
            print(f"İş #{is_id}: {j['durum']} (robot {j['robot']}) {j['ozet']}")
            return 0 if j["durum"] == "basarili" else 1
        time.sleep(2)
    print(f"İş #{is_id}: {bekle_dk} dk içinde bitmedi")
    return 2


def mcp_anahtari_olustur(ayarlar, kullanici, ad="komut satırı"):
    """Komut satırından bir kullanıcıya MCP anahtarı üretir (panel kullanılamıyorsa / betikle kurulum)."""
    db = Veritabani(ayarlar.yol("MERKEZ", "veri_klasoru", olustur=True))
    k = db.tek("SELECT id FROM kullanicilar WHERE ad=? AND aktif=1", (kullanici,))
    if not k:
        raise SystemExit(f"Kullanıcı bulunamadı ya da pasif: {kullanici}")
    anahtar = db.api_anahtari_olustur(k["id"], ad)
    db.denetle("komut_satiri", "mcp_anahtar_olustur", kullanici)
    return anahtar
