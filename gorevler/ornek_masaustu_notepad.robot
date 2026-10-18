*** Settings ***
Documentation     RPA.Windows ile masaüstü otomasyonu örneği:
...               Not Defteri'ni açar, son hazırlanan işe giriş özetini yazar, dosyaya kaydeder ve kapatır.
Library           RPA.Windows
Library           AlamountRPA
Library           OperatingSystem
Library           Process

*** Variables ***
${METIN}          Alamount RPA masaüstü testi

*** Tasks ***
Not Defteri Otomasyonu
    ${klasor}=    Klasör Yolu    KLASORLER    cikti
    ${hedef}=    Set Variable    ${klasor}${/}notepad_ornek.txt
    Remove File    ${hedef}
    ${ozet}=    Özet Metni Hazırla
    Start Process    notepad.exe
    Control Window    regex:.*(Notepad|Defteri|Untitled|Adsız).*    timeout=20
    Sleep    1s
    Send Keys    keys=${ozet}    interval=0.005
    Send Keys    keys={Ctrl}s
    Sleep    2s
    Send Keys    keys=${hedef}    send_enter=True
    Wait Until Created    ${hedef}    timeout=20s
    Close Current Window
    ${icerik}=    Get File    ${hedef}
    Should Contain    ${icerik}    Alamount RPA
    Log    Kaydedildi: ${hedef}    console=True

*** Keywords ***
Özet Metni Hazırla
    ${durum}=    Run Keyword And Ignore Error    Son Hazır Excel
    IF    '${durum}[0]' == 'PASS'
        @{alanlar}=    Excelden Giriş Verisi Oku    ${durum}[1]
        ${n}=    Get Length    ${alanlar}
        RETURN    ${METIN}{Enter}Son hazır dosya: ${durum}[1]{Enter}Girilecek alan sayısı: ${n}{Enter}
    END
    RETURN    ${METIN}{Enter}Henüz hazırlanmış işe giriş dosyası yok.{Enter}
