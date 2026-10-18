*** Settings ***
Documentation     RPA.Browser.Selenium ile tarayıcı otomasyonu örneği:
...               Örnek web formunu (kaynaklar\\ornek_form.html) açar, son hazır işe giriş
...               verisiyle doldurur, ekran görüntüsü alır ve gönderir.
...               Gerçek bir web uygulaması için URL ve locator'ları değiştirin.
Library           RPA.Browser.Selenium    auto_close=${TRUE}
Library           AlamountRPA
Library           OperatingSystem

*** Variables ***
${HEADLESS}       ${TRUE}

*** Tasks ***
Web Formunu Doldur
    ${klasor}=    Klasör Yolu    ROBOT    cikti
    ${form}=    Normalize Path    ${CURDIR}${/}kaynaklar${/}ornek_form.html
    ${url}=    Evaluate    pathlib.Path(r'''${form}''').as_uri()    modules=pathlib
    ${veri}=    Form Verisi
    Open Available Browser    ${url}    headless=${HEADLESS}
    Input Text    id:tc          ${veri}[43]
    Input Text    id:giris       ${veri}[1]
    Input Text    id:telefon     ${veri}[14]
    Input Text    id:dogum       ${veri}[28]
    Select From List By Label    id:cinsiyet    ${veri}[25]
    Capture Page Screenshot    ${klasor}${/}tarayici_form.png
    Click Button    id:gonder
    Wait Until Element Contains    id:sonuc    Kaydedildi    timeout=10s
    ${sonuc}=    Get Text    id:sonuc
    Log    ${sonuc}    console=True
    [Teardown]    Close All Browsers

*** Keywords ***
Form Verisi
    ${durum}=    Run Keyword And Ignore Error    Son Hazır Excel
    IF    '${durum}[0]' == 'PASS'
        @{alanlar}=    Excelden Giriş Verisi Oku    ${durum}[1]
        ${veri}=    Evaluate    {str(a['no']): a['deger'] for a in $alanlar}
        FOR    ${k}    IN    1    14    25    28    43
            Set To Dictionary If Missing    ${veri}    ${k}
        END
        RETURN    ${veri}
    END
    ${veri}=    Create Dictionary    1=01.01.2026    14=0500 000 00 00    25=Erkek    28=01.01.1990    43=10000000146
    RETURN    ${veri}

Set To Dictionary If Missing
    [Arguments]    ${sozluk}    ${anahtar}
    IF    $anahtar not in $sozluk    Evaluate    $sozluk.__setitem__($anahtar, '')
