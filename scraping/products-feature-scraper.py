import base64
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import (
    InvalidSessionIdException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# ============================================================
# AYARLAR
# ============================================================

INPUT_FILE = "trendyol_product_links.xlsx"
LINK_COLUMN = "Links"

OUTPUT_EXCEL = "trendyol_electronics_products.xlsx"
OUTPUT_JSONL = "trendyol_electronics_products.jsonl"
ERROR_FILE = "scraping_errors.jsonl"

PAGE_LOAD_TIMEOUT = 40

PRODUCT_PAGE_WAIT = 5
REVIEW_PAGE_WAIT = 5

PRODUCT_DELAY = 3

# Maksimum çekilecek gerçek yorum sayısı
MAX_REVIEWS = 500

# Maksimum scroll sayısı
MAX_REVIEW_SCROLLS = 100

# Scroll sonrası bekleme
SCROLL_WAIT = 2

# Bu kadar tur yeni yorum bulunmazsa dur
MAX_STABLE_ROUNDS = 10

# ============================================================
# DAYANIKLILIK / RESUME AYARLARI
# ============================================================

# Aynı Chrome oturumu uzun süre açık kalınca bellek tüketimi artabiliyor.
# Bu kadar YENİ ürün denemesinden sonra driver yeniden başlatılır.
RESTART_DRIVER_EVERY = 20

# Bir ürün "tab crashed", timeout veya WebDriver hatası verirse
# aynı ürün bu kadar kez yeniden denenir.
MAX_RETRIES_PER_PRODUCT = 3

# Daha önce başarıyla yazılmış OUTPUT_JSONL varsa kaldığı yerden devam eder.
RESUME_EXISTING = True

# Driver yeniden başlatılırken kısa bekleme
DRIVER_RESTART_WAIT = 2


# ============================================================
# GENEL YARDIMCI FONKSİYONLAR
# ============================================================

def clean_text(text):
    if text is None:
        return None

    text = re.sub(
        r"\s+",
        " ",
        str(text),
    )

    return text.strip()


def is_missing(value):
    return value in [
        None,
        "",
        "Fiyat Bulunamadı",
        "Puan Bulunamadı",
        "Değerlendirme Sayısı Bulunamadı",
        "Favori Sayısı Bulunamadı",
    ]


# ============================================================
# YORUM URL'Sİ
# ============================================================

def build_review_url(product_url):
    """
    Ürün URL'sini yorum sayfasına dönüştürür.

    Örnek:

    https://www.trendyol.com/...-p-123?merchantId=1

    ->

    https://www.trendyol.com/...-p-123/yorumlar?merchantId=1
    """

    parts = urlsplit(product_url)

    path = parts.path.rstrip("/")

    if not path.endswith("/yorumlar"):
        path += "/yorumlar"

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            path,
            parts.query,
            parts.fragment,
        )
    )


# ============================================================
# HTML SELECTOR YARDIMCILARI
# ============================================================

def find_first_text(soup, selectors):
    """
    CSS selector listesini sırayla dener.
    """

    for selector in selectors:

        element = soup.select_one(
            selector
        )

        if not element:
            continue

        text = clean_text(
            element.get_text(
                " ",
                strip=True,
            )
        )

        if text:
            return text

    return None


def find_unique_texts(soup, selectors):
    """
    Benzersiz metinleri toplar.
    """

    results = []
    seen = set()

    for selector in selectors:

        for element in soup.select(
            selector
        ):

            text = clean_text(
                element.get_text(
                    " ",
                    strip=True,
                )
            )

            if not text:
                continue

            if text in seen:
                continue

            seen.add(
                text
            )

            results.append(
                text
            )

    return results


# ============================================================
# SAYFA YÜKLEME
# ============================================================

def load_page(
    driver,
    url,
    wait_seconds,
):

    driver.get(
        url
    )

    WebDriverWait(
        driver,
        PAGE_LOAD_TIMEOUT,
    ).until(
        lambda d:
        d.execute_script(
            "return document.readyState"
        )
        == "complete"
    )

    time.sleep(
        wait_seconds
    )


def gradual_scroll(
    driver,
    steps=6,
    wait=1,
):
    """
    Lazy-load içerikleri yüklemek için sayfayı
    parça parça aşağı kaydırır.
    """

    for step in range(
        1,
        steps + 1,
    ):

        ratio = (
            step
            / steps
        )

        driver.execute_script(
            f"""
            window.scrollTo(
                0,
                document.body.scrollHeight * {ratio}
            );
            """
        )

        time.sleep(
            wait
        )


# ============================================================
# JSON-LD ÜRÜN VERİSİ
# ============================================================

def extract_json_ld(soup):
    """
    Schema.org Product JSON-LD nesnesini bulur.
    """

    products = []

    scripts = soup.find_all(
        "script",
        attrs={
            "type": "application/ld+json"
        },
    )

    for script in scripts:

        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        try:

            data = json.loads(
                raw
            )

        except Exception:

            continue

        candidates = []

        if isinstance(
            data,
            dict,
        ):

            graph = data.get(
                "@graph"
            )

            if isinstance(
                graph,
                list,
            ):

                candidates.extend(
                    graph
                )

            candidates.append(
                data
            )

        elif isinstance(
            data,
            list,
        ):

            candidates.extend(
                data
            )

        for item in candidates:

            if not isinstance(
                item,
                dict,
            ):
                continue

            item_type = (
                item.get(
                    "@type"
                )
            )

            if item_type == "Product":

                products.append(
                    item
                )

            elif (
                isinstance(
                    item_type,
                    list,
                )
                and "Product"
                in item_type
            ):

                products.append(
                    item
                )

    if products:

        return products[0]

    return {}


def parse_json_ld_product(
    product_data,
):
    """
    JSON-LD içinden güvenilir ürün bilgilerini çıkarır.
    """

    result = {
        "product_name": None,
        "brand": None,
        "price": None,
        "rating": None,
        "review_count": None,
    }

    if not product_data:

        return result

    # --------------------------------------------------------
    # Ürün adı
    # --------------------------------------------------------

    result[
        "product_name"
    ] = product_data.get(
        "name"
    )

    # --------------------------------------------------------
    # Marka
    # --------------------------------------------------------

    brand = product_data.get(
        "brand"
    )

    if isinstance(
        brand,
        dict,
    ):

        result[
            "brand"
        ] = brand.get(
            "name"
        )

    elif isinstance(
        brand,
        str,
    ):

        result[
            "brand"
        ] = brand

    # --------------------------------------------------------
    # Fiyat
    # --------------------------------------------------------

    offers = product_data.get(
        "offers"
    )

    if isinstance(
        offers,
        dict,
    ):

        price = (
            offers.get(
                "price"
            )
            or offers.get(
                "lowPrice"
            )
        )

        currency = (
            offers.get(
                "priceCurrency"
            )
        )

        if price is not None:

            result[
                "price"
            ] = (
                f"{price} {currency}"
                if currency
                else str(price)
            )

    elif isinstance(
        offers,
        list,
    ):

        for offer in offers:

            if not isinstance(
                offer,
                dict,
            ):

                continue

            price = (
                offer.get(
                    "price"
                )
                or offer.get(
                    "lowPrice"
                )
            )

            if price is None:

                continue

            currency = (
                offer.get(
                    "priceCurrency"
                )
            )

            result[
                "price"
            ] = (
                f"{price} {currency}"
                if currency
                else str(price)
            )

            break

    # --------------------------------------------------------
    # Genel yıldız puanı
    # --------------------------------------------------------

    aggregate_rating = (
        product_data.get(
            "aggregateRating"
        )
    )

    if isinstance(
        aggregate_rating,
        dict,
    ):

        rating = (
            aggregate_rating.get(
                "ratingValue"
            )
        )

        count = (
            aggregate_rating.get(
                "ratingCount"
            )
            or aggregate_rating.get(
                "reviewCount"
            )
        )

        if rating is not None:

            result[
                "rating"
            ] = str(
                rating
            )

        if count is not None:

            result[
                "review_count"
            ] = str(
                count
            )

    return result


# ============================================================
# FİYAT
# ============================================================

def extract_price(
    soup,
    page_text,
):

    # --------------------------------------------------------
    # Meta
    # --------------------------------------------------------

    for selector in [
        "meta[itemprop='price']",
        "meta[property='product:price:amount']",
        "meta[property='og:price:amount']",
    ]:

        element = soup.select_one(
            selector
        )

        if not element:

            continue

        value = element.get(
            "content"
        )

        if value:

            return clean_text(
                value
            )

    # --------------------------------------------------------
    # DOM
    # --------------------------------------------------------

    price = find_first_text(
        soup,
        [
            ".prc-dsc",
            ".prc-org",
            ".prc-slg",
            "span.prc-dsc",
            "[data-testid='price-current-price']",
            "[class*='product-price']",
            "[class*='current-price']",
        ],
    )

    if price:

        return price

    # --------------------------------------------------------
    # Regex
    # --------------------------------------------------------

    match = re.search(
        r"(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)"
        r"\s*TL",
        page_text,
        flags=re.IGNORECASE,
    )

    if match:

        return (
            match.group(1)
            + " TL"
        )

    return None


# ============================================================
# FAVORİ SAYISI
# ============================================================

def extract_favorite_count(
    soup,
    page_text,
):

    favorite = find_first_text(
        soup,
        [
            ".favorite-count",
            "[class*='favorite-count']",
            "[class*='fav-count']",
        ],
    )

    if favorite:

        return favorite

    patterns = [

        r"([\d\.,]+)\s*kişi\s*favoriledi",

        r"([\d\.,]+)\s*kişinin\s*favorisi",

        r"([\d\.,]+)\s*favori",
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            page_text,
            flags=re.IGNORECASE,
        )

        if match:

            return match.group(
                1
            )

    return None


# ============================================================
# TEKNİK ÖZELLİKLER
# ============================================================

def extract_attributes(
    soup,
):

    attributes = {}

    selectors = [

        ".detail-attr-item",

        ".detail-attr-container .detail-attr-item",

        ".product-detail-attributes-item",

        ".attribute-item",

        "[class*='attribute-item']",

        "[class*='detail-attr']",
    ]

    for selector in selectors:

        for row in soup.select(
            selector
        ):

            texts = []

            for element in row.find_all(
                [
                    "span",
                    "div",
                    "p",
                    "li",
                ]
            ):

                text = clean_text(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )

                if (
                    text
                    and text
                    not in texts
                ):

                    texts.append(
                        text
                    )

            if len(
                texts
            ) < 2:

                continue

            key = texts[0]

            value = texts[-1]

            if (
                key == value
            ):

                continue

            if (
                len(key) <= 100
                and len(value) <= 300
            ):

                attributes[
                    key
                ] = value

    # --------------------------------------------------------
    # Tablo formatı
    # --------------------------------------------------------

    for row in soup.select(
        "table tr"
    ):

        cells = row.find_all(
            [
                "td",
                "th",
            ]
        )

        if len(
            cells
        ) != 2:

            continue

        key = clean_text(
            cells[0].get_text(
                " ",
                strip=True,
            )
        )

        value = clean_text(
            cells[1].get_text(
                " ",
                strip=True,
            )
        )

        if (
            key
            and value
            and key != value
            and len(key) <= 100
            and len(value) <= 300
        ):

            attributes[
                key
            ] = value

    return attributes


# ============================================================
# ÜRÜN SAYFASI
# ============================================================

def scrape_product_page(
    driver,
    product_url,
):

    load_page(
        driver,
        product_url,
        PRODUCT_PAGE_WAIT,
    )

    gradual_scroll(
        driver,
        steps=6,
        wait=1,
    )

    soup = BeautifulSoup(
        driver.page_source,
        "html.parser",
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    structured = (
        parse_json_ld_product(
            extract_json_ld(
                soup
            )
        )
    )

    # --------------------------------------------------------
    # Ürün adı
    # --------------------------------------------------------

    product_name = (

        structured.get(
            "product_name"
        )

        or find_first_text(
            soup,
            [
                "h1.pr-new-br",
                "h1",
            ],
        )
    )

    # --------------------------------------------------------
    # Marka
    # --------------------------------------------------------

    brand = (

        structured.get(
            "brand"
        )

        or find_first_text(
            soup,
            [
                ".product-brand-name-with-link",
                ".product-brand-name",
                "[class*='brand-name']",
            ],
        )
    )

    if (
        not brand
        and product_name
    ):

        brand = (
            product_name
            .split()[0]
        )

    # --------------------------------------------------------
    # Fiyat
    # --------------------------------------------------------

    price = (

        structured.get(
            "price"
        )

        or extract_price(
            soup,
            page_text,
        )
    )

    # --------------------------------------------------------
    # Genel yıldız
    # --------------------------------------------------------

    rating = (
        structured.get(
            "rating"
        )
    )

    # --------------------------------------------------------
    # Değerlendirme sayısı
    # --------------------------------------------------------

    review_count = (
        structured.get(
            "review_count"
        )
    )

    # --------------------------------------------------------
    # Favori
    # --------------------------------------------------------

    favorite_count = (
        extract_favorite_count(
            soup,
            page_text,
        )
    )

    # --------------------------------------------------------
    # Kategoriler
    # --------------------------------------------------------

    categories = (
        find_unique_texts(
            soup,
            [
                ".product-detail-breadcrumb-item",
                ".breadcrumb-item",
                "[class*='breadcrumb'] a",
            ],
        )
    )

    # --------------------------------------------------------
    # Teknik özellikler
    # --------------------------------------------------------

    attributes = (
        extract_attributes(
            soup
        )
    )

    return {

        "product_name":
            product_name
            or "Ürün İsmi Bulunamadı",

        "brand":
            brand
            or "Marka Bulunamadı",

        "price":
            price
            or "Fiyat Bulunamadı",

        "rating":
            rating
            or "Puan Bulunamadı",

        "review_count":
            review_count
            or "Değerlendirme Sayısı Bulunamadı",

        "favorite_count":
            favorite_count
            or "Favori Sayısı Bulunamadı",

        "categories":
            categories,

        "attributes":
            attributes,

        "source_url":
            product_url,
    }


# ============================================================
# YORUM TEMİZLEME
# ============================================================

def normalize_review(
    text,
):
    """
    Yorumu temizler.

    Cümlelere ASLA bölmez.
    """

    if not isinstance(
        text,
        str,
    ):

        return None

    text = clean_text(
        text
    )

    if not text:

        return None

    if len(
        text
    ) < 5:

        return None

    lowered = (
        text.lower()
    )

    blocked_phrases = [

        "değerlendirme özeti",

        "yorum özeti",

        "yapay zeka özeti",

        "yapay zekâ özeti",

        "şikayet et",

        "şikâyet et",

        "yorum yayınlama kriterleri",

        "daha fazla yorum göster",
    ]

    if any(
        phrase in lowered
        for phrase
        in blocked_phrases
    ):

        return None

    return text


# ============================================================
# NETWORK JSON YORUM KEY'LERİ
# ============================================================

REVIEW_TEXT_KEYS = {

    "comment",

    "commentText",

    "commentContent",

    "review",

    "reviewText",

    "reviewContent",

    "commentBody",

    "reviewBody",
}


# ============================================================
# JSON İÇİNDEN YORUM ÇIKAR
# ============================================================

def extract_reviews_from_json(
    data,
    reviews=None,
    seen=None,
):
    """
    JSON'u recursive tarar.

    Her tam yorum ayrı string olarak döner.
    """

    if reviews is None:

        reviews = []

    if seen is None:

        seen = set()

    if isinstance(
        data,
        dict,
    ):

        for (
            key,
            value,
        ) in data.items():

            if (
                key in REVIEW_TEXT_KEYS
                and isinstance(
                    value,
                    str,
                )
            ):

                review = (
                    normalize_review(
                        value
                    )
                )

                if review:

                    normalized = (
                        review
                        .lower()
                        .strip()
                    )

                    if (
                        normalized
                        not in seen
                    ):

                        seen.add(
                            normalized
                        )

                        reviews.append(
                            review
                        )

            if isinstance(
                value,
                (
                    dict,
                    list,
                ),
            ):

                extract_reviews_from_json(
                    value,
                    reviews,
                    seen,
                )

    elif isinstance(
        data,
        list,
    ):

        for item in data:

            extract_reviews_from_json(
                item,
                reviews,
                seen,
            )

    return reviews


# ============================================================
# PERFORMANCE LOGLARINDAN YORUM ÇIKAR
# ============================================================

def extract_reviews_from_network(
    driver,
):
    """
    Yorumlarla ilgili XHR / fetch response'larını bulur.
    """

    reviews = []

    seen_reviews = set()

    try:

        logs = driver.get_log(
            "performance"
        )

    except Exception:

        return reviews

    for entry in logs:

        try:

            message = (
                json.loads(
                    entry[
                        "message"
                    ]
                )[
                    "message"
                ]
            )

        except Exception:

            continue

        if (
            message.get(
                "method"
            )
            !=
            "Network.responseReceived"
        ):

            continue

        params = message.get(
            "params",
            {},
        )

        response = params.get(
            "response",
            {},
        )

        url = response.get(
            "url",
            "",
        )

        mime_type = response.get(
            "mimeType",
            "",
        )

        url_lower = (
            url.lower()
        )

        # ----------------------------------------------------
        # Yorum endpoint olma ihtimali
        # ----------------------------------------------------

        possible_review_response = any(
            keyword
            in url_lower
            for keyword
            in [
                "review",
                "reviews",
                "comment",
                "comments",
                "rating",
                "evaluation",
            ]
        )

        if not possible_review_response:

            continue

        if (
            "json"
            not in mime_type.lower()
            and "javascript"
            not in mime_type.lower()
        ):

            continue

        request_id = params.get(
            "requestId"
        )

        if not request_id:

            continue

        try:

            body_result = (
                driver.execute_cdp_cmd(
                    "Network.getResponseBody",
                    {
                        "requestId":
                            request_id
                    },
                )
            )

            body = body_result.get(
                "body",
                "",
            )

            if body_result.get(
                "base64Encoded",
                False,
            ):

                body = (
                    base64.b64decode(
                        body
                    )
                    .decode(
                        "utf-8",
                        errors="ignore",
                    )
                )

            data = json.loads(
                body
            )

        except Exception:

            continue

        found_reviews = (
            extract_reviews_from_json(
                data
            )
        )

        for review in found_reviews:

            normalized = (
                review
                .lower()
                .strip()
            )

            if (
                normalized
                in seen_reviews
            ):

                continue

            seen_reviews.add(
                normalized
            )

            reviews.append(
                review
            )

    return reviews


# ============================================================
# DOM'DAN GERÇEK YORUMLARI BUL
# ============================================================

def extract_reviews_from_dom(
    soup,
):
    """
    Network başarısız olursa fallback.

    Yorum özeti selector'ları dahil edilmez.
    """

    reviews = []

    seen = set()

    selectors = [

        ".rnr-com-tx",

        ".comment-text",

        ".user-comment",

        "[data-testid='review-comment']",
    ]

    for selector in selectors:

        for element in soup.select(
            selector
        ):

            review = (
                normalize_review(
                    element.get_text(
                        " ",
                        strip=True,
                    )
                )
            )

            if not review:

                continue

            normalized = (
                review
                .lower()
                .strip()
            )

            if (
                normalized
                in seen
            ):

                continue

            seen.add(
                normalized
            )

            reviews.append(
                review
            )

    return reviews


# ============================================================
# YORUM SAYFASI İSTATİSTİKLERİ
# ============================================================

def parse_review_statistics(
    page_text,
):

    result = {

        "rating": None,

        "review_count": None,

        "comment_count": None,
    }

    if not page_text:

        return result

    # --------------------------------------------------------
    # Değerlendirme
    # --------------------------------------------------------

    review_match = re.search(
        r"([\d\.,]+)"
        r"\s*Değerlendirme",
        page_text,
        flags=re.IGNORECASE,
    )

    # --------------------------------------------------------
    # Yorum
    # --------------------------------------------------------

    comment_match = re.search(
        r"([\d\.,]+)"
        r"\s*Yorum",
        page_text,
        flags=re.IGNORECASE,
    )

    if review_match:

        result[
            "review_count"
        ] = (
            review_match
            .group(1)
            .replace(
                ".",
                "",
            )
        )

    if comment_match:

        result[
            "comment_count"
        ] = (
            comment_match
            .group(1)
            .replace(
                ".",
                "",
            )
        )

    return result


# ============================================================
# TÜM YORUMLARI YÜKLE
# ============================================================

def load_reviews_from_page(
    driver,
):
    """
    Network ve DOM üzerinden yorumları toplar.

    Her yorum tek bir string olarak tutulur.
    """

    all_reviews = []

    seen_reviews = set()

    stable_rounds = 0

    previous_count = 0

    for scroll_index in range(
        MAX_REVIEW_SCROLLS
    ):

        # ----------------------------------------------------
        # Scroll
        # ----------------------------------------------------

        driver.execute_script(
            """
            window.scrollTo(
                0,
                document.body.scrollHeight
            );
            """
        )

        time.sleep(
            SCROLL_WAIT
        )

        # ----------------------------------------------------
        # Network
        # ----------------------------------------------------

        network_reviews = (
            extract_reviews_from_network(
                driver
            )
        )

        # ----------------------------------------------------
        # DOM
        # ----------------------------------------------------

        soup = BeautifulSoup(
            driver.page_source,
            "html.parser",
        )

        dom_reviews = (
            extract_reviews_from_dom(
                soup
            )
        )

        # ----------------------------------------------------
        # Birleştir
        # ----------------------------------------------------

        new_reviews = (
            network_reviews
            + dom_reviews
        )

        for review in new_reviews:

            normalized = (
                review
                .lower()
                .strip()
            )

            if (
                normalized
                in seen_reviews
            ):

                continue

            seen_reviews.add(
                normalized
            )

            all_reviews.append(
                review
            )

        current_count = len(
            all_reviews
        )

        print(
            f"  Scroll "
            f"{scroll_index + 1}: "
            f"{current_count} "
            f"benzersiz yorum bulundu"
        )

        # ----------------------------------------------------
        # Yeni yorum kontrolü
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Maksimum limite ulaştık
        # ----------------------------------------------------

        if (
            current_count
            >= MAX_REVIEWS
        ):

            print(
                f"  {MAX_REVIEWS} "
                "yorum limitine ulaşıldı."
            )

            break

        # ----------------------------------------------------
        # Uzun süredir yeni yorum yok
        # ----------------------------------------------------

        if (
            stable_rounds
            >= MAX_STABLE_ROUNDS
        ):

            print(
                "  Yeni yorum gelmedi. "
                "Yükleme durduruldu."
            )

            break

    return all_reviews[
        :MAX_REVIEWS
    ]


# ============================================================
# YORUM SAYFASI
# ============================================================

def scrape_review_page(
    driver,
    product_url,
):

    review_url = (
        build_review_url(
            product_url
        )
    )

    print(
        "  Yorum URL:",
        review_url,
    )

    # --------------------------------------------------------
    # Eski network loglarını temizle
    # --------------------------------------------------------

    try:

        driver.get_log(
            "performance"
        )

    except Exception:

        pass

    # --------------------------------------------------------
    # Sayfayı aç
    # --------------------------------------------------------

    load_page(
        driver,
        review_url,
        REVIEW_PAGE_WAIT,
    )

    # --------------------------------------------------------
    # Yorumları yükle
    # --------------------------------------------------------

    reviews = (
        load_reviews_from_page(
            driver
        )
    )

    # --------------------------------------------------------
    # Genel istatistikler
    # --------------------------------------------------------

    soup = BeautifulSoup(
        driver.page_source,
        "html.parser",
    )

    page_text = clean_text(
        soup.get_text(
            " ",
            strip=True,
        )
    )

    statistics = (
        parse_review_statistics(
            page_text
        )
    )

    return {

        "review_url":
            review_url,

        "review_page_count":
            statistics[
                "review_count"
            ],

        "comment_count":
            statistics[
                "comment_count"
            ],

        # Her eleman = bir TAM yorum
        "reviews":
            reviews,
    }


# ============================================================
# ÜRÜN + YORUM BİRLEŞTİR
# ============================================================

def merge_product_and_reviews(
    product,
    review_data,
):

    product.update(
        review_data
    )

    if (
        is_missing(
            product.get(
                "review_count"
            )
        )
        and product.get(
            "review_page_count"
        )
    ):

        product[
            "review_count"
        ] = product[
            "review_page_count"
        ]

    return product


# ============================================================
# DRIVER
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

    # Performance / Network logları
    options.set_capability(
        "goog:loggingPrefs",
        {
            "performance":
                "ALL"
        }
    )

    service = Service(
        ChromeDriverManager()
        .install()
    )

    driver = webdriver.Chrome(
        service=service,
        options=options,
    )

    driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    # CDP Network aktif
    driver.execute_cdp_cmd(
        "Network.enable",
        {},
    )

    return driver


# ============================================================
# JSONL KAYDET
# ============================================================

def save_jsonl(
    records,
    filename,
):

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        for record in records:

            file.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                )
                + "\n"
            )


# ============================================================
# EXCEL FORMATINA ÇEVİR
# ============================================================

def prepare_excel_records(
    products,
):

    rows = []

    for product in products:

        reviews = product.get(
            "reviews",
            [],
        )

        rows.append(
            {

                "Ürün İsmi":
                    product.get(
                        "product_name"
                    ),

                "Marka":
                    product.get(
                        "brand"
                    ),

                "Fiyat":
                    product.get(
                        "price"
                    ),

                # Genel ürün puanı
                "Yıldız Puanı":
                    product.get(
                        "rating"
                    ),

                "Değerlendirme Sayısı":
                    product.get(
                        "review_count"
                    ),

                "Yorum Sayısı":
                    product.get(
                        "comment_count"
                    ),

                "Favori Sayısı":
                    product.get(
                        "favorite_count"
                    ),

                "Kategoriler":
                    " > ".join(
                        product.get(
                            "categories",
                            [],
                        )
                    ),

                "Teknik Özellikler":
                    json.dumps(
                        product.get(
                            "attributes",
                            {},
                        ),
                        ensure_ascii=False,
                    ),

                # --------------------------------------------
                # Her liste elemanı = bir tam kullanıcı yorumu
                # --------------------------------------------

                "Yorumlar":
                    json.dumps(
                        reviews,
                        ensure_ascii=False,
                    ),

                "Çekilen Yorum Sayısı":
                    len(
                        reviews
                    ),

                "Ürün Linki":
                    product.get(
                        "source_url"
                    ),

                "Yorum Linki":
                    product.get(
                        "review_url"
                    ),
            }
        )

    return rows



# ============================================================
# RESUME / DRIVER RECOVERY YARDIMCILARI
# ============================================================

def load_jsonl_records(filename):
    """
    JSONL dosyası varsa geçerli kayıtları yükler.
    Bozuk/yarım satırlar atlanır.
    """
    file_path = Path(filename)

    if not file_path.exists():
        return []

    records = []

    with file_path.open(
        "r",
        encoding="utf-8",
    ) as file:

        for line_number, line in enumerate(
            file,
            start=1,
        ):

            line = line.strip()

            if not line:
                continue

            try:

                record = json.loads(
                    line
                )

            except json.JSONDecodeError:

                print(
                    f"UYARI: {filename} "
                    f"satır {line_number} okunamadı, atlandı."
                )

                continue

            if isinstance(
                record,
                dict,
            ):

                records.append(
                    record
                )

    return records


def get_processed_urls(
    products,
):
    """
    Başarıyla scrape edilmiş ürün URL'lerini döndürür.
    """
    return {
        str(
            product.get(
                "source_url",
                "",
            )
        ).strip()
        for product in products
        if product.get(
            "source_url"
        )
    }


def save_outputs(
    products,
    errors,
):
    """
    JSONL + Excel + hata dosyasını tek noktadan kaydeder.
    Böylece crash olsa bile elde edilen veriler korunur.
    """
    save_jsonl(
        products,
        OUTPUT_JSONL,
    )

    excel_rows = (
        prepare_excel_records(
            products
        )
    )

    pd.DataFrame(
        excel_rows
    ).to_excel(
        OUTPUT_EXCEL,
        index=False,
    )

    save_jsonl(
        errors,
        ERROR_FILE,
    )


def safe_quit_driver(
    driver,
):
    """
    Çökmüş veya kapanmış driver'da quit hata verirse programı durdurmaz.
    """
    if driver is None:
        return

    try:

        driver.quit()

    except Exception:

        pass


def restart_driver(
    driver,
    reason=None,
):
    """
    Mevcut Chrome'u kapatır ve temiz bir Chrome oturumu açar.
    """
    if reason:

        print(
            f"\nDriver yeniden başlatılıyor. "
            f"Neden: {reason}"
        )

    safe_quit_driver(
        driver
    )

    time.sleep(
        DRIVER_RESTART_WAIT
    )

    new_driver = (
        create_driver()
    )

    print(
        "Yeni Chrome driver hazır."
    )

    return new_driver


def is_recoverable_driver_error(
    error,
):
    """
    Driver restart ile çözülebilecek hataları tespit eder.
    """
    text = str(
        error
    ).lower()

    keywords = [
        "tab crashed",
        "session deleted",
        "invalid session id",
        "chrome not reachable",
        "disconnected",
        "not connected to devtools",
        "target frame detached",
        "renderer",
        "timeout",
    ]

    return (
        isinstance(
            error,
            (
                WebDriverException,
                TimeoutException,
                InvalidSessionIdException,
            ),
        )
        or any(
            keyword in text
            for keyword in keywords
        )
    )


def upsert_error(
    errors,
    link,
    error,
    attempts,
):
    """
    Aynı URL için birden fazla hata satırı üretmek yerine
    son hatayı günceller.
    """
    error_record = {
        "url": link,
        "error": str(
            error
        ),
        "attempts": attempts,
    }

    for index, item in enumerate(
        errors
    ):

        if item.get(
            "url"
        ) == link:

            errors[
                index
            ] = error_record

            return

    errors.append(
        error_record
    )


def remove_error_for_url(
    errors,
    link,
):
    """
    Önceden hata alıp daha sonra başarıyla tamamlanan URL'yi
    hata listesinden çıkarır.
    """
    errors[:] = [
        item
        for item in errors
        if item.get(
            "url"
        ) != link
    ]


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # Excel oku
    # --------------------------------------------------------

    df = pd.read_excel(
        INPUT_FILE
    )

    if (
        LINK_COLUMN
        not in df.columns
    ):

        raise ValueError(
            f"'{LINK_COLUMN}' "
            "kolonu bulunamadı."
        )

    links = (
        df[
            LINK_COLUMN
        ]
        .dropna()
        .astype(str)
        .str.strip()
        .drop_duplicates()
        .tolist()
    )

    print(
        "Toplam input ürün:",
        len(
            links
        ),
    )

    # --------------------------------------------------------
    # Önceki başarılı kayıtları yükle
    # --------------------------------------------------------

    if RESUME_EXISTING:

        products = (
            load_jsonl_records(
                OUTPUT_JSONL
            )
        )

    else:

        products = []

    processed_urls = (
        get_processed_urls(
            products
        )
    )

    # Önceki hata dosyasını da yükle.
    # Başarılı olanlar ileride buradan çıkarılır.
    errors = (
        load_jsonl_records(
            ERROR_FILE
        )
    )

    # Daha önce başarılı olmuş URL'leri hata listesinden temizle
    errors = [
        error
        for error in errors
        if error.get(
            "url"
        )
        not in processed_urls
    ]

    remaining_links = [
        link
        for link in links
        if link
        not in processed_urls
    ]

    print(
        "Daha önce başarılı:",
        len(
            processed_urls
        ),
    )

    print(
        "Bu çalıştırmada işlenecek:",
        len(
            remaining_links
        ),
    )

    if not remaining_links:

        print(
            "İşlenecek yeni ürün yok. "
            "Tüm ürünler daha önce başarıyla tamamlanmış."
        )

        save_outputs(
            products,
            errors,
        )

        return

    # --------------------------------------------------------
    # Driver
    # --------------------------------------------------------

    driver = None

    processed_since_restart = 0

    successful_this_run = 0

    failed_this_run = 0

    try:

        driver = (
            create_driver()
        )

        for input_index, link in enumerate(
            remaining_links,
            start=1,
        ):

            original_index = (
                links.index(
                    link
                )
                + 1
            )

            print(
                "\n"
                + "=" * 80
            )

            print(
                f"[Input {original_index}/"
                f"{len(links)} | "
                f"Kalan {input_index}/"
                f"{len(remaining_links)}]"
            )

            print(
                link
            )

            # ------------------------------------------------
            # Periyodik driver restart
            # ------------------------------------------------

            if (
                processed_since_restart
                >= RESTART_DRIVER_EVERY
            ):

                driver = (
                    restart_driver(
                        driver,
                        reason=(
                            f"{RESTART_DRIVER_EVERY} "
                            "ürünlük periyodik bellek temizliği"
                        ),
                    )
                )

                processed_since_restart = 0

            product_success = False

            last_error = None

            for attempt in range(
                1,
                MAX_RETRIES_PER_PRODUCT + 1,
            ):

                print(
                    f"Deneme "
                    f"{attempt}/"
                    f"{MAX_RETRIES_PER_PRODUCT}"
                )

                try:

                    # ==========================================
                    # 1. ÜRÜN BİLGİLERİ
                    # ==========================================

                    product = (
                        scrape_product_page(
                            driver,
                            link,
                        )
                    )

                    # ==========================================
                    # 2. YORUMLAR
                    # ==========================================

                    review_data = (
                        scrape_review_page(
                            driver,
                            link,
                        )
                    )

                    # ==========================================
                    # 3. BİRLEŞTİR
                    # ==========================================

                    product = (
                        merge_product_and_reviews(
                            product,
                            review_data,
                        )
                    )

                    # ==========================================
                    # LOG
                    # ==========================================

                    print(
                        "Ürün:",
                        product[
                            "product_name"
                        ],
                    )

                    print(
                        "Fiyat:",
                        product[
                            "price"
                        ],
                    )

                    print(
                        "Yıldız:",
                        product[
                            "rating"
                        ],
                    )

                    print(
                        "Değerlendirme:",
                        product[
                            "review_count"
                        ],
                    )

                    print(
                        "Yorum sayısı:",
                        product[
                            "comment_count"
                        ],
                    )

                    print(
                        "Favori:",
                        product[
                            "favorite_count"
                        ],
                    )

                    print(
                        "Teknik özellik:",
                        len(
                            product[
                                "attributes"
                            ]
                        ),
                    )

                    print(
                        "Gerçek çekilen yorum:",
                        len(
                            product[
                                "reviews"
                            ]
                        ),
                    )

                    # ==========================================
                    # BAŞARILI KAYIT
                    # ==========================================

                    products.append(
                        product
                    )

                    processed_urls.add(
                        link
                    )

                    remove_error_for_url(
                        errors,
                        link,
                    )

                    product_success = True

                    successful_this_run += 1

                    processed_since_restart += 1

                    # Her başarılı ürün sonrası diske yaz
                    save_outputs(
                        products,
                        errors,
                    )

                    break

                except Exception as error:

                    last_error = error

                    print(
                        "HATA:",
                        error,
                    )

                    recoverable = (
                        is_recoverable_driver_error(
                            error
                        )
                    )

                    # Her hatada mevcut sonuçları hemen kaydet
                    upsert_error(
                        errors,
                        link,
                        error,
                        attempt,
                    )

                    save_outputs(
                        products,
                        errors,
                    )

                    # Son deneme değilse driver'ı yenileyip aynı ürünü tekrar dene
                    if (
                        attempt
                        < MAX_RETRIES_PER_PRODUCT
                    ):

                        reason = (
                            "recoverable driver hatası"
                            if recoverable
                            else "ürün scrape hatası sonrası temiz oturum"
                        )

                        driver = (
                            restart_driver(
                                driver,
                                reason=reason,
                            )
                        )

                        processed_since_restart = 0

                        continue

                    # Son denemede başarısız kaldı
                    break

            if not product_success:

                failed_this_run += 1

                print(
                    f"ÜRÜN BAŞARISIZ: "
                    f"{MAX_RETRIES_PER_PRODUCT} "
                    "denemeden sonra atlandı."
                )

                if last_error is not None:

                    upsert_error(
                        errors,
                        link,
                        last_error,
                        MAX_RETRIES_PER_PRODUCT,
                    )

                # Bir sonraki ürüne temiz driver ile geç
                driver = (
                    restart_driver(
                        driver,
                        reason=(
                            "başarısız ürün sonrası "
                            "bir sonraki ürüne temiz oturumla geçiş"
                        ),
                    )
                )

                processed_since_restart = 0

                save_outputs(
                    products,
                    errors,
                )

            time.sleep(
                PRODUCT_DELAY
            )

    except KeyboardInterrupt:

        print(
            "\nKullanıcı tarafından durduruldu. "
            "Mevcut sonuçlar kaydediliyor..."
        )

    finally:

        safe_quit_driver(
            driver
        )

        # ====================================================
        # FINAL KAYIT
        # ====================================================

        save_outputs(
            products,
            errors,
        )

    # ========================================================
    # SONUÇ
    # ========================================================

    print(
        "\n"
        + "=" * 80
    )

    print(
        "SCRAPING TAMAMLANDI"
    )

    print(
        "=" * 80
    )

    print(
        "Toplam input ürün:",
        len(
            links
        ),
    )

    print(
        "Toplam başarılı kayıt:",
        len(
            products
        ),
    )

    print(
        "Bu çalıştırmada yeni başarılı:",
        successful_this_run,
    )

    print(
        "Bu çalıştırmada başarısız:",
        failed_this_run,
    )

    print(
        "Hata dosyasında kalan URL:",
        len(
            errors
        ),
    )

    print(
        "JSONL:",
        Path(
            OUTPUT_JSONL
        ).resolve(),
    )

    print(
        "Excel:",
        Path(
            OUTPUT_EXCEL
        ).resolve(),
    )

    print(
        "Hatalar:",
        Path(
            ERROR_FILE
        ).resolve(),
    )


# ============================================================
# PROGRAM
# ============================================================

if __name__ == "__main__":

    main()