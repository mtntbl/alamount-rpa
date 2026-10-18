# -*- coding: utf-8 -*-
"""Kontrol Merkezi bildirimleri: e-posta (SMTP) ve Microsoft Teams (gelen webhook, Adaptive Card)."""

import json
import logging
import os
import smtplib
import ssl
import threading
import urllib.request
from email.message import EmailMessage

import pca_analiz

log = logging.getLogger("alamount")

OLAY_ADLARI = {
    "is_basarisiz": "İş başarısız",
    "is_basarili": "İş tamamlandı",
    "robot_cevrimdisi": "Robot çevrimdışı",
    "robot_cevrimici": "Robot yeniden çevrimiçi",
    "oge_basarisiz": "Kuyruk öğesi başarısız",
}
RENK = {"is_basarisiz": "attention", "robot_cevrimdisi": "attention", "oge_basarisiz": "warning",
        "is_basarili": "good", "robot_cevrimici": "good"}


class Bildirici:
    def __init__(self, ayarlar):
        self.ayarlar = ayarlar
        self.olaylar = {o.strip() for o in ayarlar.get("BILDIRIM", "olaylar").split(",") if o.strip()}

    def gonder(self, olay, baslik, alanlar, baglanti=""):
        """Arka planda gönderir; hata olursa yalnızca loglar."""
        if olay not in self.olaylar:
            return
        threading.Thread(target=self._gonder, args=(olay, baslik, alanlar, baglanti), daemon=True).start()

    def _gonder(self, olay, baslik, alanlar, baglanti):
        if self.ayarlar.getbool("BILDIRIM", "eposta"):
            try:
                self._eposta(olay, baslik, alanlar, baglanti)
            except Exception as e:
                log.error("Bildirim e-postası gönderilemedi: %s", e)
        url = self.ayarlar.get("BILDIRIM", "teams_webhook")
        if url:
            try:
                self._teams(url, olay, baslik, alanlar, baglanti)
            except Exception as e:
                log.error("Teams bildirimi gönderilemedi: %s", e)

    def _eposta(self, olay, baslik, alanlar, baglanti):
        a = self.ayarlar
        alicilar = pca_analiz.split_list(a.get("BILDIRIM", "eposta_alicilar") or a.get("EMAIL", "alicilar"))
        if not alicilar:
            return
        msg = EmailMessage()
        msg["From"] = a.get("EMAIL", "gonderen") or a.get("EMAIL", "kullanici")
        msg["To"] = ", ".join(alicilar)
        msg["Subject"] = f"[Alamount RPA] {OLAY_ADLARI.get(olay, olay)}: {baslik}"
        govde = "\n".join(f"{k}: {v}" for k, v in alanlar.items())
        msg.set_content(f"{baslik}\n\n{govde}\n\n{baglanti}".strip())
        host, port = a.get("EMAIL", "smtp_sunucu"), a.getint("EMAIL", "smtp_port")
        guv = a.get("EMAIL", "guvenlik").lower()
        ctx = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) if guv == "ssl" else smtplib.SMTP(host, port, timeout=30)
        with smtp:
            if guv == "starttls":
                smtp.starttls(context=ctx)
            kul = a.get("EMAIL", "kullanici")
            sif = a.get("EMAIL", "sifre") or os.environ.get("ALAMOUNT_SMTP_SIFRE", "")
            if kul and sif:
                smtp.login(kul, sif)
            smtp.send_message(msg)

    def _teams(self, url, olay, baslik, alanlar, baglanti):
        kart = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "type": "AdaptiveCard", "version": "1.4",
            "body": [
                {"type": "TextBlock", "text": "ALAMOUNT RPA", "size": "Small", "weight": "Bolder",
                 "color": "accent", "spacing": "None"},
                {"type": "TextBlock", "text": OLAY_ADLARI.get(olay, olay), "weight": "Bolder", "size": "Medium",
                 "color": RENK.get(olay, "default")},
                {"type": "TextBlock", "text": baslik, "wrap": True},
                {"type": "FactSet", "facts": [{"title": str(k), "value": str(v)[:500]} for k, v in alanlar.items()]},
            ],
        }
        if baglanti:
            kart["actions"] = [{"type": "Action.OpenUrl", "title": "Panelde aç", "url": baglanti}]
        govde = {"type": "message", "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive", "contentUrl": None, "content": kart}]}
        req = urllib.request.Request(url, data=json.dumps(govde).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            if r.status >= 300:
                raise RuntimeError(f"HTTP {r.status}")
