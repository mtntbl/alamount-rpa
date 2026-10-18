# -*- coding: utf-8 -*-
"""
Ajan katmanı (opsiyonel) — Claude API.
Kural/OCR ile çıkarılamayan alanları belge metninden ve kimlik görselinden okur.
Varsayılan olarak KAPALIDIR ([LLM] aktif = hayir). Açıldığında kişisel veri Anthropic API'sine gider.
"""

import base64
import io
import json
import logging
import os

log = logging.getLogger("alamount")

SISTEM = (
    "Türk kamu belgelerinden (e-Devlet çıktıları, T.C. kimlik kartı) personel bilgisi çıkaran bir veri "
    "giriş asistanısın. Yalnızca belgede açıkça yazan bilgiyi döndür. Bir alan belgede yoksa ya da "
    "okunamıyorsa null döndür; asla tahmin etme veya uydurma. Tarihleri gg.aa.yyyy biçiminde yaz. "
    "Metin OCR çıktısıdır, harf hataları içerebilir; görsel varsa görseli esas al."
)


class LlmKatmani:
    def __init__(self, ayarlar):
        self.ayarlar = ayarlar
        self.aktif = ayarlar.getbool("LLM", "aktif")
        self.client = None
        if not self.aktif:
            return
        try:
            import anthropic

            anahtar = ayarlar.get("LLM", "api_anahtari") or None
            self.client = anthropic.Anthropic(api_key=anahtar) if anahtar else anthropic.Anthropic()
            self.anthropic = anthropic
        except Exception as e:
            log.error("LLM katmanı başlatılamadı: %s", e)
            self.aktif = False

    def alanlari_cikar(self, alanlar, metinler, gorsel_yollari=()):
        """
        alanlar : {anahtar: açıklama}  — doldurulması istenen alanlar
        metinler: [str]                 — ilgili sayfaların OCR/metin içeriği
        Döner   : {anahtar: değer|None}
        """
        if not (self.aktif and self.client and alanlar):
            return {}
        icerik = []
        if self.ayarlar.getbool("LLM", "gorsel_gonder"):
            for p in list(gorsel_yollari)[:4]:
                try:
                    icerik.append({
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": _png_b64(p)},
                    })
                except Exception as e:
                    log.warning("Görsel eklenemedi (%s): %s", os.path.basename(p), e)
        alan_listesi = "\n".join(f"- {k}: {v}" for k, v in alanlar.items())
        icerik.append({
            "type": "text",
            "text": "Belge metinleri:\n\n" + "\n\n-----\n\n".join(metinler)
                    + f"\n\nAşağıdaki alanları doldur:\n{alan_listesi}",
        })
        sema = {
            "type": "object",
            "properties": {k: {"type": ["string", "null"]} for k in alanlar},
            "required": list(alanlar),
            "additionalProperties": False,
        }
        a = self.anthropic
        try:
            yanit = self.client.beta.messages.create(
                model=self.ayarlar.get("LLM", "model") or "claude-opus-5-5",
                max_tokens=16000,
                system=SISTEM,
                messages=[{"role": "user", "content": icerik}],
                output_config={
                    "effort": self.ayarlar.get("LLM", "effort") or "medium",
                    "format": {"type": "json_schema", "schema": sema},
                },
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except a.AuthenticationError:
            log.error("LLM: API anahtarı geçersiz (ANTHROPIC_API_KEY)")
            return {}
        except a.RateLimitError:
            log.error("LLM: istek sınırı aşıldı, daha sonra tekrar deneyin")
            return {}
        except a.BadRequestError as e:
            log.error("LLM: geçersiz istek: %s", e.message)
            return {}
        except a.APIStatusError as e:
            log.error("LLM: API hatası (%s): %s", e.status_code, e.message)
            return {}
        except a.APIConnectionError:
            log.error("LLM: bağlantı hatası (internet/proxy)")
            return {}

        if yanit.stop_reason == "refusal":
            log.warning("LLM isteği reddetti, alanlar boş bırakıldı")
            return {}
        if yanit.stop_reason == "max_tokens":
            log.warning("LLM yanıtı kesildi, alanlar boş bırakıldı")
            return {}
        metin = next((b.text for b in yanit.content if b.type == "text"), "")
        try:
            veri = json.loads(metin)
        except json.JSONDecodeError:
            log.warning("LLM yanıtı JSON değil, yok sayıldı")
            return {}
        log.info("LLM %d alan önerdi (%s)", sum(1 for v in veri.values() if v), yanit.model)
        return {k: (str(v).strip() if v not in (None, "") else None) for k, v in veri.items() if k in alanlar}


def _png_b64(yol, max_kenar=1600):
    from PIL import Image

    img = Image.open(yol)
    img.thumbnail((max_kenar, max_kenar))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("ascii")
