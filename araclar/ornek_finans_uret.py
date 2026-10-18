# -*- coding: utf-8 -*-
"""Örnek e-Fatura (UBL-TR) ve MT940 ekstre dosyalarını üretir (kurgusal firmalar).
Kullanım: python araclar/ornek_finans_uret.py ornek_veri"""
import os
import sys
import uuid
import zipfile
from decimal import ROUND_HALF_UP, Decimal

HEDEF = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ornek_veri")
ALICI = ("Alamount Teknoloji A.Ş.", "1234567890", "Kozyatağı", "İstanbul", "Ataşehir")
FATURALAR = [
    ("ORN2026000000123", "2026-10-02", "TICARIFATURA", "SATIS", "TRY", None,
     ("Örnek Kırtasiye Ltd. Şti.", "4820156735", "Kadıköy", "İstanbul", "Kadıköy"),
     [("A4 Fotokopi Kağıdı (koli)", 20, "C62", "640.00", 20), ("Toner Kartuşu", 4, "C62", "1850.00", 20)]),
    ("ORN2026000000124", "2026-10-05", "TEMELFATURA", "SATIS", "TRY", None,
     ("Güneş Bilişim Hizmetleri A.Ş.", "7301942583", "Çankaya", "Ankara", "Çankaya"),
     [("Sunucu Bakım Hizmeti (Ekim)", 1, "C62", "12500.00", 20), ("Yedekleme Lisansı", 3, "C62", "750.00", 20)]),
    ("ORN2026000000125", "2026-10-08", "TICARIFATURA", "SATIS", "USD", "41.9210",
     ("Ege Yazılım Danışmanlık A.Ş.", "6152839049", "Bornova", "İzmir", "Bornova"),
     [("Bulut Altyapı Aboneliği", 1, "C62", "980.00", 20)]),
]
NS = ('xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
      'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
      'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"')


def k(d):
    return Decimal(d).quantize(Decimal("0.01"), ROUND_HALF_UP)


def taraf(kok, t):
    ad, vkn, vd, il, ilce = t
    return f"""<cac:{kok}><cac:Party>
  <cac:PartyIdentification><cbc:ID schemeID="VKN">{vkn}</cbc:ID></cac:PartyIdentification>
  <cac:PartyName><cbc:Name>{ad}</cbc:Name></cac:PartyName>
  <cac:PostalAddress><cbc:CitySubdivisionName>{ilce}</cbc:CitySubdivisionName><cbc:CityName>{il}</cbc:CityName>
    <cac:Country><cbc:Name>Türkiye</cbc:Name></cac:Country></cac:PostalAddress>
  <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>{vd}</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
</cac:Party></cac:{kok}>"""


def fatura(no, tarih, senaryo, tip, pb, kur, satici, satirlar):
    xs, toplam, kdv = [], Decimal(0), Decimal(0)
    for i, (urun, miktar, birim, fiyat, oran) in enumerate(satirlar, 1):
        tutar = k(Decimal(fiyat) * miktar)
        v = k(tutar * oran / 100)
        toplam += tutar
        kdv += v
        xs.append(f"""<cac:InvoiceLine><cbc:ID>{i}</cbc:ID>
  <cbc:InvoicedQuantity unitCode="{birim}">{miktar}</cbc:InvoicedQuantity>
  <cbc:LineExtensionAmount currencyID="{pb}">{tutar}</cbc:LineExtensionAmount>
  <cac:TaxTotal><cbc:TaxAmount currencyID="{pb}">{v}</cbc:TaxAmount><cac:TaxSubtotal>
    <cbc:TaxableAmount currencyID="{pb}">{tutar}</cbc:TaxableAmount><cbc:TaxAmount currencyID="{pb}">{v}</cbc:TaxAmount>
    <cbc:Percent>{oran}</cbc:Percent><cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name>
    <cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
  <cac:Item><cbc:Name>{urun}</cbc:Name></cac:Item>
  <cac:Price><cbc:PriceAmount currencyID="{pb}">{fiyat}</cbc:PriceAmount></cac:Price>
</cac:InvoiceLine>""")
    kur_xml = (f"<cac:PricingExchangeRate><cbc:SourceCurrencyCode>{pb}</cbc:SourceCurrencyCode>"
               f"<cbc:TargetCurrencyCode>TRY</cbc:TargetCurrencyCode><cbc:CalculationRate>{kur}</cbc:CalculationRate>"
               f"</cac:PricingExchangeRate>") if kur else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice {NS}>
<cbc:UBLVersionID>2.1</cbc:UBLVersionID><cbc:CustomizationID>TR1.2</cbc:CustomizationID>
<cbc:ProfileID>{senaryo}</cbc:ProfileID><cbc:ID>{no}</cbc:ID>
<cbc:UUID>{uuid.uuid5(uuid.NAMESPACE_URL, no)}</cbc:UUID>
<cbc:IssueDate>{tarih}</cbc:IssueDate><cbc:IssueTime>10:15:00</cbc:IssueTime>
<cbc:InvoiceTypeCode>{tip}</cbc:InvoiceTypeCode>
<cbc:Note>Örnek fatura — Alamount RPA test verisi</cbc:Note>
<cbc:DocumentCurrencyCode>{pb}</cbc:DocumentCurrencyCode><cbc:LineCountNumeric>{len(satirlar)}</cbc:LineCountNumeric>
{taraf("AccountingSupplierParty", satici)}
{taraf("AccountingCustomerParty", ALICI)}
{kur_xml}
<cac:TaxTotal><cbc:TaxAmount currencyID="{pb}">{k(kdv)}</cbc:TaxAmount><cac:TaxSubtotal>
  <cbc:TaxableAmount currencyID="{pb}">{k(toplam)}</cbc:TaxableAmount><cbc:TaxAmount currencyID="{pb}">{k(kdv)}</cbc:TaxAmount>
  <cbc:Percent>20</cbc:Percent><cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name>
  <cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal></cac:TaxTotal>
<cac:LegalMonetaryTotal>
  <cbc:LineExtensionAmount currencyID="{pb}">{k(toplam)}</cbc:LineExtensionAmount>
  <cbc:TaxExclusiveAmount currencyID="{pb}">{k(toplam)}</cbc:TaxExclusiveAmount>
  <cbc:TaxInclusiveAmount currencyID="{pb}">{k(toplam + kdv)}</cbc:TaxInclusiveAmount>
  <cbc:AllowanceTotalAmount currencyID="{pb}">0.00</cbc:AllowanceTotalAmount>
  <cbc:PayableAmount currencyID="{pb}">{k(toplam + kdv)}</cbc:PayableAmount>
</cac:LegalMonetaryTotal>
{"".join(xs)}
</Invoice>
""", k(toplam + kdv)


def main():
    kl = os.path.join(HEDEF, "efatura")
    os.makedirs(kl, exist_ok=True)
    tutarlar = {}
    for i, f in enumerate(FATURALAR):
        xml, tutar = fatura(*f)
        tutarlar[f[0]] = tutar
        if i == 2:  # entegratörden ZIP olarak inen fatura
            with zipfile.ZipFile(os.path.join(kl, f"{f[0]}.zip"), "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr(f"{f[0]}.xml", xml)
        else:
            open(os.path.join(kl, f"{f[0]}.xml"), "w", encoding="utf-8").write(xml)
    # MT940: ilk fatura açıklamadaki fatura numarasıyla, ikincisi yalnızca tutarla ödenmiş; üçüncüsü ödenmemiş
    t1, t2 = tutarlar["ORN2026000000123"], tutarlar["ORN2026000000124"]
    acilis = Decimal("250000.00")
    gelen = Decimal("18400.00")
    kapanis = acilis - t1 - t2 + gelen
    tr = lambda d: f"{d:.2f}".replace(".", ",")  # noqa: E731
    mt = f""":20:ALM20261010
:25:TR330006100519786457841326
:28C:00194/001
:60F:C261001TRY{tr(acilis)}
:61:2610061006D{tr(t1)}NTRFEFT2026100601//B2610061234
:86:EFT ORNEK KIRTASIYE LTD STI FATURA ORN2026000000123 ODEMESI
:61:2610081008C{tr(gelen)}NTRFHAVALE01//B2610089876
:86:GELEN HAVALE MUSTERI A.S. EKIM HAKEDIS
:61:2610091009D{tr(t2)}NTRFEFT2026100902//B2610095555
:86:EFT GUNES BILISIM HIZMETLERI
 EKIM BAKIM BEDELI
:62F:C261010TRY{tr(kapanis)}
-
"""
    kb = os.path.join(HEDEF, "banka")
    os.makedirs(kb, exist_ok=True)
    open(os.path.join(kb, "ornek_ekstre.sta"), "w", encoding="utf-8").write(mt)
    print("Üretildi:", kl, kb)


if __name__ == "__main__":
    main()
