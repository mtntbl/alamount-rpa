# -*- coding: utf-8 -*-
"""
Merkezden başlatılabilecek süreçlerin kataloğu (beyaz liste).
Ajan yalnızca buradaki süreçleri çalıştırır; keyfi komut çalıştırılamaz.
Robot görevlerine yalnızca 'DEGISKEN:deger' biçiminde değişken geçilebilir.
"""

import glob
import os
import re

SABIT_SURECLER = {
    "pca": ("PCA analizi (input klasörü)", ["pca", "--once"]),
    "ise-giris": ("İşe giriş — klasörü tek robotla işle", ["ise-giris"]),
    "ise-giris-dagit": ("İşe giriş — PDF'leri kuyruğa ekle (dağıtıcı)", ["kuyruk", "ise-giris-dagit"]),
    "ise-giris-isle": ("İşe giriş — kuyruktan al ve işle (çalışan)", ["kuyruk", "ise-giris-isle"]),
}
DEGISKEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}:[^\r\n]{0,500}$")
GOREV_ADI = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")


def katalog(gorev_klasoru):
    """[(surec_id, açıklama)] — panelde seçim listesi için."""
    lst = [(k, v[0]) for k, v in SABIT_SURECLER.items()]
    for p in sorted(glob.glob(os.path.join(gorev_klasoru, "*.robot"))):
        ad = os.path.splitext(os.path.basename(p))[0]
        lst.append((f"robot:{ad}", f"Robot görevi: {ad}"))
    return lst


def komut(surec, argumanlar, gorev_klasoru):
    """Süreci AlamountRPA.exe komut satırı argümanlarına çevirir; geçersizse ValueError."""
    argumanlar = [str(a) for a in (argumanlar or []) if str(a).strip()]
    for a in argumanlar:
        if not DEGISKEN.match(a):
            raise ValueError(f"Geçersiz değişken (AD:değer olmalı): {a[:60]}")
    if surec in SABIT_SURECLER:
        if argumanlar:
            raise ValueError(f"'{surec}' süreci değişken almaz")
        return list(SABIT_SURECLER[surec][1])
    if surec.startswith("robot:"):
        ad = surec[6:]
        if not GOREV_ADI.match(ad) or not os.path.isfile(os.path.join(gorev_klasoru, ad + ".robot")):
            raise ValueError(f"Robot görevi bulunamadı: {ad}")
        cmd = ["robot", ad]
        for a in argumanlar:
            cmd += ["--variable", a]
        return cmd
    raise ValueError(f"Bilinmeyen süreç: {surec}")
