*** Settings ***
Documentation     Hazır Excel'deki verileri Mikro ERP > Personel Sicil Kartları (111100) ekranına girer.
...
...               ÖNEMLİ
...               - Varsayılan KURU ÇALIŞMA'dır: hiçbir tuşa basmaz, yalnızca ne gireceğini loglar.
...                 Gerçek giriş için config.ini [ROBOT] kuru_calisma = hayir ya da
...                 AlamountRPA.exe robot mikro_personel_giris --variable KURU_CALISMA:hayir
...               - Ekran öğelerinin yerleri (locator) kaynaklar\\mikro_ekran_haritasi.resource dosyasındadır.
...                 Kendi Mikro sürümünüze göre mikro_ekran_kesfi.robot ile çıkarıp düzenleyin.
...               - Mikro uzak masaüstünde (RDP) çalışıyorsa bot da O MAKİNEDE çalışmalıdır;
...                 RDP penceresinin içindeki öğeler yerel UI Automation'a görünmez.
...               - Kayıt tuşuna basılmaz (KAYDET=hayir): son kontrol ve kayıt insan tarafından yapılır.
Library           RPA.Windows
Library           AlamountRPA
Library           OperatingSystem
Library           Collections
Resource          kaynaklar/mikro_ekran_haritasi.resource

*** Variables ***
${EXCEL}            ${EMPTY}
${KURU_CALISMA}     ${NONE}
${KAYDET}           hayir

*** Tasks ***
Mikro Personel Sicil Kartı Girişi
    ${kuru}=    Kuru Çalışma Mı    ${KURU_CALISMA}
    ${excel}=    Set Variable If    '${EXCEL}' == ''    ${EMPTY}    ${EXCEL}
    IF    '${excel}' == ''
        ${excel}=    Son Hazır Excel
    END
    Log    Kaynak: ${excel} | Kuru çalışma: ${kuru}    console=True
    @{alanlar}=    Excelden Giriş Verisi Oku    ${excel}
    ${log_klasoru}=    Klasör Yolu    ROBOT    cikti
    IF    not ${kuru}
        Control Window    ${MIKRO_PENCERE}    timeout=20
        Personel Sicil Kartını Aç
    END
    FOR    ${ekran}    IN RANGE    1    6
        Ekrana Geç    ${ekran}    ${kuru}
        FOR    ${a}    IN    @{alanlar}
            IF    ${a}[ekran] == ${ekran}    Alana Yaz    ${a}    ${kuru}
        END
        IF    not ${kuru}
            Screenshot    ${MIKRO_PENCERE}    ${log_klasoru}${/}mikro_ekran_${ekran}.png
        END
    END
    IF    not ${kuru} and '${KAYDET}' == 'evet'
        Click    ${MIKRO_KAYDET}
        Log    Kayıt tuşuna basıldı    console=True
    ELSE
        Log    Form dolduruldu; kontrol edip kaydetmek size kalmış.    console=True
    END

*** Keywords ***
Personel Sicil Kartını Aç
    [Documentation]    MikroJump arama kutusuna ekran kodunu yazıp açar.
    Send Keys    keys=${MIKRO_JUMP_KISAYOL}
    Send Keys    keys=${MIKRO_EKRAN_KODU}    send_enter=True
    Control Window    ${MIKRO_SICIL_PENCERE}    timeout=20

Ekrana Geç
    [Arguments]    ${ekran}    ${kuru}
    ${anahtar}=    Convert To String    ${ekran}
    ${sekme}=    Set Variable    ${MIKRO_SEKMELER}[${anahtar}]
    IF    ${kuru}
        Log    [KURU] Sekme: ${sekme}    console=True
    ELSE
        Click    ${sekme}
    END

Alana Yaz
    [Arguments]    ${a}    ${kuru}
    ${no}=    Convert To String    ${a}[no]
    ${var}=    Run Keyword And Return Status    Dictionary Should Contain Key    ${MIKRO_ALANLAR}    ${no}
    IF    not ${var}
        Log    Ekran haritasında yok, atlandı: ${no}. ${a}[alan]    level=WARN
        RETURN
    END
    ${locator}=    Set Variable    ${MIKRO_ALANLAR}[${no}]
    ${tip}=    Evaluate    $MIKRO_ALAN_TIPLERI.get($no, 'metin')
    IF    ${kuru}
        Log    [KURU] ${no}. ${a}[alan] → '${a}[deger]' (${tip} | ${locator})    console=True
    ELSE IF    '${tip}' == 'liste'
        Select    ${locator}    ${a}[deger]
    ELSE
        Set Value    ${locator}    ${a}[deger]
    END
