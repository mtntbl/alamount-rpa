# -*- coding: utf-8 -*-
"""
Kontrol Merkezi MCP uyumluluk testi (resmi MCP Python istemcisiyle):
  * Streamable HTTP + Authorization: Bearer   (GitHub Copilot / VS Code, Claude uzak bağlayıcı yolu)
  * X-API-Key başlığı + eski protokol sürümleri (Copilot Studio yolu)
  * stdio köprüsü: AlamountRPA mcp --merkez   (Claude Desktop yolu)
  * Roller, anahtarsız erişim, kişisel veri maskeleme, denetim kaydı
Kullanım: python testler/mcp_uyumluluk.py <proje_klasoru> <gecici_calisma_klasoru>
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

import httpx2 as httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

KOK, W = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, KOK)
import ayarlar  # noqa: E402
import merkez_db  # noqa: E402

PORT = 18877
URL = f"http://127.0.0.1:{PORT}/mcp"
shutil.rmtree(W, ignore_errors=True)
os.makedirs(W)
shutil.copytree(os.path.join(KOK, "gorevler"), os.path.join(W, "gorevler"))
cfg = ayarlar.TAM_CONFIG.replace("tesseract_yolu = tesseract\\tesseract.exe", "tesseract_yolu =")
cfg = re.sub(r"(\[MERKEZ\][\s\S]*?\n)port\s*=[^\n]*", lambda m: m.group(1) + f"port = {PORT}", cfg, count=1)
cfg = re.sub(r"(\[MCP\][\s\S]*?\n)aktif\s*=[^\n]*", lambda m: m.group(1) + "aktif = evet", cfg, count=1)
open(os.path.join(W, "config.ini"), "w", encoding="utf-8").write(cfg)

db = merkez_db.Veritabani(os.path.join(W, "merkez_veri"))
db.kullanici_ekle("ayse", "Parola12345", "operator")
db.kullanici_ekle("izzet", "Parola12345", "izleyici")
ayse = db.tek("SELECT id FROM kullanicilar WHERE ad='ayse'")["id"]
izzet = db.tek("SELECT id FROM kullanicilar WHERE ad='izzet'")["id"]
K_OP = db.api_anahtari_olustur(ayse, "Claude")
K_IZ = db.api_anahtari_olustur(izzet, "Copilot")
db.robot_ekle("ROBOT-1")
db.oge_ekle("ise_giris", "12345678028", {"pdf": "x"}, "i1")
oid = db.oge_al("ise_giris", "ROBOT-1")["id"]
db.oge_bitir(oid, "basarili", {"excel": r"\\sunucu\ik\İşe Girişi Hazır - AYŞE YILMAZ (12345678028).xlsx",
                                "ad_soyad": "AYŞE YILMAZ", "Otomatik": 35})

PY = sys.executable
BOT = os.path.join(KOK, "alamount_rpa.py")
merkez = subprocess.Popen([PY, BOT, "--config", os.path.join(W, "config.ini"), "merkez"],
                          stdout=open(os.path.join(W, "merkez.out"), "w"), stderr=subprocess.STDOUT, cwd=W)
for _ in range(60):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/saglik", timeout=2)
        break
    except Exception:
        time.sleep(0.5)

SONUC = {}


def metin(r):
    return "".join(c.text for c in r.content if getattr(c, "type", "") == "text")


async def http_oturumu(anahtar, govde):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {anahtar}"}, timeout=30) as hc:
        async with streamable_http_client(URL, http_client=hc) as akislar:
            async with ClientSession(akislar[0], akislar[1]) as s:
                bilgi = await s.initialize()
                return await govde(s, bilgi)


async def operator_testi(s, bilgi):
    SONUC["HTTP: initialize (sunucu adı)"] = bilgi.server_info.name == "alamount-rpa"
    araclar = (await s.list_tools()).tools
    adlar = {a.name for a in araclar}
    SONUC["HTTP: 11 araç listelendi"] = len(adlar) == 11 and {"is_baslat", "durum_ozeti", "kuyruk_ogeleri"} <= adlar
    ro = {a.name: a.annotations.read_only_hint for a in araclar}
    SONUC["araç ipuçları (salt okunur/yazma)"] = ro["durum_ozeti"] is True and ro["is_baslat"] is False
    d = json.loads(metin(await s.call_tool("durum_ozeti", {})))
    SONUC["durum_ozeti çalışıyor"] = d["robotlar"][0]["ad"] == "ROBOT-1"
    r = await s.call_tool("is_baslat", {"surec": "pca"})
    SONUC["operator iş başlatabiliyor"] = not r.is_error and "kuyruğa alındı" in metin(r)
    r = await s.call_tool("is_baslat", {"surec": "robot:../../etc"})
    SONUC["geçersiz süreç reddedildi (anlaşılır mesaj)"] = r.is_error and "bulunamadı" in metin(r)
    r = await s.call_tool("zamanlama_ekle", {"ad": "x", "surec": "pca", "cron": "@gunluk"})
    SONUC["operator zamanlama ekleyemiyor (yonetici gerekir)"] = r.is_error and "yonetici" in metin(r)
    k = metin(await s.call_tool("kuyruk_ogeleri", {"kuyruk": "ise_giris"}))
    SONUC["kişisel veri maskeli (TC ve ad yok)"] = ("12345678028" not in k and "AYŞE" not in k and "123******28" in k)
    return True


async def izleyici_testi(s, bilgi):
    r = await s.call_tool("is_baslat", {"surec": "pca"})
    SONUC["izleyici iş başlatamıyor"] = r.is_error and "operator" in metin(r)
    r = await s.call_tool("isleri_listele", {})
    SONUC["izleyici işleri görebiliyor"] = not r.is_error and '"surec": "pca"' in metin(r)
    return True


asyncio.run(http_oturumu(K_OP, operator_testi))
asyncio.run(http_oturumu(K_IZ, izleyici_testi))

# ---- Copilot Studio yolu: X-API-Key + eski protokol sürümleri, ham JSON-RPC
for surum in ("2025-03-26", "2025-06-18"):
    r = httpx.post(URL, headers={"X-API-Key": K_IZ, "Accept": "application/json, text/event-stream",
                                 "Content-Type": "application/json"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"protocolVersion": surum, "capabilities": {},
                                    "clientInfo": {"name": "copilot-studio-benzeri", "version": "1"}}}, timeout=30)
    SONUC[f"X-API-Key + protokol {surum}"] = r.status_code == 200 and r.json()["result"]["protocolVersion"] == surum
r = httpx.post(URL, headers={"X-API-Key": K_IZ, "Accept": "application/json, text/event-stream",
                             "Content-Type": "application/json", "MCP-Protocol-Version": "2025-06-18"},
               json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, timeout=30)
SONUC["X-API-Key ile tools/list"] = r.status_code == 200 and len(r.json()["result"]["tools"]) == 11
r = httpx.post(URL, headers={"Accept": "application/json", "Content-Type": "application/json"},
               json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=30)
SONUC["anahtarsız istek 401"] = r.status_code == 401
r = httpx.post(URL, headers={"Authorization": "Bearer alm_sahte", "Content-Type": "application/json"},
               json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=30)
SONUC["yanlış anahtar 401"] = r.status_code == 401
db.api_anahtari_iptal(db.api_anahtarlari(izzet)[0]["id"], izzet)
r = httpx.post(URL, headers={"X-API-Key": K_IZ, "Content-Type": "application/json"},
               json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, timeout=30)
SONUC["iptal edilen anahtar 401"] = r.status_code == 401


# ---- Claude Desktop yolu: stdio köprüsü
async def kopru_testi():
    p = StdioServerParameters(command=PY, args=[BOT, "mcp", "--merkez", URL],
                              env={**os.environ, "ALAMOUNT_MCP_ANAHTARI": K_OP})
    async with stdio_client(p) as (oku, yaz):
        async with ClientSession(oku, yaz) as s:
            bilgi = await s.initialize()
            SONUC["köprü: initialize"] = bilgi.server_info.name == "alamount-rpa"
            SONUC["köprü: 11 araç"] = len((await s.list_tools()).tools) == 11
            r = await s.call_tool("isleri_listele", {"durum": "bekliyor"})
            SONUC["köprü: araç çağrısı"] = not r.is_error and "pca" in metin(r)


asyncio.run(kopru_testi())

d = db.sorgu("SELECT kim, eylem FROM denetim WHERE eylem LIKE 'mcp:%'")
SONUC["MCP çağrıları denetime '(MCP)' ile yazıldı"] = len(d) >= 5 and all(x["kim"].endswith("(MCP)") for x in d)
SONUC["reddedilen denemeler de denetimde"] = len(db.sorgu("SELECT 1 FROM denetim WHERE eylem='mcp_reddedildi'")) == 2
merkez.terminate()
print("\n=========== MCP UYUMLULUK ===========")
for k, v in SONUC.items():
    print(("✅" if v else "❌"), k)
print(f"{sum(SONUC.values())}/{len(SONUC)} geçti")
sys.exit(0 if all(SONUC.values()) else 1)
