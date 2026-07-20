import re
import time
from pathlib import Path
from urllib.parse import (
    urljoin,
    urlsplit,
    urlunsplit,
    parse_qs,
    urlencode,
)

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ============================================================
# AYARLAR
# ============================================================

START_URL = (
    "https://www.trendyol.com/"
    "sr?wc=108656%2C103660%2C104024&sst=BEST_SELLER"
)

OUTPUT_FILE = "trendyol_product_links.xlsx"

# Kaç adet ürün + satıcı kombinasyonu alınacak?
TARGET_PRODUCT_COUNT = 500

PAGE_LOAD_TIMEOUT = 40

# Scroll sonrası bekleme
SCROLL_WAIT = 2

# Maksimum scroll
MAX_SCROLLS = 1000

# Bu kadar tur yeni ürün bulunmazsa dur
MAX_STABLE_ROUNDS = 30


# ============================================================
# CHROME DRIVER
# ============================================================

def create_driver():
    options = Options()

    options.add_argument(
        "--start-maximized"
    )

    options.add_argument(
        "--disable-notifications"
    )

    options.add_argument(
        "--disable-popup-blocking"
    )

    # İstersen sonradan headless kullanabilirsin.
    #
    # options.add_argument(
    #     "--headless=new"
    # )

    service = Service(
        ChromeDriverManager().install()
    )

    driver = webdriver.Chrome(
        service=service,
        options=options,
    )

    driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    return driver


# ============================================================
# PRODUCT ID ÇIKAR
# ============================================================

def extract_product_id(
    url,
):
    """
    URL içindeki:

    -p-881465224

    kısmından product_id çıkarır.
    """

    match = re.search(
        r"-p-(\d+)",
        url,
    )

    if match:
        return match.group(1)

    return None


# ============================================================
# MERCHANT ID ÇIKAR
# ============================================================

def extract_merchant_id(
    url,
):
    """
    Query içindeki merchantId değerini döndürür.
    """

    parts = urlsplit(
        url
    )

    query_params = parse_qs(
        parts.query
    )

    merchant_id = (
        query_params
        .get(
            "merchantId",
            [None],
        )[0]
    )

    return merchant_id


# ============================================================
# URL NORMALİZASYONU
# ============================================================

def normalize_product_url(
    url,
):
    """
    Aynı ürün + farklı satıcı:
        ayrı kayıt

    Aynı ürün + aynı satıcı + farklı boutiqueId:
        aynı kayıt

    URL içinde yalnızca merchantId korunur.
    """

    if not url:
        return None

    # Relative URL ise tam URL yap
    url = urljoin(
        "https://www.trendyol.com",
        url,
    )

    parts = urlsplit(
        url
    )

    path = parts.path.rstrip("/")

    # Product ID kontrolü
    product_id = (
        extract_product_id(
            path
        )
    )

    if not product_id:
        return None

    # Query parametreleri
    query_params = parse_qs(
        parts.query
    )

    merchant_id = (
        query_params
        .get(
            "merchantId",
            [None],
        )[0]
    )

    # Sadece merchantId korunacak.
    # boutiqueId kaldırılacak.
    new_query = {}

    if merchant_id:
        new_query[
            "merchantId"
        ] = merchant_id

    clean_query = urlencode(
        new_query
    )

    normalized_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            clean_query,
            "",
        )
    )

    return normalized_url


# ============================================================
# BENZERSİZ KAYIT ANAHTARI
# ============================================================

def get_product_key(
    url,
):
    """
    Benzersiz kayıt anahtarı:

    product_id + merchantId
    """

    product_id = (
        extract_product_id(
            url
        )
    )

    merchant_id = (
        extract_merchant_id(
            url
        )
    )

    if not product_id:
        return None

    # merchantId yoksa ürün id tek başına kullanılır
    return (
        product_id,
        merchant_id or "NO_MERCHANT",
    )


# ============================================================
# HTML'DEN ÜRÜN LİNKLERİNİ ÇIKAR
# ============================================================

def extract_product_links(
    html,
):
    """
    Sayfadaki ürün kartlarından URL'leri çıkarır.
    """

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    found = []

    selectors = [
        ".p-card-wrppr a[href]",
        ".p-card-chldrn-cntnr a[href]",
        ".prdct-cntnr-wrppr a[href]",
        "a[href*='-p-']",
    ]

    for selector in selectors:

        elements = soup.select(
            selector
        )

        for element in elements:

            href = element.get(
                "href"
            )

            if not href:
                continue

            normalized_url = (
                normalize_product_url(
                    href
                )
            )

            if not normalized_url:
                continue

            found.append(
                normalized_url
            )

    return found


# ============================================================
# ÜRÜN LİNKLERİNİ TOPLA
# ============================================================

def collect_product_links(driver):
    """
    Listeleme sayfasında kademeli scroll yaparak
    TARGET_PRODUCT_COUNT kadar benzersiz
    product_id + merchantId kombinasyonu toplar.
    """

    print("Listeleme sayfası açılıyor:")
    print(START_URL)

    driver.get(START_URL)

    WebDriverWait(
        driver,
        PAGE_LOAD_TIMEOUT,
    ).until(
        lambda d:
        d.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    time.sleep(5)

    # key:
    # (product_id, merchantId)
    #
    # value:
    # normalized_url
    product_records = {}

    previous_count = 0
    stable_rounds = 0

    for scroll_index in range(
        1,
        MAX_SCROLLS + 1,
    ):

        # ====================================================
        # 1. MEVCUT ÜRÜN LİNKLERİNİ TOPLA
        # ====================================================

        current_links = extract_product_links(
            driver.page_source
        )

        for link in current_links:

            key = get_product_key(
                link
            )

            if not key:
                continue

            if key not in product_records:

                product_records[key] = link

        current_count = len(
            product_records
        )

        # ====================================================
        # LOG
        # ====================================================

        current_scroll_y = driver.execute_script(
            "return window.scrollY;"
        )

        current_height = driver.execute_script(
            "return document.body.scrollHeight;"
        )

        print(
            f"Scroll {scroll_index:3} | "
            f"Konum: {int(current_scroll_y):7} / "
            f"{int(current_height):7} | "
            f"Benzersiz ürün + satıcı: "
            f"{current_count}"
        )

        # ====================================================
        # 2. HEDEFE ULAŞILDI
        # ====================================================

        if (
            current_count
            >= TARGET_PRODUCT_COUNT
        ):

            print(
                "\nHedef ürün sayısına ulaşıldı."
            )

            break

        # ====================================================
        # 3. YENİ ÜRÜN GELDİ Mİ?
        # ====================================================

        if (
            current_count
            > previous_count
        ):

            stable_rounds = 0

        else:

            stable_rounds += 1

        previous_count = (
            current_count
        )

        # ====================================================
        # 4. KADEMELİ SCROLL
        # ====================================================

        # Ekranın yaklaşık %85'i kadar aşağı in.
        # Direkt sayfanın sonuna atlamıyoruz.
        driver.execute_script(
            """
            window.scrollBy(
                0,
                window.innerHeight * 0.85
            );
            """
        )

        time.sleep(
            SCROLL_WAIT
        )

        # ====================================================
        # 5. SAYFANIN SONUNA GELDİYSE
        # YENİ ÜRÜN YÜKLENMESİNİ TETİKLE
        # ====================================================

        scroll_y = driver.execute_script(
            "return window.scrollY;"
        )

        viewport_height = driver.execute_script(
            "return window.innerHeight;"
        )

        page_height = driver.execute_script(
            "return document.body.scrollHeight;"
        )

        near_bottom = (
            scroll_y
            + viewport_height
            >= page_height - 500
        )

        if near_bottom:

            print(
                "  Sayfa sonuna yaklaşıldı, "
                "yeni ürünler bekleniyor..."
            )

            # IntersectionObserver / lazy-load tetiklemek için
            # en alta git
            driver.execute_script(
                """
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                );
                """
            )

            time.sleep(
                SCROLL_WAIT + 2
            )

            # Yeni içerik geldiyse page height büyür.
            new_height = (
                driver.execute_script(
                    "return document.body.scrollHeight;"
                )
            )

            # Bazen en alta yapışınca tetiklenmeyebilir.
            # Biraz yukarı sonra tekrar aşağı hareket ettir.
            if (
                new_height
                == page_height
            ):

                driver.execute_script(
                    """
                    window.scrollBy(
                        0,
                        -500
                    );
                    """
                )

                time.sleep(1)

                driver.execute_script(
                    """
                    window.scrollTo(
                        0,
                        document.body.scrollHeight
                    );
                    """
                )

                time.sleep(
                    SCROLL_WAIT + 2
                )

        # ====================================================
        # 6. UZUN SÜREDİR YENİ ÜRÜN YOKSA
        # ====================================================

        if (
            stable_rounds
            >= MAX_STABLE_ROUNDS
        ):

            # Son bir kez aşağı yukarı hareket ederek
            # lazy-load tetiklemeyi dene.
            print(
                "  Yeni ürün gelmiyor, "
                "son kez lazy-load tetikleniyor..."
            )

            driver.execute_script(
                """
                window.scrollTo(
                    0,
                    document.body.scrollHeight
                );
                """
            )

            time.sleep(5)

            final_links = extract_product_links(
                driver.page_source
            )

            old_count = len(
                product_records
            )

            for link in final_links:

                key = get_product_key(
                    link
                )

                if (
                    key
                    and key
                    not in product_records
                ):

                    product_records[
                        key
                    ] = link

            new_count = len(
                product_records
            )

            if new_count == old_count:

                print(
                    "\nYeni ürün bulunamadığı için "
                    "tarama durduruldu."
                )

                break

            else:

                print(
                    f"  Yeni ürünler bulundu: "
                    f"{old_count} -> {new_count}"
                )

                stable_rounds = 0

    # ========================================================
    # KAYITLARI HAZIRLA
    # ========================================================

    records = []

    for (
        product_id,
        merchant_id,
    ), url in product_records.items():

        records.append(
            {
                "Product ID":
                    product_id,

                "Merchant ID":
                    (
                        merchant_id
                        if merchant_id
                        != "NO_MERCHANT"
                        else None
                    ),

                "Links":
                    url,
            }
        )

        if (
            len(records)
            >= TARGET_PRODUCT_COUNT
        ):

            break

    return records


# ============================================================
# EXCEL'E KAYDET
# ============================================================

def save_records_to_excel(
    records,
):

    dataframe = pd.DataFrame(
        records
    )

    dataframe.to_excel(
        OUTPUT_FILE,
        index=False,
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "ÜRÜN LİNKLERİ KAYDEDİLDİ"
    )

    print(
        "=" * 70
    )

    print(
        "Toplam kayıt:",
        len(
            dataframe
        ),
    )

    # --------------------------------------------------------
    # Benzersiz ürün sayısı
    # --------------------------------------------------------

    if (
        not dataframe.empty
    ):

        unique_products = (
            dataframe[
                "Product ID"
            ]
            .nunique()
        )

        unique_merchants = (
            dataframe[
                "Merchant ID"
            ]
            .nunique(
                dropna=True
            )
        )

        print(
            "Benzersiz ürün:",
            unique_products,
        )

        print(
            "Benzersiz satıcı:",
            unique_merchants,
        )

    print(
        "Dosya:"
    )

    print(
        Path(
            OUTPUT_FILE
        ).resolve()
    )


# ============================================================
# MAIN
# ============================================================

def main():

    driver = (
        create_driver()
    )

    try:

        records = (
            collect_product_links(
                driver
            )
        )

    finally:

        driver.quit()

    save_records_to_excel(
        records
    )


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    main()