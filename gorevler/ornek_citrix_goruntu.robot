*** Settings ***
Documentation     Görüntü tabanlı otomasyon örneği (Citrix / RDP / uzak masaüstü).
...               Demo penceresinde UI Automation öğesi yoktur; ekran yalnızca piksellerden oluşur,
...               tıpkı Citrix'te yayınlanan bir uygulama gibi. Robot alanları ekrandaki yazıdan (OCR),
...               düğmeyi şablon görüntüsünden (goruntuler\demo_giris_dugmesi.png) bulur.
...               Kendi ekranınız için şablon kesmek:  AlamountRPA.exe goruntu-yakala AD
Library           AlamountGoruntu
Library           AlamountRPA
Library           OperatingSystem

*** Variables ***
${KULLANICI}      robot
# Gerçek görevde parolayı merkezin kasasından alın:  ${parola}=    Varlık Al    CITRIX_GIRIS
${PAROLA}         Demo1234

*** Tasks ***
Uzak Masaüstünde Giriş Yap
    ${klasor}=    Klasör Yolu    KLASORLER    cikti
    ${sonuc}=    Set Variable    ${klasor}${/}citrix_demo_sonuc.json
    Remove File    ${sonuc}
    Demo Uygulamasını Başlat    ${sonuc}
    Yazı Görünene Kadar Bekle    Kullanıcı adı    zaman_asimi=30
    # Etiketin 38 piksel altındaki kutuya tıkla ve yaz
    Yazıya Tıkla    Kullanıcı adı    y_kaydir=38
    Yaz    ${KULLANICI}
    Yazıya Tıkla    Parola    y_kaydir=38
    Yaz    ${PAROLA}
    Görüntüye Tıkla    demo_giris_dugmesi
    ${karsilama}=    Yazı Görünene Kadar Bekle    Hoş geldiniz    zaman_asimi=15
    ${metin}=    Ekrandaki Yazıyı Oku    bolge=${karsilama}[sol],${karsilama}[ust],480,140
    Log    Ekrandan okunan:\n${metin}    console=True
    Should Match Regexp    ${metin}    (?i)fatura
    Wait Until Created    ${sonuc}    timeout=10s
    ${json}=    Get File    ${sonuc}
    Should Contain    ${json}    "kullanici": "${KULLANICI}"
    [Teardown]    Tuşa Bas    esc
