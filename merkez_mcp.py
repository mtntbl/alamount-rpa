# -*- coding: utf-8 -*-
"""
Kontrol Merkezi MCP uç noktası (/mcp) — Microsoft Copilot (Copilot Studio, GitHub Copilot) ve
Claude Desktop gibi LLM istemcilerinin robotları yönetmesi için.

  * Taşıma: MCP "streamable HTTP" (resmi SDK; JSON yanıt, durumsuz).
  * Kimlik: kullanıcı başına MCP anahtarı — "Authorization: Bearer alm_..." ya da "X-API-Key: alm_...".
  * Yetki: LLM, anahtarın sahibinin rolüyle çalışır (izleyici / operator / yonetici); her çağrı denetime yazılır.
  * Gizlilik: [MCP] kisisel_veri_paylas = hayir iken TC maskelenir, ad soyad ve iş logları gönderilmez.
    Varlık kasası (parolalar) hiçbir rolde MCP'den okunamaz.
"""

import datetime as dt
import json
import logging
import os
import re

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

import marka
import merkez_panel as P
import surecler
from cron import Cron, gecerli_mi

log = logging.getLogger("alamount")
TC_DESENI = re.compile(r"(?<!\d)(\d{3})\d{6}(\d{2})(?!\d)")
OKUMA = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
YAZMA = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
IPTAL = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)


class YetkiHatasi(ToolError):
    """LLM'e mesajı aynen iletilen yetki hatası."""


def _zaman(ts):
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S") if ts else None


class MerkezMCP:
    def __init__(self, merkez):
        self.m = merkez
        self.db = merkez.db
        self.kisisel = merkez.ayarlar.getbool("MCP", "kisisel_veri_paylas")
        self.sunucu = self._sunucu_olustur()
        self.http = self.sunucu.streamable_http_app(
            streamable_http_path="/mcp", json_response=True, stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))

    # ------------------------------------------------------------------ yardımcılar
    def _maskele(self, metin):
        if self.kisisel or metin is None:
            return metin
        return TC_DESENI.sub(r"\1******\2", str(metin))

    def _kullanici(self, ctx: Context, rol="izleyici"):
        istek = ctx.request_context.request
        k = getattr(istek.state, "alamount_kullanici", None) if istek is not None else None
        if not k:
            raise YetkiHatasi("Kimlik doğrulanamadı")
        if not P.yetkili(k, rol):
            self.db.denetle(f"{k['ad']} (MCP)", "mcp_reddedildi", f"{rol} gerekli")
            raise YetkiHatasi(f"Bu işlem için '{rol}' rolü gerekir; sizin rolünüz '{k['rol']}'.")
        return k

    def _denetle(self, k, arac, detay=""):
        self.db.denetle(f"{k['ad']} (MCP)", f"mcp:{arac}", detay)

    @staticmethod
    def _js(veri):
        return json.dumps(veri, ensure_ascii=False, indent=1, default=str)

    def _is_ozet(self, j):
        return {"id": j["id"], "surec": j["surec"], "durum": j["durum"], "robot": j["robot"] or None,
                "hedef_robot": j["hedef_robot"] or "herhangi", "deneme": f'{j["deneme"]}/{j["max_deneme"]}',
                "olusturan": j["olusturan"], "olusturma": _zaman(j["olusturma"]), "baslama": _zaman(j["baslama"]),
                "bitis": _zaman(j["bitis"]), "ozet": self._maskele(j["ozet"]) or None,
                "panel": self.m.link(f"/isler/{j['id']}") or None}

    def _oge_ozet(self, o):
        try:
            sonuc = json.loads(o["sonuc"] or "{}")
        except ValueError:
            sonuc = {}
        if not self.kisisel:
            sonuc.pop("ad_soyad", None)
        for k, v in list(sonuc.items()):  # dosya yolları yalnızca adıyla
            if isinstance(v, str) and ("/" in v or "\\" in v):
                sonuc[k] = os.path.basename(v.replace("\\", "/"))
                if not self.kisisel:
                    sonuc[k] = self._maskele(re.sub(r" - .+? \(", " - … (", sonuc[k]))
        return {"id": o["id"], "referans": self._maskele(o["referans"]), "durum": o["durum"],
                "deneme": f'{o["deneme"]}/{o["max_deneme"]}', "robot": o["robot"] or None, "is_id": o["is_id"],
                "eklenme": _zaman(o["olusturma"]), "bitis": _zaman(o["bitis"]),
                "hata_turu": {"is": "iş kuralı", "sistem": "sistem"}.get(o["hata_turu"]) or None,
                "hata": self._maskele(o["hata"]) or None, "sonuc": sonuc or None}

    # ------------------------------------------------------------------ araçlar
    @staticmethod
    def _anlasilir(fn):
        """Doğrulama hatalarını (ValueError) LLM'in görebileceği ToolError mesajına çevirir."""
        import functools

        @functools.wraps(fn)
        def sar(*a, **k):
            try:
                return fn(*a, **k)
            except ValueError as e:
                raise ToolError(str(e)) from e
        return sar

    def _sunucu_olustur(self):
        s = MCPServer(
            name="alamount-rpa", title=marka.URUN, version=marka.SURUM,
            instructions=(
                f"{marka.URUN} Kontrol Merkezi. Robotlara iş verir, işlerin, kuyrukların ve zamanlamaların durumunu "
                "sorgular. Kullanıcının rolü dışındaki işlemler reddedilir. Süreç adlarını surecleri_listele ile al. "
                "İş kuralı hatası (örn. TC Puantaj'da yok) yeniden denemekle düzelmez; önce veriyi düzeltmek gerekir. "
                "Yanıtlarda maskelenmiş kişisel verileri açmaya çalışma."),
            website_url=self.m.panel_url or None)

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def durum_ozeti(ctx: Context) -> str:
            """Genel durum: robotların durumu, çalışan/bekleyen işler, bugünkü başarılı/başarısız işler ve kuyruk özeti."""
            k = self._kullanici(ctx)
            bugun = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
            say = lambda sql, p=(): self.db.tek(sql, p)["n"]  # noqa: E731
            esik = self.m.cevrimdisi_esik()
            robotlar = [{"ad": r["ad"], "durum": self.m._robot_durum(r, esik), "calisan_is": r["calisan_is"],
                         "windows_oturumu": r.get("oturum") or "bilinmiyor", "son_gorulme": _zaman(r["son_gorulme"])}
                        for r in self.db.sorgu("SELECT * FROM robotlar ORDER BY ad")]
            self._denetle(k, "durum_ozeti")
            return self._js({
                "urun": f"{marka.URUN} v{marka.SURUM}", "robotlar": robotlar,
                "calisan_is": say("SELECT COUNT(*) n FROM isler WHERE durum='calisiyor'"),
                "bekleyen_is": say("SELECT COUNT(*) n FROM isler WHERE durum='bekliyor'"),
                "bugun_basarili": say("SELECT COUNT(*) n FROM isler WHERE durum='basarili' AND bitis>=?", (bugun,)),
                "bugun_basarisiz": say("SELECT COUNT(*) n FROM isler WHERE durum='basarisiz' AND bitis>=?", (bugun,)),
                "kuyruklar": self.db.kuyruk_ozet()})

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def surecleri_listele(ctx: Context) -> str:
            """Başlatılabilecek süreçler (is_baslat ve zamanlama_ekle için 'surec' değerleri)."""
            k = self._kullanici(ctx)
            self._denetle(k, "surecleri_listele")
            return self._js([{"surec": a, "aciklama": b} for a, b in surecler.katalog(self.m.gorev_klasoru)])

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def isleri_listele(ctx: Context, durum: str = "", adet: int = 20) -> str:
            """Son işleri listeler. durum: bekliyor | calisiyor | basarili | basarisiz | iptal (boş = hepsi)."""
            k = self._kullanici(ctx)
            adet = max(1, min(int(adet), 100))
            if durum:
                isler = self.db.sorgu("SELECT * FROM isler WHERE durum=? ORDER BY id DESC LIMIT ?", (durum, adet))
            else:
                isler = self.db.sorgu("SELECT * FROM isler ORDER BY id DESC LIMIT ?", (adet,))
            self._denetle(k, "isleri_listele", durum)
            return self._js([self._is_ozet(j) for j in isler])

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def is_detayi(ctx: Context, is_id: int) -> str:
            """Bir işin ayrıntıları, işlediği kuyruk öğeleri ve (kişisel veri paylaşımı açıksa) logunun son kısmı."""
            k = self._kullanici(ctx)
            j = self.db.tek("SELECT * FROM isler WHERE id=?", (int(is_id),))
            if not j:
                return f"İş #{is_id} bulunamadı."
            d = self._is_ozet(j)
            d["degiskenler"] = json.loads(j["argumanlar"] or "[]")
            d["cikis_kodu"] = j["cikis_kodu"]
            d["kuyruk_ogeleri"] = [self._oge_ozet(o) for o in
                                   self.db.sorgu("SELECT * FROM kuyruk_ogeleri WHERE is_id=? ORDER BY id", (j["id"],))]
            d["log_son"] = (j["log"] or "")[-3000:] if self.kisisel else "(kişisel veri paylaşımı kapalı; log panelde)"
            self._denetle(k, "is_detayi", f"#{is_id}")
            return self._js(d)

        @s.tool(annotations=YAZMA)
        @self._anlasilir
        def is_baslat(ctx: Context, surec: str, robot: str = "", degiskenler: str = "", deneme_hakki: int = 1) -> str:
            """Yeni iş başlatır (operator). surec: surecleri_listele'deki değer. robot: boşsa uygun herhangi bir robot.
            degiskenler: Robot görevleri için her satıra bir 'AD:değer' (örn. KURU_CALISMA:evet)."""
            k = self._kullanici(ctx, "operator")
            dg = [x.strip() for x in str(degiskenler or "").replace(";", "\n").splitlines() if x.strip()]
            surecler.komut(surec, dg, self.m.gorev_klasoru)
            if robot and not self.db.tek("SELECT id FROM robotlar WHERE ad=? AND aktif=1", (robot,)):
                raise ValueError(f"Robot bulunamadı ya da pasif: {robot}")
            is_id = self.db.is_ekle(surec, dg, robot, 5, max(1, min(int(deneme_hakki), 10)), 120, f"{k['ad']} (MCP)")
            self._denetle(k, "is_baslat", {"is": is_id, "surec": surec, "robot": robot})
            return f"İş #{is_id} kuyruğa alındı ({surec}). Durumu is_detayi ile sorgulayabilirsiniz." + (
                f" Panel: {self.m.link(f'/isler/{is_id}')}" if self.m.panel_url else "")

        @s.tool(annotations=IPTAL)
        @self._anlasilir
        def is_iptal_et(ctx: Context, is_id: int) -> str:
            """Bekleyen ya da çalışan bir işi iptal eder (operator)."""
            k = self._kullanici(ctx, "operator")
            sonuc = self.db.is_iptal(int(is_id))
            self._denetle(k, "is_iptal_et", {"is": is_id, "sonuc": sonuc})
            return {None: f"İş #{is_id} bulunamadı.", "iptal": f"İş #{is_id} iptal edildi.",
                    "iptal_istendi": f"İş #{is_id} çalışıyor; iptal isteği robota iletildi."}.get(
                sonuc, f"İş #{is_id} zaten '{sonuc}' durumunda.")

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def kuyruk_ogeleri(ctx: Context, kuyruk: str = "ise_giris", durum: str = "", adet: int = 50) -> str:
            """Bir kuyruğun öğeleri. durum: yeni | isleniyor | basarili | basarisiz (boş = hepsi).
            Hata türü 'iş kuralı' olanlar veri düzeltilmeden yeniden işlenmemelidir."""
            k = self._kullanici(ctx)
            adet = max(1, min(int(adet), 200))
            sql, p = "SELECT * FROM kuyruk_ogeleri WHERE kuyruk=?", [kuyruk]
            if durum:
                sql += " AND durum=?"
                p.append(durum)
            ogeler = self.db.sorgu(sql + " ORDER BY id DESC LIMIT ?", p + [adet])
            self._denetle(k, "kuyruk_ogeleri", {"kuyruk": kuyruk, "durum": durum})
            return self._js({"ozet": [q for q in self.db.kuyruk_ozet() if q["kuyruk"] == kuyruk],
                             "ogeler": [self._oge_ozet(o) for o in ogeler]})

        @s.tool(annotations=YAZMA)
        @self._anlasilir
        def ogeyi_yeniden_isle(ctx: Context, oge_id: int) -> str:
            """Başarısız (ya da başarılı) bir kuyruk öğesini yeniden kuyruğa alır (operator)."""
            k = self._kullanici(ctx, "operator")
            n = self.db.oge_yeniden(int(oge_id))
            self._denetle(k, "ogeyi_yeniden_isle", {"oge": oge_id})
            return f"Öğe #{oge_id} yeniden kuyruğa alındı." if n else f"Öğe #{oge_id} bulunamadı ya da şu an işleniyor."

        @s.tool(annotations=OKUMA)
        @self._anlasilir
        def zamanlamalari_listele(ctx: Context) -> str:
            """Zamanlanmış işler (cron), durumları ve sonraki çalışma zamanları."""
            k = self._kullanici(ctx)
            self._denetle(k, "zamanlamalari_listele")
            return self._js([{"id": z["id"], "ad": z["ad"], "surec": z["surec"], "cron": z["cron"],
                              "robot": z["hedef_robot"] or "herhangi", "aktif": bool(z["aktif"]),
                              "sonraki": _zaman(z["sonraki"]) if z["aktif"] else None,
                              "son_calisma": _zaman(z["son_calisma"])}
                             for z in self.db.sorgu("SELECT * FROM zamanlamalar ORDER BY ad")])

        @s.tool(annotations=YAZMA)
        @self._anlasilir
        def zamanlama_ekle(ctx: Context, ad: str, surec: str, cron: str, robot: str = "", degiskenler: str = "",
                           deneme_hakki: int = 2) -> str:
            """Zamanlanmış iş ekler (yonetici). cron: 'dakika saat gün ay haftanın-günü' yerel saatle,
            örn. '30 8 * * 1-5' hafta içi 08:30, '*/15 * * * *' 15 dakikada bir, '@gunluk'."""
            k = self._kullanici(ctx, "yonetici")
            if not gecerli_mi(cron):
                raise ValueError(f"Geçersiz cron ifadesi: {cron}")
            dg = [x.strip() for x in str(degiskenler or "").replace(";", "\n").splitlines() if x.strip()]
            surecler.komut(surec, dg, self.m.gorev_klasoru)
            zid = self.db.zamanlama_ekle(ad.strip()[:80] or surec, surec, cron, dg, robot,
                                         max(1, min(int(deneme_hakki), 10)), f"{k['ad']} (MCP)")
            self._denetle(k, "zamanlama_ekle", {"id": zid, "surec": surec, "cron": cron})
            ilk = Cron(cron).sonraki().strftime("%d.%m.%Y %H:%M")
            return f"Zamanlama #{zid} eklendi ({surec}, {cron}). İlk çalışma: {ilk}."

        @s.tool(annotations=YAZMA)
        @self._anlasilir
        def zamanlama_durdur_baslat(ctx: Context, zamanlama_id: int) -> str:
            """Bir zamanlamayı durdurur; durmuşsa yeniden başlatır (operator)."""
            k = self._kullanici(ctx, "operator")
            z = self.db.tek("SELECT * FROM zamanlamalar WHERE id=?", (int(zamanlama_id),))
            if not z:
                return f"Zamanlama #{zamanlama_id} bulunamadı."
            aktif = 0 if z["aktif"] else 1
            sonraki = Cron(z["cron"]).sonraki().timestamp() if aktif else z["sonraki"]
            self.db.yaz("UPDATE zamanlamalar SET aktif=?, sonraki=? WHERE id=?", (aktif, sonraki, z["id"]))
            self._denetle(k, "zamanlama_" + ("baslat" if aktif else "durdur"), z["ad"])
            return f"'{z['ad']}' {'başlatıldı' if aktif else 'durduruldu'}."

        return s

    # ------------------------------------------------------------------ ASGI (kimlik doğrulama)
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.http(scope, receive, send)
        basliklar = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        anahtar = basliklar.get("x-api-key", "").strip()
        yetki = basliklar.get("authorization", "")
        if not anahtar and yetki.lower().startswith("bearer "):
            anahtar = yetki[7:].strip()
        kullanici = self.db.api_anahtari_dogrula(anahtar)
        if not kullanici:
            govde = json.dumps({"jsonrpc": "2.0", "id": None,
                                "error": {"code": -32001, "message": "Geçersiz ya da eksik MCP anahtarı"}}).encode()
            await send({"type": "http.response.start", "status": 401, "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="Alamount RPA", error="invalid_token"')]})
            await send({"type": "http.response.body", "body": govde})
            return
        scope.setdefault("state", {})["alamount_kullanici"] = {"id": kullanici["id"], "ad": kullanici["ad"],
                                                                 "rol": kullanici["rol"]}
        await self.http(scope, receive, send)
