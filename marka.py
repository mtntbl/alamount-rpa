# -*- coding: utf-8 -*-
"""Alamount RPA — ürün adı, sürüm, kurumsal renkler ve logo dosyaları."""

import os
import sys

URUN = "Alamount RPA"
SIRKET = "Alamount"
SURUM = "3.3.0"
EXE = "AlamountRPA.exe"

LACIVERT = "#022351"  # logodaki "Alamount"
MAVI = "#04BAF3"      # logodaki "RPA"


def kaynak(ad):
    """marka/ klasöründeki dosyanın yolu (kaynak koddan ya da paketlenmiş exe'den)."""
    kok = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(kok, "marka", ad)
