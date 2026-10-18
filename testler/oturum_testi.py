# -*- coding: utf-8 -*-
"""
Gözetimsiz oturum mantığı testi (her platformda): gözetmen kararları, kullanıcı adı çözümü,
Görev Zamanlayıcı XML'i, config.ini [OTURUM] güncellemesi, ajan durum dosyası.
Windows API'li kısımlar (LSA, WTS, schtasks) Windows CI'da exe ile denenir.
Kullanım: python testler/oturum_testi.py <proje_klasoru>
"""
import os
import sys
import tempfile
import xml.dom.minidom

KOK = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
sys.path.insert(0, KOK)
import ayarlar  # noqa: E402
import oturum as o  # noqa: E402

SONUC = {}
PC = "ROBOTPC"
SONUC["kullanıcı: .\\robot1"] = o.kullanici_coz(".\\robot1", PC) == (PC, "robot1")
SONUC["kullanıcı: ALAN\\robot1"] = o.kullanici_coz("ALAMOUNT\\robot1", PC) == ("ALAMOUNT", "robot1")
SONUC["kullanıcı: UPN"] = o.kullanici_coz("robot1@alamount.net", PC) == ("", "robot1@alamount.net")
SONUC["kullanıcı: yalın ad"] = o.kullanici_coz("robot1", PC) == (PC, "robot1")


def ot(id_, kul, durum, kilitli=False, istasyon="Console", alan=PC):
    return {"id": id_, "kullanici": kul, "alan": alan, "durum": durum, "kilitli": kilitli, "istasyon": istasyon}


T = 1_000_000.0
K = ".\\robot1"
SONUC["karar: oturum yok → bekle"] = o.karar([ot(0, "", "bagli_degil", None, "Services")], K, None, T, bilgisayar=PC)[0] == "bekle"
SONUC["karar: açık oturum → tamam"] = o.karar([ot(1, "robot1", "aktif")], K, None, T, bilgisayar=PC)[:2] == ("tamam", 1)
SONUC["karar: büyük/küçük harf duyarsız"] = o.karar([ot(1, "Robot1", "aktif", alan="robotpc")], K, None, T,
                                                    bilgisayar=PC)[0] == "tamam"
SONUC["karar: RDP kapatıldı → konsola bağla"] = o.karar([ot(2, "robot1", "bagli_degil", istasyon="")], K, None, T,
                                                        bilgisayar=PC)[:2] == ("konsola_bagla", 2)
SONUC["karar: konsolda başkası varsa dokunma"] = o.karar(
    [ot(2, "robot1", "bagli_degil", istasyon=""), ot(3, "ayse", "aktif")], K, None, T, bilgisayar=PC)[0] == "bekle"
kilitli = [ot(1, "robot1", "aktif", kilitli=True)]
SONUC["karar: yeni kilitlendi → bekle"] = o.karar(kilitli, K, None, T, None, bilgisayar=PC)[0] == "bekle"
SONUC["karar: kilitli + süre doldu + boşta → kapat"] = o.karar(kilitli, K, {"mesgul": False, "zaman": T}, T, T - 61,
                                                               bilgisayar=PC)[:2] == ("oturumu_kapat", 1)
SONUC["karar: kilitli ama robot çalışıyor → bekle"] = o.karar(kilitli, K, {"mesgul": True, "zaman": T - 5}, T, T - 600,
                                                              bilgisayar=PC)[0] == "bekle"
SONUC["karar: ajan durumu eskiyse meşgul sayılmaz"] = o.karar(kilitli, K, {"mesgul": True, "zaman": T - 600}, T,
                                                              T - 600, bilgisayar=PC)[0] == "oturumu_kapat"
SONUC["karar: kilitliyken_yeniden_ac=hayir"] = o.karar(kilitli, K, None, T, T - 600, yeniden_ac=False,
                                                       bilgisayar=PC)[0] == "bekle"
SONUC["karar: başka kullanıcının oturumu sayılmaz"] = o.karar([ot(4, "robot10", "aktif")], K, None, T,
                                                              bilgisayar=PC)[0] == "bekle"
SONUC["karar: aktif oturum bağlı olmayana tercih edilir"] = o.karar(
    [ot(5, "robot1", "bagli_degil", istasyon=""), ot(6, "robot1", "aktif")], K, None, T, bilgisayar=PC)[:2] == ("tamam", 6)

x = o.gorev_xml("Ajan & <test>", r"C:\Alamount RPA\AlamountRPA.exe", r'--config "C:\Alamount RPA\config.ini" ajan',
                r"C:\Alamount RPA", "ROBOTPC\\robot1")
d = xml.dom.minidom.parseString(x.replace('encoding="UTF-16"', 'encoding="UTF-8"').encode("utf-8"))
SONUC["görev XML: ajan (oturum açılınca, etkileşimli)"] = (
    d.getElementsByTagName("LogonType")[0].firstChild.data == "InteractiveToken"
    and d.getElementsByTagName("UserId")[0].firstChild.data == "ROBOTPC\\robot1"
    and d.getElementsByTagName("Description")[0].firstChild.data == "Ajan & <test>"
    and d.getElementsByTagName("ExecutionTimeLimit")[0].firstChild.data == "PT0S")
x = o.gorev_xml("Gözetmen", "a.exe", "oturum-gozetmen", "C:\\")
d = xml.dom.minidom.parseString(x.replace('encoding="UTF-16"', 'encoding="UTF-8"').encode("utf-8"))
SONUC["görev XML: gözetmen (açılışta, SYSTEM)"] = bool(d.getElementsByTagName("BootTrigger")) and \
    d.getElementsByTagName("UserId")[0].firstChild.data == "S-1-5-18"

g = tempfile.mkdtemp()
cfg = os.path.join(g, "config.ini")
open(cfg, "w", encoding="utf-8").write(ayarlar.TAM_CONFIG)
o.config_bolumunu_yaz(cfg, {"mod": "autologon", "kullanici": "ROBOTPC\\robot1", "parola_varligi": "R1",
                            "kilitliyken_is_al": "hayir"})
a = ayarlar.ayarlari_yukle(cfg)
metin = open(cfg, encoding="utf-8").read()
SONUC["config [OTURUM] güncellendi, yorumlar korundu"] = (
    a.get("OTURUM", "mod") == "autologon" and a.get("OTURUM", "kullanici") == "ROBOTPC\\robot1"
    and not a.getbool("OTURUM", "kilitliyken_is_al") and a.get("AJAN", "nabiz_sn") == "15"
    and "; Gözetimsiz robot" in metin and metin.count("[OTURUM]") == 1)
eski = os.path.join(g, "eski.ini")
open(eski, "w", encoding="utf-8").write("[GENEL]\nmod = test\n")
o.config_bolumunu_yaz(eski, {"mod": "yok"})
a2 = ayarlar.ayarlari_yukle(eski)
SONUC["eski config'e [OTURUM] eklendi"] = a2.get("OTURUM", "mod") == "yok" and a2.get("GENEL", "mod") == "test"

o.ajan_durumunu_yaz(a, True, "acik")
dd = o.ajan_durumunu_oku(a)
SONUC["ajan durum dosyası"] = dd["mesgul"] is True and dd["oturum"] == "acik"
SONUC["Windows dışı: oturum durumu 'bilinmiyor'"] = os.name == "nt" or o.bu_oturum_durumu() == "bilinmiyor"

print("\n=========== GÖZETİMSİZ OTURUM ===========")
for k_, v in SONUC.items():
    print(("✅" if v else "❌"), k_)
print(f"{sum(SONUC.values())}/{len(SONUC)} geçti")
sys.exit(0 if all(SONUC.values()) else 1)
