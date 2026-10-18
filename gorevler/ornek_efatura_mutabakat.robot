*** Settings ***
Documentation     Türkiye bağlayıcıları örneği: e-Fatura (UBL-TR) + banka ekstresi (MT940) mutabakatı.
...               Gelen e-faturaları okur, Excel'e aktarır, döviz faturalarını TCMB kuruyla TL'ye çevirir,
...               banka ekstresindeki ödemelerle eşleştirir ve ödenmemiş faturaları raporlar.
...               Kendi dosyalarınız için:  --variable FATURA_KLASORU:C:\\Faturalar  --variable EKSTRE:C:\\ekstre.sta
Library           AlamountBaglayicilar
Library           AlamountRPA
Library           Collections

*** Variables ***
${FATURA_KLASORU}    ${CURDIR}${/}..${/}ornek_veri${/}efatura
${EKSTRE}            ${CURDIR}${/}..${/}ornek_veri${/}banka${/}ornek_ekstre.sta

*** Tasks ***
Fatura Banka Mutabakatı
    ${cikti}=    Klasör Yolu    KLASORLER    cikti
    @{faturalar}=    E-Fatura Klasörünü Oku    ${FATURA_KLASORU}
    E-Faturaları Excel'e Aktar    ${FATURA_KLASORU}    ${cikti}${/}faturalar.xlsx
    FOR    ${f}    IN    @{faturalar}
        ${gecerli}=    Vergi Numarası Geçerli Mi    ${f}[satici][vkn_tckn]
        IF    not ${gecerli}    Log    ${f}[fatura_no]: satıcı VKN geçersiz!    WARN
        IF    '${f}[para_birimi]' != 'TRY'    TL Karşılığını Yaz    ${f}
    END
    ${ekstre}=    MT940 Ekstresini Oku    ${EKSTRE}
    Should Be True    ${ekstre}[tutarli]    Ekstre bakiyesi tutarsız
    @{sonuc}=    Faturaları Ekstreyle Eşleştir    ${faturalar}    ${ekstre}    ${cikti}${/}mutabakat.xlsx
    FOR    ${s}    IN    @{sonuc}
        Log    ${s}[fatura_no] · ${s}[karsi_taraf] · ${s}[fatura_tutari] → ${s}[durum]    console=True
    END

*** Keywords ***
TL Karşılığını Yaz
    [Arguments]    ${f}
    # Faturada kur varsa onu, yoksa TCMB'nin fatura tarihindeki döviz satış kurunu kullan
    IF    $f['kur']
        ${kur}=    Set Variable    ${f}[kur]
    ELSE
        ${durum}    ${kur}=    Run Keyword And Ignore Error    Kur Al    ${f}[para_birimi]    ${f}[tarih]
        IF    '${durum}' == 'FAIL'
            Log    TCMB'ye ulaşılamadı: ${kur}    WARN
            RETURN
        END
    END
    ${tl}=    Evaluate    round(${f}[odenecek_tutar] * ${kur}, 2)
    Log    ${f}[fatura_no]: ${f}[odenecek_tutar] ${f}[para_birimi] × ${kur} = ${tl} TL    console=True
