# -*- coding: utf-8 -*-
"""
Claude Desktop (stdio) ↔ Kontrol Merkezi (/mcp, streamable HTTP) köprüsü.

  AlamountRPA.exe mcp --merkez https://rpa-sunucu:8765/mcp      (anahtar: ALAMOUNT_MCP_ANAHTARI)

stdin'den gelen her JSON-RPC mesajını merkeze POST eder, yanıtı stdout'a yazar.
stdout yalnızca MCP protokolüne aittir; bütün loglar stderr'e gider.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _yaz(mesaj):
    sys.stdout.write(json.dumps(mesaj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _hata(istek_id, mesaj, kod=-32603):
    if istek_id is not None:
        _yaz({"jsonrpc": "2.0", "id": istek_id, "error": {"code": kod, "message": mesaj}})


def _sse_ayikla(govde):
    """text/event-stream yanıtındaki 'data:' satırlarından JSON-RPC mesajlarını çıkarır."""
    for blok in govde.split("\n\n"):
        veri = "\n".join(s[5:].lstrip() for s in blok.splitlines() if s.startswith("data:"))
        if veri.strip():
            yield json.loads(veri)


def calistir(url, anahtar, ca_dosyasi="", ssl_dogrula=True):
    if not anahtar:
        print("MCP anahtarı yok: ALAMOUNT_MCP_ANAHTARI ortam değişkenini ya da --anahtar seçeneğini kullanın.",
              file=sys.stderr)
        return 2
    url = url.rstrip("/")
    if not url.endswith("/mcp"):
        url += "/mcp"
    ctx = None
    if url.startswith("https"):
        ctx = ssl.create_default_context(cafile=ca_dosyasi or None)
        if not ssl_dogrula:
            ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    protokol = None
    oturum = None
    print(f"Alamount RPA MCP köprüsü → {url}", file=sys.stderr)
    for satir in sys.stdin:
        satir = satir.strip()
        if not satir:
            continue
        try:
            mesaj = json.loads(satir)
        except json.JSONDecodeError:
            continue
        istek_id = mesaj.get("id") if isinstance(mesaj, dict) else None
        basliklar = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                     "Authorization": f"Bearer {anahtar}"}
        if protokol:
            basliklar["MCP-Protocol-Version"] = protokol
        if oturum:
            basliklar["Mcp-Session-Id"] = oturum
        req = urllib.request.Request(url, data=satir.encode("utf-8"), headers=basliklar, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
                oturum = r.headers.get("Mcp-Session-Id") or oturum
                govde = r.read().decode("utf-8")
                if r.status == 202 or not govde.strip():
                    continue
                if "text/event-stream" in (r.headers.get("Content-Type") or ""):
                    yanitlar = list(_sse_ayikla(govde))
                else:
                    yanit = json.loads(govde)
                    yanitlar = yanit if isinstance(yanit, list) else [yanit]
                for y in yanitlar:
                    if isinstance(y, dict) and isinstance(y.get("result"), dict) and y["result"].get("protocolVersion"):
                        protokol = y["result"]["protocolVersion"]
                    _yaz(y)
        except urllib.error.HTTPError as e:
            try:
                y = json.loads(e.read().decode("utf-8"))
                mesaj_metni = (y.get("error") or {}).get("message") or e.reason
            except Exception:
                mesaj_metni = e.reason
            print(f"Merkez HTTP {e.code}: {mesaj_metni}", file=sys.stderr)
            _hata(istek_id, f"Alamount RPA Kontrol Merkezi: {mesaj_metni} (HTTP {e.code})")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print(f"Merkeze ulaşılamıyor: {e}", file=sys.stderr)
            _hata(istek_id, f"Alamount RPA Kontrol Merkezi'ne ulaşılamıyor: {getattr(e, 'reason', e)}")
    return 0
