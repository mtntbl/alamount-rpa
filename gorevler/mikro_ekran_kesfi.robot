*** Settings ***
Documentation     Açık Mikro penceresindeki ekran öğelerini (ağacı) listeler.
...               Çıktıdaki name / automationid / class değerleriyle
...               kaynaklar\\mikro_ekran_haritasi.resource dosyasını doldurun.
...               Kullanım: Mikro'da Personel Sicil Kartı ekranını açın, sonra:
...                   AlamountRPA.exe robot mikro_ekran_kesfi
Library           RPA.Windows
Library           AlamountRPA
Resource          kaynaklar/mikro_ekran_haritasi.resource

*** Variables ***
${PENCERE}        ${MIKRO_SICIL_PENCERE}
${DERINLIK}       12

*** Tasks ***
Mikro Ekran Ağacını Kaydet
    ${klasor}=    Klasör Yolu    ROBOT    cikti
    Control Window    ${PENCERE}    timeout=20
    Print Tree    max_depth=${DERINLIK}    capture_image_folder=${klasor}${/}ekran_kesfi    log_as_warnings=True
    Log    Ağaç log.html'e, öğe görüntüleri ${klasor}${/}ekran_kesfi klasörüne yazıldı    console=True
