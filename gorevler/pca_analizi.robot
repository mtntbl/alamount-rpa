*** Settings ***
Documentation     input klasöründeki veri dosyalarına PCA analizi uygular (PCA_Example.ipynb).
Library           AlamountRPA

*** Tasks ***
PCA Analizi
    ${sonuc}=    PCA Klasörünü İşle
    Log    Başarılı: ${sonuc}[0] / Hatalı: ${sonuc}[1]    console=True
    IF    ${sonuc}[1] > 0    Fail    ${sonuc}[1] dosya işlenemedi, error klasörüne bakın
