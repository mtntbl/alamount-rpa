*** Settings ***
Documentation     İşe giriş belgelerini hazırlar.
...               input\\ise_giris klasöründeki <TC>.pdf dosyalarını OCR ile okur, Puantaj'la TC üzerinden
...               eşleştirir, checklist kurallarını uygular ve girişe hazır Excel üretir.
Library           AlamountRPA
Library           RPA.FileSystem

*** Tasks ***
İşe Giriş Belgelerini Hazırla
    ${sonuclar}=    İşe Giriş Klasörünü İşle
    ${hata}=    Set Variable    ${0}
    FOR    ${s}    IN    @{sonuclar}
        IF    'hata' in ${s}
            Log    HATA ${s}[dosya]: ${s}[hata]    level=WARN
            ${hata}=    Evaluate    ${hata} + 1
        ELSE
            Log    Hazır: ${s}[excel]    console=True
            Log    Durum özeti: ${s}[ozet]    console=True
            FOR    ${u}    IN    @{s}[uyarilar]
                Log    Dikkat: ${u}    level=WARN
            END
        END
    END
    IF    ${hata} > 0    Fail    ${hata} personel dosyası işlenemedi (error\\ise_giris)
