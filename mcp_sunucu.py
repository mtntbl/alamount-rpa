# -*- coding: utf-8 -*-
"""
MCP sunucusu (stdio). Claude Desktop / Claude Code gibi MCP istemcilerinin robotu araç olarak
kullanmasını sağlar:  AlamountRPA.exe mcp

Claude Desktop ayarı (claude_desktop_config.json):
  {"mcpServers": {"alamount-rpa": {"command": "C:\\\\AlamountRPA\\\\AlamountRPA.exe", "args": ["mcp"]}}}

DİKKAT: Araç sonuçları (OCR metni, kişisel veriler) istemci üzerinden modele gider.
"""

import glob
import io
import json
import os
from contextlib import redirect_stdout

from mcp.server.mcpserver import MCPServer

import ayarlar as ay
import belge_ocr as bo
import ise_giris
import pca_analiz


def sunucu_olustur(config_yolu):
    ayarlar = ay.ayarlari_yukle(config_yolu)
    server = MCPServer(
        name="alamount-rpa",
        instructions=(
            "Yerel RPA robotu: PDF/görsel OCR (Türkçe), işe giriş verisi hazırlama (Puantaj + personel PDF → "
            "Mikro'ya hazır Excel), PCA analizi ve Robot Framework görevleri. Dosya yolları bu bilgisayardaki "
            "yollardır. Kişisel verileri yalnızca görev için kullan."
        ),
    )

    @server.tool()
    def ocr_pdf(pdf_yolu: str) -> str:
        """PDF'i metne çevirir. Taranmış sayfalara Tesseract (Türkçe) ile OCR uygular."""
        return bo.pdf_metne_cevir(pdf_yolu, ayarlar)

    @server.tool()
    def belge_analizi(pdf_yolu: str) -> str:
        """Personel PDF'indeki sayfaların belge türlerini ve çıkarılan alanları JSON olarak döner."""
        sonuc = bo.pdf_coz(pdf_yolu, ayarlar)
        return json.dumps({
            "sayfalar": [{"no": s["no"], "tur": bo.BELGE_ADLARI.get(s["tur"], s["tur"]), "okuma": s["kaynak"],
                          "kart_sayisi": s["kart_sayisi"]} for s in sonuc["sayfalar"]],
            "alanlar": sonuc["belgeler"],
            "tc_listesi": sonuc["tc_listesi"],
        }, ensure_ascii=False, indent=2)

    @server.tool()
    def ise_giris_hazirla(tc: str, pdf_yolu: str, puantaj_yolu: str = "") -> str:
        """Tek personel için Mikro'ya girişe hazır Excel üretir. Excel yolu, durum özeti ve uyarıları döner."""
        r = ise_giris.hazirla(tc, pdf_yolu, puantaj_yolu or ayarlar.yol("ISE_GIRIS", "puantaj"), ayarlar)
        return json.dumps({k: r[k] for k in ("excel", "ozet", "uyarilar", "ad_soyad")}, ensure_ascii=False, indent=2)

    @server.tool()
    def ise_giris_klasorunu_isle() -> str:
        """input\\ise_giris klasöründeki tüm <TC>.pdf dosyalarını işler."""
        sonuclar = ise_giris.klasoru_isle(ayarlar)
        return json.dumps([{k: v for k, v in r.items() if k in ("excel", "ozet", "uyarilar", "hata", "dosya")}
                           for r in sonuclar], ensure_ascii=False, indent=2)

    @server.tool()
    def pca_analizi(dosya_yolu: str = "") -> str:
        """Verilen veri dosyasına (ya da input klasöründekilere) PCA uygular; Excel rapor + grafik üretir."""
        if dosya_yolu:
            ok = pca_analiz.process_file(os.path.abspath(dosya_yolu), ayarlar)
            return "Başarılı" if ok else "Hata — logs klasörüne bakın"
        ok, hata = pca_analiz.run_once(ayarlar)
        return f"Başarılı: {ok}, Hatalı: {hata}"

    @server.tool()
    def gorev_listesi() -> str:
        """Çalıştırılabilecek Robot Framework görevlerini listeler."""
        klasor = ayarlar.yol("ROBOT", "gorev_klasoru")
        return "\n".join(os.path.splitext(os.path.basename(p))[0] for p in sorted(glob.glob(os.path.join(klasor, "*.robot"))))

    @server.tool()
    def robot_gorevi_calistir(gorev: str, kuru_calisma: bool = True) -> str:
        """Bir Robot Framework görevini çalıştırır (ör. ise_giris_hazirla). Mikro görevleri varsayılan kuru çalışır."""
        import alamount_rpa

        buf = io.StringIO()
        with redirect_stdout(buf):
            kod = alamount_rpa.robot_calistir(ayarlar, gorev, ["--variable", f"KURU_CALISMA:{'evet' if kuru_calisma else 'hayir'}",
                                                          "--console", "dotted"])
        return f"Çıkış kodu: {kod}\n{buf.getvalue()[-4000:]}"

    return server


def calistir(config_yolu):
    sunucu_olustur(config_yolu).run("stdio")
