# -*- coding: utf-8 -*-
"""
Robot ajanı — robot makinesinde sürekli çalışır:  AlamountRPA.exe ajan
  * Merkeze düzenli nabız gönderir (çevrimiçi/meşgul, iptal istekleri)
  * Boştayken merkezden iş alır, işi beyaz listeden (surecler.py) geçirip alt süreç olarak çalıştırır
  * Çıktıyı canlı olarak merkeze aktarır, bitince Robot Framework raporlarını yükler
  * İptal ve zaman aşımında süreç ağacını sonlandırır
  * Merkeze ulaşılamazsa bekler ve yeniden bağlanır; sonucu kaybetmez
Masaüstü (Mikro, Not Defteri) görevleri için ajan, AÇIK BİR KULLANICI OTURUMUNDA çalışmalıdır.
"""

import logging
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time

import surecler
from merkez_istemci import MerkezHatasi, MerkezIstemci

log = logging.getLogger("alamount")
RAPOR_DESENI = re.compile(r"Rapor:\s*(.+?log\.html)\s*$")


def _exe_komutu():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "alamount_rpa.py")]


def _agaci_sonlandir(proc):
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except Exception as e:
        log.warning("Süreç sonlandırılamadı: %s", e)
        proc.kill()


class Ajan:
    def __init__(self, ayarlar, surum):
        self.ayarlar = ayarlar
        self.surum = surum
        self.istemci = MerkezIstemci.ayarlardan(ayarlar)
        self.nabiz_sn = max(5, ayarlar.getint("AJAN", "nabiz_sn"))
        self.gorev_klasoru = ayarlar.yol("ROBOT", "gorev_klasoru")
        self.makine = socket.gethostname()
        self.calisan = None  # {"id", "proc", "iptal", "baslama", "max_sure"}
        self._dur = threading.Event()
        self._kilit = threading.Lock()
        self.cikis_kodu = 0

    # ------------------------------------------------------------------ nabız
    def _nabiz_dongusu(self):
        bagli = None
        while not self._dur.is_set():
            with self._kilit:
                is_id = self.calisan["id"] if self.calisan else None
            try:
                yanit = self.istemci.nabiz(self.makine, self.surum, is_id) or {}
                if bagli is not True:
                    log.info("Merkeze bağlanıldı: %s (robot %s)", self.istemci.url, self.istemci.robot_adi)
                bagli = True
                with self._kilit:
                    if self.calisan and self.calisan["id"] in (yanit.get("iptal") or []) and not self.calisan["iptal"]:
                        log.warning("İş #%s için iptal isteği alındı", self.calisan["id"])
                        self.calisan["iptal"] = True
                        _agaci_sonlandir(self.calisan["proc"])
            except MerkezHatasi as e:
                if e.kod == 401:
                    log.error("Merkez robotu reddetti (ad/anahtar hatalı ya da robot pasif). Ajan duruyor.")
                    self.cikis_kodu = 1
                    self._dur.set()
                    return
                if bagli is not False:
                    log.warning("%s — yeniden denenecek", e)
                bagli = False
            self._dur.wait(self.nabiz_sn)

    # ------------------------------------------------------------------ iş
    def _isi_calistir(self, j):
        is_id = j["id"]
        try:
            cmd = surecler.komut(j["surec"], j.get("argumanlar") or [], self.gorev_klasoru)
        except ValueError as e:
            log.error("İş #%s reddedildi: %s", is_id, e)
            self._bitir(is_id, False, None, f"Reddedildi: {e}")
            return
        tam = _exe_komutu() + ["--config", self.ayarlar.path] + cmd
        ortam = dict(os.environ, **self.istemci.ortam(), ALAMOUNT_IS_ID=str(is_id), PYTHONIOENCODING="utf-8",
                     PYTHONUTF8="1")
        ca = self.ayarlar.yol("AJAN", "ca_dosyasi")
        if ca:
            ortam["ALAMOUNT_CA_DOSYASI"] = ca
        log.info("İş #%s başlıyor (deneme %s): %s", is_id, j.get("deneme"), " ".join(cmd))
        ek = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        proc = subprocess.Popen(tam, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=ortam, cwd=os.path.dirname(self.ayarlar.path), **ek)
        with self._kilit:
            self.calisan = {"id": is_id, "proc": proc, "iptal": False, "zaman_asimi": False}
        satirlar = queue.Queue()
        raporlar = []

        def oku():
            for ham in iter(proc.stdout.readline, b""):
                satir = ham.decode("utf-8", "replace")
                satirlar.put(satir)
                m = RAPOR_DESENI.search(satir)
                if m:
                    raporlar.append(m.group(1).strip())
            proc.stdout.close()

        okuyucu = threading.Thread(target=oku, daemon=True)
        okuyucu.start()
        baslama = time.time()
        max_sn = int(j.get("max_sure_dk") or 120) * 60
        tampon = [f"[{time.strftime('%H:%M:%S')}] {self.istemci.robot_adi}@{self.makine}: {' '.join(cmd)}\n"]
        son_gonderim = 0
        while True:
            bitti = proc.poll() is not None and not okuyucu.is_alive()
            try:
                while True:
                    tampon.append(satirlar.get_nowait())
            except queue.Empty:
                pass
            if tampon and (bitti or time.time() - son_gonderim > 3 or sum(map(len, tampon)) > 32000):
                self._log_gonder(is_id, "".join(tampon))
                tampon, son_gonderim = [], time.time()
            if bitti:
                break
            if time.time() - baslama > max_sn and not self.calisan["zaman_asimi"]:
                log.error("İş #%s zaman aşımı (%s dk)", is_id, max_sn // 60)
                self.calisan["zaman_asimi"] = True
                _agaci_sonlandir(proc)
            time.sleep(0.5)

        kod = proc.returncode
        for r in raporlar:
            for ad in ("log.html", "report.html"):
                yol = os.path.join(os.path.dirname(r), ad)
                if os.path.isfile(yol):
                    try:
                        self.istemci.is_rapor(is_id, yol, f"{os.path.basename(os.path.dirname(r))}_{ad}")
                    except MerkezHatasi as e:
                        log.warning("Rapor yüklenemedi: %s", e)
        with self._kilit:
            iptal, zaman_asimi = self.calisan["iptal"], self.calisan["zaman_asimi"]
            self.calisan = None
        sure = int(time.time() - baslama)
        if iptal:
            ozet = f"İptal edildi ({sure} sn)"
        elif zaman_asimi:
            ozet = f"Zaman aşımı: {max_sn // 60} dk"
        else:
            ozet = f"Çıkış kodu {kod} ({sure} sn)"
        log.info("İş #%s bitti: %s", is_id, ozet)
        self._bitir(is_id, kod == 0 and not iptal and not zaman_asimi, kod, ozet, iptal)

    def _log_gonder(self, is_id, metin):
        try:
            self.istemci.is_log(is_id, metin)
        except MerkezHatasi as e:
            log.warning("Log gönderilemedi: %s", e)

    def _bitir(self, is_id, basarili, kod, ozet, iptal=False):
        """Merkeze ulaşana kadar dener — sonuç kaybolmaz."""
        bekle = 5
        while not self._dur.is_set():
            try:
                self.istemci.is_bitir(is_id, basarili, kod, ozet, iptal)
                return
            except MerkezHatasi as e:
                if e.kod and 400 <= e.kod < 500:
                    log.error("İş #%s sonucu reddedildi: %s", is_id, e)
                    return
                log.warning("Sonuç gönderilemedi, %s sn sonra tekrar: %s", bekle, e)
                self._dur.wait(bekle)
                bekle = min(bekle * 2, 120)

    # ------------------------------------------------------------------ ana döngü
    def calistir(self):
        log.info("Alamount RPA robot ajanı başladı: %s → %s", self.istemci.robot_adi, self.istemci.url)
        threading.Thread(target=self._nabiz_dongusu, daemon=True, name="nabiz").start()
        try:
            while not self._dur.is_set():
                try:
                    j = self.istemci.is_al()
                except MerkezHatasi as e:
                    if e.kod == 401:
                        log.error("Merkez robotu reddetti (ad/anahtar hatalı ya da robot pasif). Ajan duruyor.")
                        self.cikis_kodu = 1
                        break
                    self._dur.wait(self.nabiz_sn)
                    continue
                if j:
                    self._isi_calistir(j)
                else:
                    self._dur.wait(5)
        except KeyboardInterrupt:
            log.info("Ajan durduruluyor")
            with self._kilit:
                if self.calisan:
                    _agaci_sonlandir(self.calisan["proc"])
        self._dur.set()
        return self.cikis_kodu


def calistir(ayarlar, surum):
    try:
        return Ajan(ayarlar, surum).calistir()
    except MerkezHatasi as e:
        log.error("%s", e)
        return 1
