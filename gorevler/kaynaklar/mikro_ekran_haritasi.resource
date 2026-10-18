*** Settings ***
Documentation     Mikro ERP > Personel Sicil Kartları ekran haritası (locator'lar).
...
...               BU DEĞERLER ŞABLONDUR. Mikro sürümüne göre değişir; mikro_ekran_kesfi.robot ile
...               gerçek name / automationid değerlerini çıkarıp aşağıya yazın.
...               Locator sözdizimi (RPA.Windows) — regex içinde BOŞLUK kullanmayın, yerine . yazın:
...                 name:"Giriş Tarihi"             → görünen ad
...                 id:txtGirisTarihi               → AutomationId
...                 class:Edit and name:"Cadde"     → birleşik
...                 name:"Tanıtım Kartı" > name:"Giriş Tarihi"   → hiyerarşi
...               Alan numaraları checklist'teki numaralarla aynıdır.

*** Variables ***
${MIKRO_PENCERE}          regex:.*Mikro.*
${MIKRO_SICIL_PENCERE}    regex:.*Personel.Sicil.*
${MIKRO_JUMP_KISAYOL}     {Ctrl}j
${MIKRO_EKRAN_KODU}       111100
${MIKRO_KAYDET}           name:"Kaydet"

&{MIKRO_SEKMELER}
...    1=name:"Tanıtım Kartı"
...    2=name:"İletişim Bilgileri"
...    3=name:"Kimlik Bilgileri"
...    4=name:"Nüfus Bilgileri"
...    5=name:"Ücret Bilgileri"

# Alan no → locator. Haritada olmayan alanlar atlanır (uyarı yazılır).
&{MIKRO_ALANLAR}
...    1=name:"Giriş Tarihi"
...    2=name:"Tersane"
...    3=name:"Sicil"
...    4=name:"Entegre Grubu"
...    5=name:"Emeklilik Durumu"
...    6=name:"Cadde"
...    7=name:"Mahalle"
...    8=name:"Sokak"
...    9=name:"Bina No"
...    10=name:"Daire No"
...    11=name:"Ülke"
...    12=name:"İl"
...    13=name:"İlçe"
...    14=name:"Cep Telefonu"
...    15=name:"Tahsili"
...    16=name:"Mesleği"
...    17=name:"Görevi"
...    18=name:"SGK Sicil"
...    19=name:"Ana Kanun"
...    20=name:"Kanun 2"
...    21=name:"Diğer Belge Türü"
...    22=name:"Diğer Kanun"
...    23=name:"Uyruğu"
...    25=name:"Cinsiyeti"
...    26=name:"Medeni Hali"
...    27=name:"Dini"
...    28=name:"Doğum Tarihi"
...    29=name:"Doğum Yeri"
...    31=name:"Seri No"
...    32=name:"Nüfus İl"
...    33=name:"Nüfus İlçe"
...    34=name:"Nüfus Mahalle"
...    35=name:"Köy"
...    36=name:"Cilt No"
...    37=name:"Aile Sıra No"
...    38=name:"Sıra No"
...    40=name:"Verildiği Nüfus İdaresi"
...    43=name:"T.C. Kimlik No"
...    44=name:"İlk Soyadı"
...    46=name:"Ücret Tipi"
...    48=name:"Hesap Tipi"
...    49=name:"SGK Şubesi"
...    51=name:"Çalışma Kodu"
...    52=name:"Meslek Kodu"
...    54=name:"Banka Ödeme"
...    55=name:"IBAN"

# Açılır liste (ComboBox) olan alanlar: Select ile seçilir. Diğerleri metin kutusu (Set Value).
&{MIKRO_ALAN_TIPLERI}
...    3=liste
...    4=liste
...    5=liste
...    18=liste
...    25=liste
...    26=liste
...    46=liste
...    48=liste
...    49=liste
...    54=liste
