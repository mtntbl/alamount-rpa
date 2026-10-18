# -*- coding: utf-8 -*-
"""
Kontrol Merkezi istemcisi (robot tarafı). Ajan, kuyruk işleri ve Robot görevleri kullanır.
Bağlantı bilgisi config.ini [AJAN] bölümünden ya da ajanın alt süreçlere verdiği ortam değişkenlerinden gelir:
  ALAMOUNT_MERKEZ_URL, ALAMOUNT_ROBOT_ADI, ALAMOUNT_ROBOT_ANAHTARI, ALAMOUNT_IS_ID, ALAMOUNT_CA_DOSYASI, ALAMOUNT_SSL_DOGRULA
"""

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request


class MerkezHatasi(Exception):
    def __init__(self, mesaj, kod=None):
        super().__init__(mesaj)
        self.kod = kod


class MerkezIstemci:
    def __init__(self, url, robot_adi, anahtar, ca_dosyasi="", ssl_dogrula=True, zaman_asimi=30):
        if not (url and robot_adi and anahtar):
            raise MerkezHatasi("Merkez bağlantısı ayarlı değil ([AJAN] merkez_url, robot_adi, robot_anahtari)")
        self.url = url.rstrip("/")
        self.robot_adi = robot_adi
        self._yetki = f"Bearer {robot_adi}:{anahtar}"
        self.zaman_asimi = zaman_asimi
        self.ctx = None
        if self.url.startswith("https"):
            self.ctx = ssl.create_default_context(cafile=ca_dosyasi or None)
            if not ssl_dogrula:
                self.ctx.check_hostname = False
                self.ctx.verify_mode = ssl.CERT_NONE
        self.is_id = int(os.environ["ALAMOUNT_IS_ID"]) if os.environ.get("ALAMOUNT_IS_ID", "").isdigit() else None

    @classmethod
    def ayarlardan(cls, ayarlar=None):
        """Önce ortam değişkenleri (ajanın başlattığı alt süreç), sonra config.ini [AJAN]."""
        env = os.environ
        if env.get("ALAMOUNT_MERKEZ_URL"):
            return cls(env["ALAMOUNT_MERKEZ_URL"], env.get("ALAMOUNT_ROBOT_ADI", ""), env.get("ALAMOUNT_ROBOT_ANAHTARI", ""),
                       env.get("ALAMOUNT_CA_DOSYASI", ""), env.get("ALAMOUNT_SSL_DOGRULA", "1") != "0")
        if ayarlar is None:
            raise MerkezHatasi("Merkez bağlantısı yok")
        return cls(ayarlar.cp.get("AJAN", "merkez_url", fallback="").strip(),
                   ayarlar.cp.get("AJAN", "robot_adi", fallback="").strip(),
                   ayarlar.cp.get("AJAN", "robot_anahtari", fallback="").strip() or env.get("ALAMOUNT_ROBOT_ANAHTARI", ""),
                   ayarlar.yol("AJAN", "ca_dosyasi"), ayarlar.getbool("AJAN", "ssl_dogrula"))

    def ortam(self):
        """Alt süreçlere aktarılacak ortam değişkenleri."""
        return {"ALAMOUNT_MERKEZ_URL": self.url, "ALAMOUNT_ROBOT_ADI": self.robot_adi,
                "ALAMOUNT_ROBOT_ANAHTARI": self._yetki.split(":", 1)[1],
                "ALAMOUNT_SSL_DOGRULA": "1" if (self.ctx is None or self.ctx.verify_mode != ssl.CERT_NONE) else "0"}

    # ------------------------------------------------------------------ HTTP
    def istek(self, yontem, yol, veri=None, ham=None, icerik_turu="application/json", deneme=3):
        govde = ham if ham is not None else (json.dumps(veri).encode() if veri is not None else b"")
        son_hata = None
        for i in range(deneme):
            req = urllib.request.Request(self.url + yol, data=govde if yontem != "GET" else None, method=yontem,
                                         headers={"Authorization": self._yetki, "Content-Type": icerik_turu})
            try:
                with urllib.request.urlopen(req, timeout=self.zaman_asimi, context=self.ctx) as r:
                    if r.status == 204:
                        return None
                    icerik = r.read()
                    return json.loads(icerik) if icerik else None
            except urllib.error.HTTPError as e:
                try:
                    mesaj = json.loads(e.read()).get("hata", e.reason)
                except Exception:
                    mesaj = e.reason
                if e.code < 500:
                    raise MerkezHatasi(f"Merkez: {mesaj} (HTTP {e.code})", e.code)
                son_hata = MerkezHatasi(f"Merkez: {mesaj} (HTTP {e.code})", e.code)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                son_hata = MerkezHatasi(f"Merkeze ulaşılamıyor: {getattr(e, 'reason', e)}")
            time.sleep(min(2 ** i, 10))
        raise son_hata

    # ------------------------------------------------------------------ API
    def nabiz(self, makine, surum, calisan_is, oturum=""):
        return self.istek("POST", "/api/nabiz", {"makine": makine, "surum": surum, "calisan_is": calisan_is,
                                                 "oturum": oturum}, deneme=1)

    def is_al(self):
        return self.istek("POST", "/api/is/al", {}, deneme=1)

    def is_log(self, is_id, metin):
        return self.istek("POST", f"/api/is/{is_id}/log", ham=metin.encode("utf-8"), icerik_turu="text/plain")

    def is_rapor(self, is_id, dosya_yolu, ad=None):
        with open(dosya_yolu, "rb") as f:
            ham = f.read()
        q = urllib.parse.quote(ad or os.path.basename(dosya_yolu))
        return self.istek("POST", f"/api/is/{is_id}/rapor?ad={q}", ham=ham, icerik_turu="application/octet-stream")

    def is_bitir(self, is_id, basarili, cikis_kodu, ozet="", iptal=False):
        return self.istek("POST", f"/api/is/{is_id}/bitir",
                          {"basarili": basarili, "cikis_kodu": cikis_kodu, "ozet": ozet, "iptal": iptal}, deneme=6)

    def kuyruga_ekle(self, kuyruk, referans, veri=None, imza="", oncelik=5, max_deneme=3):
        q = urllib.parse.quote(kuyruk, safe="")
        return self.istek("POST", f"/api/kuyruk/{q}/ekle", {"referans": referans, "veri": veri or {}, "imza": imza,
                                                             "oncelik": oncelik, "max_deneme": max_deneme})

    def kuyruktan_al(self, kuyruk):
        q = urllib.parse.quote(kuyruk, safe="")
        return self.istek("POST", f"/api/kuyruk/{q}/al", {"is_id": self.is_id})

    def oge_bitir(self, oge_id, durum, sonuc=None, hata=""):
        return self.istek("POST", f"/api/kuyruk/oge/{oge_id}/bitir",
                          {"durum": durum, "sonuc": sonuc or {}, "hata": hata}, deneme=6)

    def varlik(self, ad):
        return self.istek("GET", f"/api/varlik/{urllib.parse.quote(ad, safe='')}")


def varlik_cozucu_kur(ayarlar=None):
    """config.ini'deki 'varlik:AD' değerlerinin merkezden çözülmesini sağlar (bağlantı varsa)."""
    import pca_analiz

    try:
        ist = MerkezIstemci.ayarlardan(ayarlar)
    except MerkezHatasi:
        return None
    onbellek = {}

    def coz(ad, alan):
        if ad not in onbellek:
            onbellek[ad] = ist.varlik(ad)
        v = onbellek[ad]
        return v["kullanici_adi"] if alan == "kullanici" else v["deger"]

    pca_analiz.VARLIK_COZUCU = coz
    return ist
