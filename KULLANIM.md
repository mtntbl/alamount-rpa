<p align="center"><img src="marka/logo.png" alt="Alamount RPA" width="420"></p>

# Alamount RPA – Kullanım Kılavuzu

Altı katmanlı bir robot. Hepsi tek pakette ve `AlamountRPA.exe` üzerinden çalışır:

| Katman | Teknoloji | Ne yapar |
|---|---|---|
| Orkestrasyon | **Robot Framework** | `gorevler\*.robot` görevleri, log/rapor (`logs\robot\…\log.html`), tekrarlanabilirlik |
| Masaüstü & tarayıcı | **rpaframework** | `RPA.Windows` (UI Automation), `RPA.Browser.Selenium`, `RPA.Excel`, `RPA.PDF` |
| Citrix / RDP | **opencv · Tesseract** | UI Automation'ın göremediği ekranlarda görüntü ve yazı bularak tıklar, yazar (bölüm 4a) |
| Bağlayıcılar | **rpaframework · AlamountBaglayicilar** | E-posta, Outlook/Exchange, SAP GUI, veritabanı, REST, Microsoft 365; e-Fatura, TCMB kuru, MT940 (bölüm 4b) |
| Belge → görsel | **pymupdf · Pillow · opencv** | PDF sayfasını görsele çevirir; kimlik kartını bulup eğimini düzelterek kırpar |
| OCR | **pytesseract + Tesseract** | Yerel (internetsiz) Türkçe metin okuma; taranmış sayfalar otomatik algılanır |
| Veri & çıktı | **openpyxl · re** | Puantaj Excel'ini okur, TC ile eşleştirir, girişe hazır Excel yazar |
| Ajan katmanı (opsiyonel) | **anthropic · MCP** | OCR'ın okuyamadığı alanları Claude'a sordurur; robotu Claude Desktop'a araç olarak açar |

Ayrıca ilk sürümdeki **PCA analizi** de aynen duruyor. Birden fazla robot makinesi varsa **Kontrol Merkezi**
(web paneli, kuyruklar, zamanlamalar, şifreli kasa, bildirimler) bir makinede çalışır, robotlar oradan iş alır — bkz. bölüm 6.
Hiçbir parçası Claude'a, internete ya da başka bir lisansa bağlı değildir.

---

## Hızlı başlangıç

1. `AlamountRPA_Windows.zip` dosyasını bir klasöre çıkarın (ör. `C:\AlamountRPA`).
2. `AlamountRPA.exe`'ye çift tıklayın. Bir menü açılır:

```
  1. PCA analizi (input klasörü)
  2. İşe giriş belgelerini hazırla (input\ise_giris)
  3. Mikro'ya giriş — KURU ÇALIŞMA (yalnızca log)
  4. Mikro'ya giriş — GERÇEK (Mikro açık olmalı)
  5. Mikro ekran keşfi (locator çıkarma)
  6. Örnek: Not Defteri otomasyonu
  7. Örnek: Tarayıcı formu doldurma
  8. Örnek: Citrix/uzak masaüstü (görüntü + OCR)
  9. Kurulum kontrolü
 10. Kontrol Merkezi'ni başlat (sunucu makinesi)
 11. Robot ajanını başlat (robot makinesi)
```

3. İlk iş olarak **9 – Kurulum kontrolü**'nü çalıştırın. Tesseract, Türkçe dil paketi ve kütüphaneler `[OK]` görünmeli.
4. Denemek için `ornek_veri\ise_giris\` içindeki dosyaları `input\ise_giris\` klasörüne kopyalayıp **2**'yi seçin.
   Bu dosyalar **kurgusal** test verisidir.

> Windows SmartScreen uyarısında **Ek bilgi → Yine de çalıştır** deyin (exe imzasızdır).
> ARM64 Windows'ta paket x64 emülasyonuyla çalışır.

## Komut satırı

```
AlamountRPA.exe kontrol                                   kurulum kontrolü
AlamountRPA.exe ise-giris                                 input\ise_giris klasörünü işler
AlamountRPA.exe ise-giris --tc 12345678901 --pdf D:\belge.pdf [--puantaj D:\PUANTAJ.xlsx]
AlamountRPA.exe ocr D:\taranmis.pdf --cikti D:\metin.txt  taranmış PDF → metin
AlamountRPA.exe pca --once | --watch | --file D:\veri.txt PCA analizi
AlamountRPA.exe robot <görev> [Robot seçenekleri]         ör. robot mikro_personel_giris --variable KURU_CALISMA:hayir
AlamountRPA.exe gorevler                                  görev listesi
AlamountRPA.exe goruntu-yakala AD                         Citrix/RDP: ekrandan şablon keser (bölüm 4a)
AlamountRPA.exe goruntu-dene AD                           şablonu şu anki ekranda arar, eşleşme skorunu yazar
AlamountRPA.exe oturum-kur --kullanici .\robot1           gözetimsiz robot: oturumu robot açar (bölüm 6, yönetici)
AlamountRPA.exe oturum-durum | oturum-kaldir              gözetimsiz oturum durumu / geri alma
AlamountRPA.exe mcp                                       MCP sunucusu (Claude Desktop için)
AlamountRPA.exe merkez | ajan                             Kontrol Merkezi / robot ajanı (bölüm 6)
AlamountRPA.exe kuyruk ise-giris-dagit | ise-giris-isle   merkez kuyruğuyla işe giriş
--config D:\baska.ini                                 farklı ayar dosyası
```

Çıkış kodu `0` = başarılı, `1` = hata. UiPath, Power Automate gibi araçlardan çağırırken bu kod kullanılabilir.

---

## 1) İşe giriş belgelerini hazırlama

**Girdi (`input\ise_giris\`):**
- `PUANTAJ BİLGİLERİ.xlsx` – **GİRİŞ** sayfası. Başlık satırı otomatik bulunur. Aranan sütunlar: TC KİMLİK NO, ADI SOYADI,
  DOĞUM TARİHİ, EMEKLİ Mİ DEĞİLMİ, BİRİM, İŞE GİRİŞ TARİHİ, MESLEK, EĞİTİM DURUMU, IBN NO, TELEFON NUMARASI.
- Her personel için tek PDF, adı TC numarası olmalı (ör. `12345678901.pdf`). Dosya adında TC yoksa PDF'in içinde aranır.

**Robot ne yapar:**
1. Her sayfayı açar. Metin katmanı yoksa sayfa taranmış kabul edilir ve Tesseract ile Türkçe OCR yapılır.
2. Sayfanın belge türünü bulur: kimlik kartı, nüfus kayıt örneği, yerleşim yeri belgesi, adli sicil, diploma, sertifika.
3. Fotoğraflanmış ya da fotokopisi çekilmiş kimlik kartını bulur, eğimini düzeltip kırpar ve ayrıca okur (seri no, cinsiyet, doğum tarihi…).
4. Puantaj'la **TC üzerinden** eşleştirir. TC algoritma kontrolünü ve PDF'teki TC ile çapraz doğrulamayı yapar.
5. Checklist kurallarını uygular:
   - Ana Kanun: emekli değil → `01`, emekli → `02`
   - Kanun 2: emekli değil → `5510`, emekli → `0000`. **SEDEF istisnası:** birim SEDEF ise her zaman `0000` (`[ISE_GIRIS] sedef_birimleri`)
   - Ücret tipi her zaman **Aylık**, hesap tipi **Diğer**, çalışma kodu **0**
   - **Ücret kasıtlı olarak boş bırakılır**
   - Sicil, SGK şubesi, entegre grubu, banka ödemesi, meslek ve görev kodu → **HR ONAYI GEREKLİ** (biriminize göre öneri yazılır)
   - Çelişkiler not edilir (ör. sertifikadaki meslek ≠ Puantaj'daki meslek, doğum tarihi uyuşmazlığı, IBAN kontrol hanesi hatası)
   - Eski cüzdana özgü alanlar uydurulmaz → **Bilgi Yok**
6. Çıktı: `output\ise_giris\<AD SOYAD (TC)>_<tarih>\İşe Girişi Hazır - AD SOYAD (TC).xlsx`
   - 5 ekran başlığı altında No / Alan / Değer / Durum / Not / Kaynak
   - Renkler: **sarı** = HR onayı, **gri** = bilgi yok, **turuncu** = LLM önerisi
   - Ayrıca `hazir_veri.json` ve `gorseller\` (sayfa görüntüleri + kırpılmış kimlik) oluşur
7. İşlenen PDF `archive\ise_giris\`, hatalı olan `error\ise_giris\` klasörüne taşınır (yanında `.hata.txt` açıklaması olur).

## 2) Mikro ERP'ye giriş (RPA.Windows)

`gorevler\mikro_personel_giris.robot` dosyası hazır Excel'i okur ve **Personel Sicil Kartları (111100)** ekranının 5 sekmesini doldurur.

**Güvenlik önlemleri:**
- Varsayılan olarak **kuru çalışma** açıktır: robot tuşa basmaz, ne gireceğini yalnızca loglar.
  Gerçek giriş için `config.ini` → `[ROBOT] kuru_calisma = hayir` yapın ya da menüden **4**'ü seçin.
- Durum'u **HR ONAYI GEREKLİ** veya **LLM - KONTROL EDİN** olan satırlar, HR Durum hücresini **ONAYLANDI** yapmadıkça girilmez.
- **Kaydet tuşuna basılmaz.** Kontrol ve kayıt insan tarafından yapılır.
  Otomatik kayıt için: `--variable KAYDET:evet`.

**İlk kurulum – ekran haritası (bir kez yapılır):**
Mikro'daki alan adları sürüme göre değişir. `gorevler\kaynaklar\mikro_ekran_haritasi.resource` dosyası bir **şablondur**.
1. Mikro'da Personel Sicil Kartı ekranını açın.
2. Menüden **5 – Mikro ekran keşfi**'ni çalıştırın. Ekrandaki öğeler `logs\robot\…\log.html` dosyasına yazılır,
   öğe görüntüleri de `ekran_kesfi\` klasörüne kaydedilir.
3. Her alanın `name` / `automationid` değerini haritaya yazın (ör. `1=name:"Giriş Tarihi"` ya da `1=id:txtGirisTarihi`).
   Açılır listeleri `MIKRO_ALAN_TIPLERI` içinde `liste` olarak işaretleyin.
4. Önce kuru çalışmayla, sonra gerçek modda deneyin.

> **Mikro uzak masaüstündeyse (RDP):** RDP penceresinin içindeki öğeler yerel UI Automation'a görünmez.
> Robotu Mikro'nun çalıştığı (uzak) makineye kurun.

## 3) OCR (taranmış PDF → metin)

```
AlamountRPA.exe ocr D:\taranmis.pdf --cikti D:\metin.txt
```
Ayarlar `[OCR]` bölümündedir: `dil = tur+eng`, `dpi = 300`, `psm_belge` / `psm_kimlik` (belge türüne göre sayfa bölümleme modu).
Tesseract paketin `tesseract\` klasöründe gelir. Başka bir kurulum kullanmak için `tesseract_yolu` ayarını değiştirin.

## 4) Robot Framework görevleri

`gorevler\` klasöründeki `.robot` dosyaları düz metindir; Not Defteri'yle düzenlenebilir.
Bot kendi anahtar kelimelerini `AlamountRPA` kütüphanesiyle sunar:
`İşe Giriş Klasörünü İşle`, `İşe Giriş Verisi Hazırla`, `PDF Metne Çevir`, `PDF Sayfalarını Görsele Çevir`,
`Kimlik Kartlarını Kırp`, `Görselde OCR Yap`, `Excelden Giriş Verisi Oku`, `Son Hazır Excel`, `PCA Klasörünü İşle`,
`Ayarı Oku`, `Klasör Yolu`, `TC Geçerli Mi` …
Bunları RPA.Windows, RPA.Browser.Selenium, RPA.Excel.Files gibi kütüphanelerle birlikte kullanabilirsiniz.
Her çalıştırmanın raporu `logs\robot\<görev>_<tarih>\log.html` dosyasındadır.

| Görev | Açıklama |
|---|---|
| `ise_giris_hazirla` | input\ise_giris klasörünü işler |
| `mikro_personel_giris` | Hazır Excel → Mikro ekranı (varsayılan kuru çalışma) |
| `mikro_ekran_kesfi` | Mikro ekranındaki öğeleri listeler (haritayı doldurmak için) |
| `ornek_masaustu_notepad` | RPA.Windows örneği: Not Defteri'ni aç, yaz, kaydet |
| `ornek_tarayici` | RPA.Browser örneği: web formunu doldur, ekran görüntüsü al |
| `ornek_citrix_goruntu` | Görüntü otomasyonu örneği: yalnızca piksellerden oluşan ekranda giriş yap (bölüm 4a) |
| `ornek_efatura_mutabakat` | e-Fatura + MT940 ekstre mutabakatı, TCMB kuruyla TL karşılığı (bölüm 4b) |
| `pca_analizi` | PCA analizi |

## 4a) Citrix / RDP: görüntü tabanlı otomasyon

Citrix, RDP, VDI ya da eski uygulamalarda ekran yalnızca bir resimdir; `RPA.Windows` içindeki öğeleri göremez.
`AlamountGoruntu` kütüphanesi ekranı gerçek bir kullanıcı gibi görür:

- **Şablon görüntüsü** (düğme, simge, alan) OpenCV ile aranır. %100, %125 ve %150 ekran ölçeklendirmesi ile
  Citrix çözünürlük farkları otomatik denenir.
- **Yazı**, Türkçe OCR ile aranır. Büyük/küçük harf, Türkçe karakter farkı ve küçük OCR hataları yok sayılır;
  koyu temalı ekranlar da okunur.
- Fare ve klavye gerçek kullanıcı gibi kullanılır (Türkçe karakterler dahil).
- Aranan şey bulunamazsa ekran görüntüsü Robot raporuna eklenir. Hatayı görmek için ekrana bakmak yeter.

**Şablon kesmek:** hedef ekranı açın ve `AlamountRPA.exe goruntu-yakala giris_dugmesi` çalıştırın.
3 saniye sonra ekran donar; fareyle alanı seçin. Şablon `gorevler\goruntuler\giris_dugmesi.png` olarak kaydedilir.
Aynı görüntü ekranda birden çok kez varsa araç uyarır. `goruntu-dene giris_dugmesi` şablonun o anda ekranda bulunup
bulunmadığını ve eşleşme skorunu gösterir.

```robotframework
*** Settings ***
Library    AlamountGoruntu
Library    AlamountRPA

*** Tasks ***
Citrix Uygulamasına Giriş
    ${parola}=    Varlık Al    CITRIX_GIRIS
    Yazı Görünene Kadar Bekle    Kullanıcı adı    zaman_asimi=60
    Yazıya Tıkla    Kullanıcı adı    y_kaydir=38          # etiketin altındaki kutu
    Yaz    robot1
    Tuşa Bas    tab
    Yaz    ${parola}
    Görüntüye Tıkla    giris_dugmesi
    Görüntü Kaybolana Kadar Bekle    yukleniyor_simgesi
    ${tutar}=    Ekrandaki Yazıyı Oku    bolge=820,310,200,40
```

| Anahtar kelime | Ne yapar |
|---|---|
| `Görüntüye Tıkla` / `Yazıya Tıkla` | Bulur ve tıklar; `tiklama=sağ/çift`, `x_kaydir`/`y_kaydir` ile yanındaki alana tıklar |
| `Görüntüyü Bul` / `Yazıyı Bul` | Konumu döner (`x`, `y`, `sol`, `ust`, `genislik`, `yukseklik`, `skor`) |
| `Görüntü Var Mı` / `Yazı Var Mı` / `Görüntü Sayısı` | Beklemeden kontrol eder |
| `Görüntü Görünene Kadar Bekle` / `Yazı Görünene Kadar Bekle` / `Görüntü Kaybolana Kadar Bekle` | Ekran değişimini bekler |
| `Ekrandaki Yazıyı Oku` | Ekrandaki (ya da bölgedeki) yazıyı satır satır döner |
| `Yaz` / `Tuşa Bas` / `Koordinata Tıkla` / `Fareyi Götür` / `Ekran Görüntüsü Al` | Klavye, fare ve ekran görüntüsü |

İpuçları:
- Aramayı `bolge=x,y,genişlik,yükseklik` ile daraltın. OCR tüm ekranda 1–3 sn sürer, küçük bir bölgede çok daha hızlıdır.
- Şablonu ayırt edici kesin: yalnızca düğmenin içini değil, üstündeki yazıyı da alın.
- Yavaş uzak masaüstlerinde `Yaz    metin    aralik=0.05` kullanın.
- Robot, uzak masaüstünü açık ve **kilitsiz** bir Windows oturumunda görmelidir. Gözetimsiz çalışma için bölüm 6'ya bakın.

## 4b) Bağlayıcılar

Genel bağlayıcılar pakette hazır gelir; `.robot` görevinde `Library` satırıyla kullanılır:

| Kütüphane | Ne için |
|---|---|
| `RPA.Email.ImapSmtp` / `RPA.Email.Exchange` | Gelen kutusunu okuma, ek indirme, e-posta gönderme (IMAP/SMTP, Exchange/Office 365) |
| `RPA.Outlook.Application` | Masaüstü Outlook'u kullanma |
| `RPA.SAP` | SAP GUI otomasyonu (SAP GUI Scripting açık olmalı) |
| `RPA.Database` | SQL Server (`pyodbc`), PostgreSQL (`psycopg2`), Oracle (`oracledb`), MySQL (`pymysql`) |
| `RPA.HTTP` | REST/HTTP servisleri, dosya indirme |
| `RPA.FTP` | FTP / FTPS |
| `RPA.MSGraph` | Microsoft 365: OneDrive, SharePoint, Outlook (Graph API) |
| `RPA.Cloud.Azure` | Azure servisleri (Document Intelligence, Key Vault…) |
| `RPA.Salesforce` | Salesforce kayıtları |
| `RPA.Word.Application` / `RPA.Excel.Application` | Masaüstü Word ve Excel (makro, formül, yazdırma) |
| `RPA.Archive` / `RPA.JSON` / `RPA.Crypto` | ZIP, JSON, şifreleme |

Türkiye'ye özel bağlayıcılar `AlamountBaglayicilar` kütüphanesindedir:

| Anahtar kelime | Ne yapar |
|---|---|
| `E-Fatura Oku` / `E-Fatura Klasörünü Oku` | UBL-TR XML ya da entegratör ZIP'inden faturayı okur. Satıcı/alıcı VKN, vergi dairesi, satırlar, KDV, tevkifat, döviz ve kur alanlarını çıkarır. Satır toplamı ile KDV tutarsızlığını ve geçersiz VKN'yi uyarı olarak işaretler |
| `E-Faturaları Excel'e Aktar` | "Faturalar" ve "Satırlar" sayfalı Excel; okunamayan dosyalar ayrı sayfada |
| `TCMB Kurlarını Al` / `Kur Al` | TCMB gösterge kurları (döviz/efektif alış-satış). Geçmiş tarih verilebilir; hafta sonu ve tatilde önceki iş günü kullanılır |
| `MT940 Ekstresini Oku` / `Ekstreyi Excel'e Aktar` | Banka ekstresi (MT940, UTF-8 ya da Windows-1254). Açılış + hareketler = kapanış kontrolü yapılır |
| `Faturaları Ekstreyle Eşleştir` | Fatura–banka mutabakatı: önce açıklamadaki fatura numarası, sonra tutar. Sonuç: ödendi / eksik / fazla / ödenmedi, Excel raporu |
| `Vergi Numarası Geçerli Mi` / `TC Kimlik Numarası Geçerli Mi` / `IBAN Geçerli Mi` | Kontrol hanesi doğrulaması |

Örnek: `AlamountRPA.exe robot ornek_efatura_mutabakat` komutu `ornek_veri\efatura` ve `ornek_veri\banka` klasörlerindeki
kurgusal dosyaları kullanır ve `output\mutabakat.xlsx` dosyasını yazar. Kendi dosyalarınız için:
`--variable FATURA_KLASORU:D:\Faturalar --variable EKSTRE:D:\ekstre.sta`.

> Logo, Netsis, Mikro gibi ERP'lere yazma; SGK ve e-Devlet akışları kuruma özel erişim (API kullanıcısı,
> e-imza, test ortamı) gerektirir. Bunlar her kurulumda o kurumun sistemine göre görev olarak yazılır.

## 5) Ajan katmanı ve LLM entegrasyonu (opsiyonel)

**a) OCR'ın okuyamadığı alanlar için Claude (`[LLM]`)**
- `aktif = evet` yapın ve API anahtarını `ANTHROPIC_API_KEY` ortam değişkenine yazın.
- Belge düzeni değişip kurallar bir alanı bulamazsa, ilgili sayfa metni ve kimlik görüntüsü Claude'a gönderilir.
  Varsayılan model `claude-opus-5-5`'tir. Ücret kullanıma göre alınır; `effort = low` daha ucuzdur.
- Claude'un doldurduğu alanlar **LLM - KONTROL EDİN** (turuncu) olarak işaretlenir ve onaylanmadan Mikro'ya girilmez.
  Claude kuralın bulduğu değerden farklı bir şey okursa alan **HR ONAYI GEREKLİ** olarak işaretlenir.
- ⚠️ **KVKK:** Bu ayar açılınca kimlik görüntüsü ve kişisel veriler Anthropic API'sine gider. Kurum onayı olmadan açmayın.

**b) LLM ile yönetim — MCP (Microsoft Copilot, Claude Desktop)**

Kontrol Merkezi, standart bir MCP uç noktası (`https://SUNUCU:8765/mcp`) sunar. Bir LLM bu uç nokta üzerinden,
**bağlanan kullanıcının rolüyle**, durum sorgular, iş başlatır, kuyruğu ve zamanlamaları yönetir.

1. Merkez makinesindeki `config.ini` dosyasında `[MCP] aktif = evet` yapın ve merkezi yeniden başlatın.
2. Her kullanıcı panelde **MCP / LLM** sayfasından kendi anahtarını oluşturur. Anahtar `alm_…` ile başlar ve yalnızca bir kez gösterilir.
   Betikle oluşturmak için: `AlamountRPA.exe merkez-mcp-anahtar ayse`.
3. İstemciyi bağlayın (MCP / LLM sayfasında URL'si doldurulmuş hazır örnekler vardır):

| İstemci | Bağlantı |
|---|---|
| **Microsoft Copilot Studio** (Microsoft 365 Copilot ajanları) | Araçlar → Model Context Protocol → URL `…/mcp`, kimlik doğrulama **API anahtarı**, üst bilgi adı `X-API-Key`. Merkezin internetten **HTTPS** ile erişilebilir olması gerekir. |
| **GitHub Copilot** (VS Code) | `.vscode/mcp.json` içinde `"type": "http"`, `url` ve `Authorization: Bearer <anahtar>` üst bilgisi |
| **Claude Desktop** | `claude_desktop_config.json`: `"command": "C:\\AlamountRPA\\AlamountRPA.exe"`, `"args": ["mcp", "--merkez", "https://SUNUCU:8765/mcp"]`, `"env": {"ALAMOUNT_MCP_ANAHTARI": "alm_…"}`. Yerel bir köprü merkeze bağlanır. |

LLM'in kullanabileceği araçlar:

| Araç | Rol |
|---|---|
| `durum_ozeti`, `surecleri_listele`, `isleri_listele`, `is_detayi`, `kuyruk_ogeleri`, `zamanlamalari_listele` | izleyici |
| `is_baslat`, `is_iptal_et`, `ogeyi_yeniden_isle`, `zamanlama_durdur_baslat` | operator |
| `zamanlama_ekle` | yonetici |

- Varlık kasası (parolalar) ve kullanıcı yönetimi MCP'den **erişilemez**.
- Her çağrı, reddedilenler dahil, **Denetim** sayfasına "ad (MCP)" olarak yazılır.
- ⚠️ **KVKK:** `[MCP] kisisel_veri_paylas = hayir` (varsayılan) iken TC numaraları maskelenir, ad soyad ve iş logları LLM'e gönderilmez.
  Bulut tabanlı bir LLM kullanıldığında gönderilen her şey sağlayıcının sunucularına gider.

**c) Yerel MCP (tek bilgisayar, merkez olmadan)**
`"args": ["mcp"]` (`--merkez` olmadan) yalnızca o bilgisayardaki araçları açar: `ocr_pdf`, `belge_analizi`,
`ise_giris_hazirla`, `ise_giris_klasorunu_isle`, `pca_analizi`, `gorev_listesi`, `robot_gorevi_calistir`.
Bu modda OCR metni de LLM'e gider.

## 6) Kontrol Merkezi ve robot ajanları (çok makineli çalışma)

Tek paket iki rolde çalışır. Rolü config.ini ve çalıştırılan komut belirler:

```
                     ┌──────────────── Kontrol Merkezi (1 makine) ─────────────────┐
  Tarayıcı (HR, BT) ─┤  AlamountRPA.exe merkez   →  http://SUNUCU:8765                  │
                     │  web paneli · iş kuyruğu · iş öğesi kuyrukları · zamanlamalar │
                     │  şifreli varlık kasası · loglar/raporlar · bildirimler        │
                     └──────────────▲───────────────────────────▲──────────────────┘
                                    │ HTTP(S), robot anahtarı   │
                     ┌──────────────┴─────────┐    ┌────────────┴───────────┐
                     │ Robot makinesi 1       │    │ Robot makinesi 2       │
                     │ AlamountRPA.exe ajan       │    │ AlamountRPA.exe ajan       │
                     └──────────┬─────────────┘    └────────────┬───────────┘
                                └──── ortak ağ klasörü (\\sunucu\ik\ise_giris) ┘
```

### Kurulum

**Merkez makinesi** (7/24 açık bir sunucu ya da bilgisayar):
1. Zip'i çıkarın (ör. `C:\AlamountRPA`).
2. `merkez_kur.bat` dosyasını **Yönetici olarak** çalıştırın. Bu betik merkezi Windows açılışında başlatan görevi kurar, güvenlik duvarında 8765 portunu açar ve merkezi başlatır.
3. İlk yönetici parolası `merkez_veri\ilk_yonetici_parolasi.txt` dosyasındadır. `http://SUNUCU:8765` adresinden giriş yapın, sonra **Kullanıcılar** sayfasından parolanızı değiştirin ve bu dosyayı silin.
4. **Robotlar → Robot ekle** ile her robot makinesi için bir robot oluşturun. Ekranda bir kez gösterilen anahtarı not edin.
5. (Önerilir) HTTPS için `[MERKEZ] ssl_sertifika` / `ssl_anahtar` ayarlarına kurumsal sertifikanızı verin.
   Bildirim e-postalarındaki bağlantılar için `panel_url` ayarını doldurun.

**Robot makinesi:**
1. Zip'i çıkarın.
2. `config.ini` dosyasının `[AJAN]` bölümüne `merkez_url`, `robot_adi`, `robot_anahtari` yazın.
3. Çok robotlu işe giriş için `[ISE_GIRIS]` ayarlarındaki `giris`, `puantaj`, `cikti` ile `[KLASORLER]` ayarlarındaki `arsiv`, `hata` değerlerini **ortak ağ klasörüne** yönlendirin (ör. `\\sunucu\ik\ise_giris`).
4. **Gözetimli robot** (bir kullanıcı bilgisayarın başında): o kullanıcıyla oturum açıp `ajan_kur.bat` dosyasını çalıştırın. Ajan her oturum açılışında başlar.
   **Gözetimsiz robot** (kimse başında değil): aşağıdaki "Gözetimsiz robot" bölümüne bakın.
5. Panelde robot birkaç saniye içinde **Boşta** görünür. **Robotlar** sayfasında robotun Windows oturumunun açık ya da kilitli olduğu da görünür.

### Gözetimsiz robot (oturumu robot kendisi açar)

Masaüstü otomasyonu (Mikro, Citrix, Not Defteri) yalnızca açık ve kilitsiz bir Windows oturumunda çalışır.
Gözetimsiz bir robot makinesinde bunu Alamount RPA sağlar:

1. Robot için bir Windows kullanıcısı açın (ör. `robot1`; etki alanı hesabı da olur). Parolayı isterseniz merkezin
   kasasına varlık olarak kaydedin (ör. `ROBOT1_WINDOWS`).
2. Robot makinesinde **yönetici** komut isteminde çalıştırın:
   ```
   AlamountRPA.exe oturum-kur --kullanici .\robot1
   AlamountRPA.exe oturum-kur --kullanici ALAN\robot1 --parola-varligi ROBOT1_WINDOWS
   ```
   İlki parolayı sorar, ikincisi merkezin kasasından alır. Parola önce Windows'ta doğrulanır; yanlışsa hiçbir şey değişmez.
3. Bilgisayarı yeniden başlatın. Windows robot kullanıcısıyla kendiliğinden oturum açar ve ajan başlar.

Ne yapar:
- **Otomatik oturum açma:** Parola Windows'un LSA gizli alanında şifreli saklanır; kayıt defterinde düz metin parola
  yoktur (Sysinternals Autologon ile aynı yöntem). Oturum kapatılırsa Windows hemen yeniden giriş yapar.
- **Oturum gözetmeni** (`AlamountRPA_OturumGozetmeni` görevi, SYSTEM olarak çalışır) 20 sn'de bir bakar:
  - Biri robota RDP ile bağlanıp pencereyi kapattıysa, oturum kilitlenmeden fiziksel konsola geri bağlanır.
  - Oturum kilitlendiyse ve robot o anda iş çalıştırmıyorsa, oturum kapatılır ve temiz bir oturumla yeniden açılır
    (`kilitliyken_yeniden_ac = hayir` ile kapatılabilir).
  - Parola kasadan geliyorsa 6 saatte bir kontrol edilir. Kasada değiştirdiğinizde robot makinesi kendini günceller.
- **Ajan:** Robot kullanıcısının oturumunda başlar ve çökerse yeniden başlatılır. Boştayken bilgisayarı uyanık tutar,
  ekran koruyucu ve kilit devreye girmez. Oturum kilitliyken iş almaz.
- Uyku modunu (prizdeyken) kapatır.

`AlamountRPA.exe oturum-durum` oturumları, otomatik oturum açma durumunu ve ajanı gösterir.
`AlamountRPA.exe oturum-kaldir` hepsini geri alır ve parolayı LSA'dan siler.

> Güvenlik: Robot kullanıcısına yalnızca işi için gereken yetkileri verin (yönetici yapmayın).
> Makineye fiziksel erişimi kısıtlayın; otomatik oturum açılan bir makinede ekran başındaki kişi robotun oturumunu görür.
> Bir Windows Server'da aynı anda birden çok robot oturumu (RDP ile) henüz desteklenmiyor; her robot için bir makine
> ya da sanal makine kullanın.

Kurulumu betikle yapmak isterseniz, merkez makinesinde şu komutları kullanabilirsiniz:
`AlamountRPA.exe merkez-robot ROBOT-1` (anahtarı yazar), `AlamountRPA.exe merkez-is pca --robot ROBOT-1 --bekle 30`
(işi başlatır, bitmesini bekler; çıkış kodu 0 = başarılı), `AlamountRPA.exe merkez-parola admin` (parola sıfırlar).

### Panel

| Sayfa | Ne yapılır |
|---|---|
| **Pano** | Çevrimiçi robotlar, çalışan/bekleyen işler, bugünkü başarı/başarısızlık, kuyruk durumu (15 sn'de bir yenilenir) |
| **İşler** | Süreç ve robot seçerek iş başlatma, öncelik, deneme hakkı, zaman aşımı, Robot değişkenleri. İş detayında canlı log, Robot `log.html` raporu, iptal ve yeniden çalıştırma |
| **Kuyruklar** | İş öğeleri (ör. her personel PDF'i bir öğe): durum, deneme, hangi robot, sonuç, hata türü; tek tıkla yeniden işleme |
| **Zamanlamalar** | Cron ile zamanlanmış işler (ör. `*/15 8-18 * * 1-5`); durdurma/başlatma, "şimdi çalıştır". Önceki çalışma bitmeden yenisi başlamaz |
| **Robotlar** | Robot ekleme/pasifleştirme, anahtar yenileme, son görülme, makine, sürüm |
| **Varlıklar** | Şifreli kasa: Mikro kullanıcı/parolası, SMTP parolası, Teams webhook URL'si… |
| **Kullanıcılar** | Roller: **izleyici** (yalnızca görür), **operator** (iş başlatır/iptal eder, öğe yeniden işler), **yonetici** (her şey) |
| **Denetim** | Kim, ne zaman, ne yaptı: girişler, iş başlatma/iptal, varlık okuma, robot ve kullanıcı değişiklikleri |

### Çok robotlu işe giriş (kuyruk)

1. **İşe giriş — PDF'leri kuyruğa ekle (dağıtıcı):** Ortak klasördeki her PDF için `ise_giris` kuyruğuna bir öğe ekler.
   Aynı dosya iki kez eklenmez; dosya değişirse yeni öğe olarak eklenir.
2. **İşe giriş — kuyruktan al ve işle (çalışan):** Bu işi birden fazla robota verebilirsiniz. Her öğeyi yalnızca bir robot alır; kuyruk boşalınca iş biter.
3. Hatalar ikiye ayrılır:
   - **İş kuralı hatası** (TC Puantaj'da yok, PDF yanlış): yeniden denenmez, PDF `error\ise_giris` klasörüne gider, bildirim gönderilir.
   - **Sistem hatası** (ağ, dosya kilidi, çökme): deneme hakkı kadar (varsayılan 3) otomatik yeniden denenir.

Tipik zamanlama: `*/10 8-18 * * 1-5` ile dağıtıcı, `*/10 8-18 * * 1-5` ile her robotta çalışan.

### Güvenilirlik

- Bir robot 90 sn nabız göndermezse **çevrimdışı** sayılır ve bildirim gider; geri gelince "yeniden çevrimiçi" bildirimi gider.
- Robotu kaybolan **çalışan iş** 5 dk sonra başarısız sayılır, deneme hakkı varsa başka robotta yeniden çalışır.
  Yarım kalan kuyruk öğeleri yeniden kuyruğa alınır.
- Başarısız işler 1, 2, 4… dk aralıklarla yeniden denenir (iş başlatırken verilen deneme hakkı kadar).
- Merkeze geçici olarak ulaşılamazsa ajan, iş sonucunu kaybetmeden ulaşana kadar tekrar dener.
- Ajan yalnızca katalogdaki süreçleri çalıştırır (PCA, işe giriş, `gorevler\*.robot`). Merkezden keyfi komut çalıştırılamaz.

### Bildirimler (`[BILDIRIM]`)

- **E-posta:** `eposta = evet` yapın. `[EMAIL]` bölümündeki SMTP ayarları kullanılır; parolayı `sifre = varlik:SMTP` biçiminde kasadan okutabilirsiniz.
- **Teams:** Kanalda **Workflows → "Post to a channel when a webhook request is received"** ile bir URL alın ve `teams_webhook` ayarına yazın (ya da `varlik:TEAMS_WEBHOOK`).
- Hangi olaylarda bildirim gideceği: `olaylar = is_basarisiz, robot_cevrimdisi, robot_cevrimici, oge_basarisiz` (`is_basarili` da eklenebilir).
- Panel her durumda güncel durumu gösterir.

### Yedekleme

`merkez_veri\` klasörünün tamamını düzenli yedekleyin: veritabanı, `kasa.key` ve raporlar.
**`kasa.key` kaybolursa kasadaki parolalar çözülemez.** Bu klasöre yalnızca yöneticiler erişebilmelidir.

### UiPath Orchestrator'a göre eksikler

- Görsel süreç tasarımcısı ve kaydedici yok; süreçler `.robot` / Python ile yazılır.
- Bir sunucuda aynı anda birden çok gözetimsiz robot oturumu (RDP) yok; robot başına bir makine gerekir.
- Yüksek erişilebilirlik (çift merkez) ve Active Directory / Entra ID ile tek oturum açma (SSO) yok.

## 7) PCA analizi

`input\` klasörüne `.txt` / `.csv` / `.xlsx` veri dosyası bırakın, sonra `AlamountRPA.exe pca --once` çalıştırın.
Ayarlar `[VERI]`, `[PCA]`, `[GRAFIK]`, `[CIKTI]`, `[EMAIL]` bölümlerindedir. Çıktı `output\<dosya>_<tarih>\` klasörüne yazılır.

## Otomatik çalıştırma

`gorev_zamanlayici_kur.bat` iki görev oluşturur: **AlamountRPA_IseGiris** ve **AlamountRPA_PCA** (varsayılan olarak 15 dakikada bir).
Farklı aralık için: `gorev_zamanlayici_kur.bat 60`. Kaldırmak için: `gorev_zamanlayici_kaldir.bat`.
Mikro girişi zamanlanmaz; HR onayından sonra elle başlatılması önerilir.

## Gizlilik (KVKK)

- Loglarda TC numarası maskelenir (`123******01`, `[ISE_GIRIS] tc_maskele`).
- OCR tamamen yereldir; LLM katmanı kapalıyken hiçbir veri bilgisayardan çıkmaz.
- `output\ise_giris\…\gorseller\` klasörü kimlik görüntüleri içerir. İstemiyorsanız `[OCR] ara_gorselleri_kaydet = hayir` yapın.

## Kaynaktan derleme

Python 3.12 (x64) ve Tesseract (`winget install UB-Mannheim.TesseractOCR`) kurulu bir Windows makinede `build_exe.bat` çalıştırın.
Kurgusal test belgelerini yeniden üretmek için: `python araclar\ornek_belge_uret.py`.
