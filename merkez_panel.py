# -*- coding: utf-8 -*-
"""Kontrol Merkezi web paneli — HTML şablonları (bağımlılıksız, sunucu tarafında üretilir)."""

import datetime as dt
import html
import json

import marka

CSS = """
:root{--bg:#f3f6fa;--kart:#fff;--yazi:#14213a;--soluk:#5c6b80;--cizgi:#dbe3ec;--ana:#022351;--ana-h:#0b3a7a;
--vurgu:#04baf3;--bag:#0a6fb8;--ust:#fff;--ust-yazi:#022351;--ust-soluk:#5c6b80;
--yesil:#17723a;--yesil-a:#e2f4e8;--kirmizi:#b42318;--kirmizi-a:#fde8e6;--sari:#8a5a00;--sari-a:#fff4d6;
--mavi:#0a5c99;--mavi-a:#ddf4fd;--gri-a:#eef2f6}
@media (prefers-color-scheme:dark){:root{--bg:#0b1220;--kart:#121b2b;--yazi:#e6edf6;--soluk:#93a3b8;--cizgi:#243149;
--ana:#04baf3;--ana-h:#38cbf7;--vurgu:#04baf3;--bag:#5ccff8;--ust:#0e1726;--ust-yazi:#e6edf6;--ust-soluk:#93a3b8;
--yesil:#6fd38f;--yesil-a:#163222;--kirmizi:#ff8a80;--kirmizi-a:#3a1b19;--sari:#f2c46b;--sari-a:#382c12;
--mavi:#7fd8f9;--mavi-a:#10314a;--gri-a:#1a2436}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 "Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--yazi);
display:flex;flex-direction:column;min-height:100vh}
a{color:var(--bag);text-decoration:none}a:hover{text-decoration:underline}
header{background:var(--ust);color:var(--ust-yazi);padding:0 20px;display:flex;align-items:center;gap:20px;flex-wrap:wrap;
border-top:3px solid var(--vurgu);border-bottom:1px solid var(--cizgi);box-shadow:0 1px 3px #0223510f}
header .marka{display:flex;align-items:center;gap:12px;padding:8px 0;text-decoration:none}
header .marka img{height:38px;width:auto;display:block}
header .marka span{color:var(--ust-soluk);font-size:13px;border-left:1px solid var(--cizgi);padding-left:12px;white-space:nowrap}
header nav{display:flex;flex-wrap:wrap;gap:2px;align-self:stretch}
header nav a{color:var(--ust-yazi);padding:18px 10px 15px;display:flex;align-items:center;border-bottom:3px solid transparent;font-weight:500}
header nav a:hover{text-decoration:none;border-bottom-color:var(--cizgi)}
header nav a.aktif{border-bottom-color:var(--vurgu);font-weight:700}
header .sag{margin-left:auto;font-size:13px;color:var(--ust-soluk);display:flex;align-items:center;gap:8px}
main{max-width:1280px;width:100%;margin:0 auto;padding:22px 16px;flex:1}
h1{font-size:22px;margin:4px 0 16px;color:var(--ana)}@media (prefers-color-scheme:dark){h1{color:var(--yazi)}}
h2{font-size:16px;margin:24px 0 10px}
.kart{background:var(--kart);border:1px solid var(--cizgi);border-radius:10px;padding:16px;margin-bottom:16px}
.kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:16px}
.kpi div{background:var(--kart);border:1px solid var(--cizgi);border-radius:10px;padding:14px;border-top:3px solid var(--vurgu)}
.kpi b{display:block;font-size:26px;line-height:1.2;color:var(--ana)}@media (prefers-color-scheme:dark){.kpi b{color:var(--yazi)}}
.kpi span{color:var(--soluk);font-size:12px}
.tablo{overflow-x:auto}table{border-collapse:collapse;width:100%;background:var(--kart)}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--cizgi);vertical-align:top}
th{font-size:12px;color:var(--soluk);font-weight:600;background:var(--gri-a)}tr:hover td{background:var(--gri-a)}
.rozet{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;font-weight:600;white-space:nowrap}
.r-basarili,.r-cevrimici,.r-bosta{background:var(--yesil-a);color:var(--yesil)}
.r-basarisiz,.r-cevrimdisi,.r-iptal{background:var(--kirmizi-a);color:var(--kirmizi)}
.r-calisiyor,.r-isleniyor,.r-mesgul{background:var(--mavi-a);color:var(--mavi)}
.r-bekliyor,.r-yeni,.r-yeniden{background:var(--sari-a);color:var(--sari)}.r-pasif,.r-bilinmiyor{background:var(--gri-a);color:var(--soluk)}
form.satir{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end}
label{display:flex;flex-direction:column;font-size:12px;color:var(--soluk);gap:3px}
input,select,textarea{font:inherit;padding:7px 9px;border:1px solid var(--cizgi);border-radius:6px;background:var(--kart);color:var(--yazi);min-width:0}
input:focus,select:focus,textarea:focus{outline:2px solid var(--vurgu);outline-offset:-1px;border-color:var(--vurgu)}
textarea{min-height:60px}
button,.dugme{font:inherit;padding:7px 14px;border-radius:6px;border:1px solid var(--ana);background:var(--ana);color:#fff;cursor:pointer;font-weight:600}
button:hover{background:var(--ana-h);border-color:var(--ana-h)}
@media (prefers-color-scheme:dark){button,.dugme{color:#04121f}}
button.ikincil{background:transparent;color:var(--bag);border-color:var(--cizgi);font-weight:500}button.ikincil:hover{border-color:var(--vurgu);background:var(--mavi-a)}
button.tehlike{background:var(--kirmizi);border-color:var(--kirmizi);color:#fff}
form.ic{display:inline}td form.ic button{padding:2px 8px;font-size:12px}
pre{background:#071226;color:#d7e3f2;padding:12px;border-radius:8px;overflow:auto;max-height:520px;font-size:12px;white-space:pre-wrap;word-break:break-word;border-left:3px solid var(--vurgu)}
.uyari{background:var(--sari-a);color:var(--sari);padding:10px 14px;border-radius:6px;margin-bottom:14px}
.hata{background:var(--kirmizi-a);color:var(--kirmizi);padding:10px 14px;border-radius:6px;margin-bottom:14px}
.basari{background:var(--yesil-a);color:var(--yesil);padding:10px 14px;border-radius:6px;margin-bottom:14px}
.soluk{color:var(--soluk)}.nw{white-space:nowrap}.anahtar{font-family:Consolas,monospace;background:var(--gri-a);padding:8px;border-radius:6px;word-break:break-all;display:block}
.giris-sayfa{flex:1;display:flex;align-items:center;justify-content:center;padding:24px 16px;
background:linear-gradient(160deg,var(--bg) 0%,var(--bg) 55%,var(--mavi-a) 100%)}
.giris{width:100%;max-width:380px;padding:28px;border-top:4px solid var(--vurgu)}
.giris img{width:230px;max-width:100%;display:block;margin:0 auto 6px}
.giris p.alt{text-align:center;color:var(--soluk);margin:0 0 20px;font-size:13px}
.giris form{display:flex;flex-direction:column;gap:12px}.giris button{padding:10px}
.filtre a{margin-right:10px}
footer{text-align:center;color:var(--soluk);font-size:12px;padding:14px}
@media (max-width:760px){header{gap:8px}header .marka span{display:none}header nav a{padding:10px 7px 8px}main{padding:14px 12px}}
"""

MENU = [
    ("/", "Pano", "izleyici"), ("/isler", "İşler", "izleyici"), ("/kuyruklar", "Kuyruklar", "izleyici"),
    ("/zamanlamalar", "Zamanlamalar", "izleyici"), ("/robotlar", "Robotlar", "izleyici"),
    ("/varliklar", "Varlıklar", "yonetici"), ("/kullanicilar", "Kullanıcılar", "yonetici"),
    ("/denetim", "Denetim", "yonetici"), ("/mcp-baglanti", "MCP / LLM", "izleyici"),
]
ROL_SIRA = {"izleyici": 0, "operator": 1, "yonetici": 2}
DURUM_ADI = {
    "bekliyor": "Bekliyor", "calisiyor": "Çalışıyor", "basarili": "Başarılı", "basarisiz": "Başarısız",
    "iptal": "İptal", "yeni": "Yeni", "isleniyor": "İşleniyor", "cevrimici": "Çevrimiçi",
    "cevrimdisi": "Çevrimdışı", "bosta": "Boşta", "mesgul": "Meşgul", "bilinmiyor": "Bilinmiyor", "pasif": "Pasif",
}


def e(x):
    return html.escape("" if x is None else str(x), quote=True)


def yetkili(kullanici, rol):
    return ROL_SIRA.get(kullanici["rol"], -1) >= ROL_SIRA[rol]


def zaman(ts):
    if not ts:
        return "—"
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M:%S")


def sure(bas, son=None):
    if not bas:
        return "—"
    s = int((son or dt.datetime.now().timestamp()) - bas)
    if s < 60:
        return f"{s} sn"
    if s < 3600:
        return f"{s // 60} dk {s % 60} sn"
    return f"{s // 3600} sa {s % 3600 // 60} dk"


def rozet(durum):
    return f'<span class="rozet r-{e(durum)}">{e(DURUM_ADI.get(durum, durum))}</span>'


def csrf_alani(kullanici):
    return f'<input type="hidden" name="csrf" value="{e(kullanici["csrf"])}">'


def dugme_form(eylem, etiket, kullanici, sinif="ikincil", onay=None, gizli=None):
    ek = "".join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k, v in (gizli or {}).items())
    js = f' onsubmit="return confirm(\'{e(onay)}\')"' if onay else ""
    return (f'<form class="ic" method="post" action="{e(eylem)}"{js}>{csrf_alani(kullanici)}{ek}'
            f'<button class="{sinif}">{e(etiket)}</button></form>')


def tablo(basliklar, satirlar, bos="Kayıt yok", kirilmaz=()):
    """kirilmaz: satır sonuna kırılmayacak sütunların sıra numaraları."""
    if not satirlar:
        return f'<p class="soluk">{e(bos)}</p>'
    th = "".join(f"<th>{e(b)}</th>" for b in basliklar)
    tr = "".join("<tr>" + "".join(f'<td{" class=nw" if i in kirilmaz else ""}>{h}</td>' for i, h in enumerate(s))
                 + "</tr>" for s in satirlar)
    return f'<div class="tablo"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def secenekler(lst, secili=""):
    return "".join(f'<option value="{e(v)}"{" selected" if v == secili else ""}>{e(a)}</option>' for v, a in lst)


LOGO = ('<picture><source srcset="/marka/logo_koyu.png" media="(prefers-color-scheme: dark)">'
        f'<img src="/marka/logo.png" alt="{marka.URUN}"></picture>')


def _bas(baslik, yenile=None):
    yen = f'<meta http-equiv="refresh" content="{int(yenile)}">' if yenile else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">{yen}
<title>{e(baslik)} · {marka.URUN}</title><link rel="icon" type="image/png" href="/marka/favicon.png">
<meta name="theme-color" content="{marka.LACIVERT}"><style>{CSS}</style></head><body>"""


def sayfa(baslik, govde, kullanici=None, aktif="", yenile=None, mesaj=None):
    nav = ""
    sag = ""
    if kullanici:
        nav = "<nav>" + "".join(
            f'<a href="{u}" class="{"aktif" if u == aktif else ""}">{e(a)}</a>'
            for u, a, rol in MENU if yetkili(kullanici, rol)) + "</nav>"
        sag = (f'<div class="sag"><span>{e(kullanici["ad"])} · {e(kullanici["rol"])}</span>'
               f'<form class="ic" method="post" action="/cikis">{csrf_alani(kullanici)}'
               f'<button class="ikincil" style="padding:3px 10px">Çıkış</button></form></div>')
    msj = ""
    if mesaj:
        tur, metin = mesaj
        msj = f'<div class="{e(tur)}">{e(metin)}</div>'
    return (_bas(baslik, yenile)
            + f'<header><a class="marka" href="/">{LOGO}<span>Kontrol Merkezi</span></a>{nav}{sag}</header>'
            + f"<main><h1>{e(baslik)}</h1>{msj}{govde}</main>"
            + f"<footer>{marka.URUN} v{marka.SURUM} · {marka.SIRKET}</footer></body></html>")


def giris_sayfasi(hata=None):
    h = f'<div class="hata">{e(hata)}</div>' if hata else ""
    return (_bas("Giriş") + f"""<div class="giris-sayfa"><div class="giris kart">{LOGO}
<p class="alt">Kontrol Merkezi</p>{h}<form method="post" action="/giris">
<label>Kullanıcı adı<input name="ad" autocomplete="username" required autofocus></label>
<label>Parola<input name="sifre" type="password" autocomplete="current-password" required></label>
<button>Giriş yap</button></form></div></div>
<footer>{marka.URUN} v{marka.SURUM} · {marka.SIRKET}</footer></body></html>""")


def oge_sonucu(s):
    """Kuyruk öğesi sonucunu kısa gösterir: dosya yolları yalnızca adıyla (tam yol üzerine gelince)."""
    try:
        d = json.loads(s) if isinstance(s, str) else (s or {})
    except Exception:
        return e(s)
    if not isinstance(d, dict) or not d:
        return ""
    dosyalar, diger = [], []
    for k, v in d.items():
        metin = str(v)
        if isinstance(v, str) and ("/" in metin or "\\" in metin) and "." in metin[-6:]:
            ad = metin.replace("\\", "/").rsplit("/", 1)[-1]
            dosyalar.append(f'<span title="{e(metin)}">📄 {e(ad)}</span>')
        elif k != "ad_soyad":
            diger.append(f"{e(k)}: <b>{e(v)}</b>")
    ust = e(d["ad_soyad"]) + "<br>" if d.get("ad_soyad") else ""
    return ust + "<br>".join(dosyalar) + ('<br><span class="soluk">' + " · ".join(diger) + "</span>" if diger else "")


def json_goster(s):
    try:
        d = json.loads(s) if isinstance(s, str) else s
    except Exception:
        return e(s)
    if not d:
        return ""
    if isinstance(d, dict):
        return "<br>".join(f"<b>{e(k)}</b>: {e(v if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False))}"
                           for k, v in d.items())
    return e(", ".join(map(str, d)) if isinstance(d, list) else d)
