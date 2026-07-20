# Electronic Product Web Scraping Pipeline

Bu klasör, elektronik ürün verilerinin otomatik olarak toplanması için
geliştirilen web scraping pipeline'ını içermektedir.

Pipeline iki temel aşamadan oluşmaktadır:

```text
Ürün listeleme sayfası
        │
        ▼
product-links-scraper.py
        │
        ▼
Ürün bağlantıları
        │
        ▼
products-feature-scraper.py
        │
        ▼
Ham elektronik ürün veri seti
```

---

## product-links-scraper.py

Bu script elektronik ürün listeleme sayfalarını tarayarak ürün
bağlantılarını otomatik olarak toplamaktadır.

Sayfa yapısı dinamik olduğu için kademeli scroll yöntemi kullanılarak
yeni ürün kartlarının yüklenmesi beklenmektedir.

Toplanan ürün bağlantıları daha sonra ürün detay scraper'ına girdi olarak
verilmektedir.

Aynı ürünün farklı merchant/satıcı kayıtları mevcut olduğunda
`product_id + merchant_id` kombinasyonu dikkate alınarak ayrı kayıt olarak
değerlendirilebilmektedir.

---

## products-feature-scraper.py

Bu script toplanan ürün bağlantılarını ziyaret ederek ürün detaylarını
çıkarmaktadır.

Mevcut olduğu durumlarda aşağıdaki alanlar elde edilmektedir:

- Ürün adı
- Marka
- Fiyat
- Genel yıldız puanı
- Değerlendirme sayısı
- Yorum sayısı
- Kullanıcı yorumları
- Favori bilgisi
- Kategoriler
- Teknik özellikler
- Ürün URL'si
- Yorum URL'si

Dinamik içerikler için Selenium ve tarayıcı otomasyonu kullanılmaktadır.

Ürün yorumları, her kullanıcı yorumu ayrı bir kayıt olacak şekilde
toplanmaktadır.

Bir yorum birden fazla cümle içerse bile yorum bütünlüğü korunmaktadır.

Örnek:

```json
[
  "Ürünü iki haftadır kullanıyorum. Pil performansı oldukça iyi.",
  "Paketleme güzeldi. Ürün sorunsuz şekilde elime ulaştı."
]
```

Burada iki ayrı kullanıcı yorumu bulunmaktadır.

---

## Uzun Süreli Scraping ve Hata Yönetimi

Yüzlerce ürünün aynı Chrome oturumu içerisinde işlenmesi bellek
tüketiminin artmasına neden olabileceğinden scraper aşağıdaki
mekanizmaları kullanabilir:

- Belirli sayıda ürün sonrasında Chrome driver restart
- Hata durumunda otomatik retry
- `tab crashed` hatasında driver yeniden başlatma
- Başarılı ürünleri kaydederek kaldığı yerden devam etme
- Daha önce işlenen ürünleri tekrar işlememe
- Hatalı URL'leri ayrı kayıt altında tutma

Bu yapı sayesinde uzun süreli scraping işlemlerinin daha dayanıklı
çalışması amaçlanmaktadır.

---

## Oluşturulan Ham Veri

Scraping sonucunda oluşturulan ana veri dosyası:

```text
trendyol_electronics_products.jsonl
```

Her satır bir ürün kaydını temsil etmektedir.

Ham dataset ayrıca Hugging Face üzerinde yayınlanmaktadır:

```text
sedayzc/trendyol-electronics-products
```

---

## Türetilmiş Dataset

Ham ürün verileri daha sonra chat formatına dönüştürülmektedir.

Final fine-tuning dataset:

```text
sedayzc/turkish-electronics-product-comparison-recommendation
```

Bu dataset ürün karşılaştırma ve ürün öneri görevleri için hazırlanmıştır.

---

## Kurulum

Gerekli temel paketler:

```bash
pip install selenium
pip install webdriver-manager
pip install beautifulsoup4
pip install pandas
pip install openpyxl
```

---

## Veri Kullanım Notu

Veriler eğitim ve araştırma amacıyla herkese açık e-ticaret sayfalarından
toplanmıştır.

Scraping işlemlerinin gerçekleştirildiği platformların kullanım
koşullarının ve uygulanabilir yasal düzenlemelerin kontrol edilmesi
kullanıcının sorumluluğundadır.

Bu proje Trendyol tarafından oluşturulmamış, desteklenmemiş veya
onaylanmamıştır.