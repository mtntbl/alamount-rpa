# -*- coding: utf-8 -*-
"""
5 alanlı cron ifadesi (dakika saat gün ay haftanın-günü), yerel saatle.
Desteklenen: *  */n  a-b  a-b/n  a,b,c   (haftanın günü: 0 veya 7 = Pazar, 1 = Pazartesi)
Kısayollar: @saatlik @gunluk @haftalik @aylik
Örnekler:  "*/15 * * * *"  her 15 dk   |   "30 8 * * 1-5"  hafta içi 08:30
"""

import datetime as dt

KISAYOLLAR = {
    "@saatlik": "0 * * * *", "@hourly": "0 * * * *",
    "@gunluk": "0 0 * * *", "@daily": "0 0 * * *",
    "@haftalik": "0 0 * * 1", "@weekly": "0 0 * * 1",
    "@aylik": "0 0 1 * *", "@monthly": "0 0 1 * *",
}
ARALIKLAR = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]


def _alan(metin, alt, ust):
    degerler = set()
    for parca in metin.split(","):
        adim = 1
        if "/" in parca:
            parca, a = parca.split("/", 1)
            adim = int(a)
            if adim <= 0:
                raise ValueError("adım 0 olamaz")
        if parca == "*":
            bas, son = alt, ust
        elif "-" in parca:
            b, s = parca.split("-", 1)
            bas, son = int(b), int(s)
        else:
            bas = son = int(parca)
            if adim > 1:
                son = ust
        if bas < alt or son > ust or bas > son:
            raise ValueError(f"'{parca}' {alt}-{ust} aralığında değil")
        degerler.update(range(bas, son + 1, adim))
    return degerler


class Cron:
    def __init__(self, ifade):
        ifade = KISAYOLLAR.get(ifade.strip().lower(), ifade.strip())
        alanlar = ifade.split()
        if len(alanlar) != 5:
            raise ValueError("Cron ifadesi 5 alan olmalı: dakika saat gün ay haftanın-günü")
        self.ifade = ifade
        self.dk, self.sa, self.gun, self.ay, hg = (_alan(a, *r) for a, r in zip(alanlar, ARALIKLAR))
        self.hg = {0 if d == 7 else d for d in hg}
        self._gun_kisitli = alanlar[2] != "*"
        self._hg_kisitli = alanlar[4] != "*"

    def _gun_uyar(self, t):
        hg = (t.weekday() + 1) % 7  # Python: Pzt=0 → cron: Pzt=1, Paz=0
        g, h = t.day in self.gun, hg in self.hg
        if self._gun_kisitli and self._hg_kisitli:
            return g or h  # klasik cron davranışı
        return g and h

    def sonraki(self, sonra=None):
        """'sonra'dan (dahil değil) sonraki ilk çalışma zamanı (naive yerel datetime)."""
        t = (sonra or dt.datetime.now()).replace(second=0, microsecond=0) + dt.timedelta(minutes=1)
        sinir = t + dt.timedelta(days=366 * 5)
        while t < sinir:
            if t.month not in self.ay:
                t = (t.replace(day=1, hour=0, minute=0) + dt.timedelta(days=32)).replace(day=1)
                continue
            if not self._gun_uyar(t):
                t = t.replace(hour=0, minute=0) + dt.timedelta(days=1)
                continue
            if t.hour not in self.sa:
                t = t.replace(minute=0) + dt.timedelta(hours=1)
                continue
            if t.minute not in self.dk:
                t += dt.timedelta(minutes=1)
                continue
            return t
        raise ValueError("Bu cron ifadesi hiçbir zaman çalışmıyor")


def gecerli_mi(ifade):
    try:
        Cron(ifade).sonraki()
        return True
    except Exception:
        return False
