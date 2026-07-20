import json
import math
import random
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path


# ============================================================
# AYARLAR
# ============================================================

PRODUCT_FILE = (
    "scraping/trendyol_electronics_products.jsonl"
)

COMPARISON_FILE = (
    "comparison_chat_dataset.json"
)

OUTPUT_FILE = (
    "recommendation_chat_dataset.json"
)

RANDOM_SEED = 42

# Bir öneri cevabında maksimum kaç ürün sıralansın?
TOP_N_RECOMMENDATIONS = 3

# Bir grupta öneri üretmek için minimum ürün
MIN_PRODUCTS_PER_GROUP = 3

# Marka + kategori başına maksimum kaç recommendation örneği
MAX_RECOMMENDATIONS_PER_GROUP = 5


random.seed(
    RANDOM_SEED
)


# ============================================================
# EKSİK DEĞERLER
# ============================================================

MISSING_VALUES = {
    None,
    "",
    "Fiyat Bulunamadı",
    "Puan Bulunamadı",
    "Değerlendirme Sayısı Bulunamadı",
    "Favori Sayısı Bulunamadı",
    "Ürün İsmi Bulunamadı",
    "Marka Bulunamadı",
}


def is_valid(value):

    if value in MISSING_VALUES:
        return False

    if isinstance(
        value,
        str,
    ):

        return bool(
            value.strip()
        )

    return True


def clean_text(text):

    if text is None:
        return None

    return re.sub(
        r"\s+",
        " ",
        str(text),
    ).strip()


# ============================================================
# FİYAT PARSE
# ============================================================

def parse_price(price):

    if not is_valid(
        price
    ):
        return None

    text = (
        str(price)
        .upper()
        .replace(
            "TRY",
            "",
        )
        .replace(
            "TL",
            "",
        )
        .replace(
            "₺",
            "",
        )
        .strip()
    )

    # 47.799,00
    if (
        "."
        in text
        and ","
        in text
    ):

        text = (
            text
            .replace(
                ".",
                "",
            )
            .replace(
                ",",
                ".",
            )
        )

    # 24.597
    elif (
        text.count(".")
        == 1
    ):

        left, right = (
            text.split(".")
        )

        if len(
            right
        ) == 3:

            text = (
                left
                + right
            )

    elif "," in text:

        text = (
            text.replace(
                ",",
                ".",
            )
        )

    text = re.sub(
        r"[^\d.]",
        "",
        text,
    )

    try:

        return Decimal(
            text
        )

    except (
        InvalidOperation,
        ValueError,
    ):

        return None


def format_price(
    price,
):

    if price is None:
        return None

    value = float(
        price
    )

    return (
        f"{value:,.2f}"
        .replace(
            ",",
            "X",
        )
        .replace(
            ".",
            ",",
        )
        .replace(
            "X",
            ".",
        )
        + " TL"
    )


# ============================================================
# SAYISAL PARSE
# ============================================================

def parse_float(
    value,
):

    if not is_valid(
        value
    ):
        return None

    try:

        return float(
            str(value)
            .replace(
                ",",
                ".",
            )
        )

    except ValueError:

        return None


def parse_int(
    value,
):

    if not is_valid(
        value
    ):
        return 0

    text = re.sub(
        r"[^\d]",
        "",
        str(value),
    )

    if not text:
        return 0

    try:

        return int(
            text
        )

    except ValueError:

        return 0


# ============================================================
# KATEGORİ BELİRLEME
# ============================================================

def get_category(
    product,
):

    categories = product.get(
        "categories",
        [],
    )

    if not categories:
        return "Bilinmeyen"

    categories = [
        clean_text(
            category
        )
        for category
        in categories
        if clean_text(
            category
        )
    ]

    ignored = {
        "Trendyol",
        "Elektronik",
    }

    categories = [
        category
        for category
        in categories
        if category
        not in ignored
    ]

    if not categories:
        return "Bilinmeyen"

    brand = (
        product.get(
            "brand",
            "",
        )
        or ""
    ).lower()

    # Örnek:
    # Laptop > LENOVO Laptop
    #
    # LENOVO Laptop yerine Laptop kullan
    if (
        len(
            categories
        ) >= 2
        and brand
        and brand
        in categories[
            -1
        ].lower()
    ):

        return categories[
            -2
        ]

    return categories[
        -1
    ]


# ============================================================
# ÜRÜNLERİ YÜKLE
# ============================================================

def load_products():

    products = []

    with open(
        PRODUCT_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = (
                line.strip()
            )

            if not line:
                continue

            try:

                product = (
                    json.loads(
                        line
                    )
                )

            except (
                json.JSONDecodeError
            ):

                continue

            if not is_valid(
                product.get(
                    "product_name"
                )
            ):

                continue

            product[
                "_price"
            ] = parse_price(
                product.get(
                    "price"
                )
            )

            product[
                "_rating"
            ] = parse_float(
                product.get(
                    "rating"
                )
            )

            product[
                "_review_count"
            ] = parse_int(
                product.get(
                    "review_count"
                )
            )

            product[
                "_category"
            ] = get_category(
                product
            )

            products.append(
                product
            )

    return products


# ============================================================
# COMPARISON DATASET YÜKLE
# ============================================================

def load_comparison_dataset():

    if not Path(
        COMPARISON_FILE
    ).exists():

        raise FileNotFoundError(
            f"{COMPARISON_FILE} "
            "bulunamadı."
        )

    with open(
        COMPARISON_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        return json.load(
            file
        )


# ============================================================
# CHAT KAYDI
# ============================================================

def create_chat_record(
    question,
    answer,
):

    return {
        "messages": [
            {
                "role":
                    "user",

                "content":
                    question,
            },
            {
                "role":
                    "assistant",

                "content":
                    answer,
            },
        ]
    }


# ============================================================
# FİYAT PERFORMANS SKORU
# ============================================================

def calculate_value_score(
    product,
    group,
):
    """
    Basit ve açıklanabilir bir fiyat-performans skoru.

    Kullanılan faktörler:

    - fiyat
    - rating
    - değerlendirme sayısı
    - teknik özellik doluluğu

    Bu skor gerçek bir benchmark değildir.
    Dataset içindeki ürünleri göreli sıralamak için kullanılır.
    """

    price = product.get(
        "_price"
    )

    rating = product.get(
        "_rating"
    )

    review_count = product.get(
        "_review_count",
        0,
    )

    attributes = product.get(
        "attributes",
        {},
    )

    if (
        price is None
        or rating is None
    ):

        return None

    valid_prices = [
        float(
            p["_price"]
        )
        for p
        in group
        if p.get(
            "_price"
        )
        is not None
    ]

    if not valid_prices:
        return None

    min_price = min(
        valid_prices
    )

    max_price = max(
        valid_prices
    )

    current_price = float(
        price
    )

    # Daha ucuz ürün daha yüksek fiyat skoru
    if (
        max_price
        == min_price
    ):

        price_score = 1.0

    else:

        price_score = (
            max_price
            - current_price
        ) / (
            max_price
            - min_price
        )

    # Rating 5 üzerinden
    rating_score = (
        rating
        / 5.0
    )

    # Çok yüksek review count değerlerinin
    # skoru domine etmesini engellemek için log
    review_score = min(
        math.log10(
            review_count
            + 1
        )
        / 4,
        1.0,
    )

    # Teknik özellik doluluğu
    attribute_score = min(
        len(
            attributes
        )
        / 30,
        1.0,
    )

    final_score = (
        0.35
        * price_score
        +
        0.35
        * rating_score
        +
        0.20
        * review_score
        +
        0.10
        * attribute_score
    )

    return final_score


# ============================================================
# ÜRÜN AÇIKLAMASI
# ============================================================

def describe_product(
    product,
):

    parts = [
        product[
            "product_name"
        ]
    ]

    price = product.get(
        "_price"
    )

    rating = product.get(
        "_rating"
    )

    review_count = product.get(
        "_review_count",
        0,
    )

    if price is not None:

        parts.append(
            f"fiyatı "
            f"{format_price(price)}"
        )

    if rating is not None:

        parts.append(
            f"kullanıcı puanı "
            f"{rating:g}"
        )

    if review_count:

        parts.append(
            f"{review_count} "
            "değerlendirmeye sahip"
        )

    return ", ".join(
        parts
    )


# ============================================================
# FİYAT PERFORMANS ÖNERİSİ
# ============================================================

def generate_price_performance_recommendation(
    brand,
    category,
    group,
):

    scored = []

    for product in group:

        score = (
            calculate_value_score(
                product,
                group,
            )
        )

        if score is None:
            continue

        scored.append(
            (
                score,
                product,
            )
        )

    if len(
        scored
    ) < 2:

        return None

    scored.sort(
        key=lambda item:
        item[0],
        reverse=True,
    )

    top_products = scored[
        :TOP_N_RECOMMENDATIONS
    ]

    question = (
        f"En iyi fiyat performans "
        f"{brand} {category} önerisinde bulun."
    )

    best_score, best = (
        top_products[0]
    )

    answer = (
        f"Veri setindeki {brand} {category} ürünleri "
        "fiyat, kullanıcı puanı, değerlendirme sayısı ve "
        "teknik özellik doluluğu birlikte değerlendirilerek "
        f"sıralandığında {best['product_name']} öne çıkmaktadır. "
        f"{describe_product(best)}."
    )

    if len(
        top_products
    ) > 1:

        alternatives = [
            describe_product(
                product
            )
            for _,
            product
            in top_products[
                1:
            ]
        ]

        answer += (
            " Alternatif olarak "
            + "; ".join(
                alternatives
            )
            + " modelleri de değerlendirilebilir."
        )

    answer += (
        " Bu öneri yalnızca veri setinde bulunan ürünler "
        "ve mevcut fiyat/değerlendirme bilgileri üzerinden yapılmıştır."
    )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# EN YÜKSEK PUANLI ÜRÜN
# ============================================================

def generate_best_rated_recommendation(
    brand,
    category,
    group,
):

    valid = [
        product
        for product
        in group
        if product.get(
            "_rating"
        )
        is not None
    ]

    if len(
        valid
    ) < 2:

        return None

    valid.sort(
        key=lambda product:
        (
            product[
                "_rating"
            ],
            product.get(
                "_review_count",
                0,
            ),
        ),
        reverse=True,
    )

    best = valid[0]

    question = (
        f"Kullanıcı puanına göre en iyi "
        f"{brand} {category} hangisi?"
    )

    answer = (
        f"Veri setindeki {brand} {category} ürünleri arasında "
        f"{best['product_name']} {best['_rating']:g} kullanıcı puanıyla "
        "en yüksek puanlı seçeneklerden biri olarak öne çıkmaktadır"
    )

    if best.get(
        "_review_count"
    ):

        answer += (
            f" ve {best['_review_count']} "
            "değerlendirmeye sahiptir"
        )

    answer += "."

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# BÜTÇE ÖNERİSİ
# ============================================================

def generate_budget_recommendation(
    brand,
    category,
    group,
):

    priced = [
        product
        for product
        in group
        if product.get(
            "_price"
        )
        is not None
    ]

    if len(
        priced
    ) < 3:

        return None

    prices = sorted(
        float(
            product[
                "_price"
            ]
        )
        for product
        in priced
    )

    # Yaklaşık median fiyatı bütçe sınırı yap
    median_price = prices[
        len(
            prices
        )
        // 2
    ]

    budget = Decimal(
        str(
            round(
                median_price
                / 1000
            )
            * 1000
        )
    )

    candidates = [
        product
        for product
        in priced
        if product[
            "_price"
        ]
        <= budget
    ]

    if not candidates:
        return None

    candidates.sort(
        key=lambda product:
        (
            product.get(
                "_rating"
            )
            or 0,
            product.get(
                "_review_count"
            )
            or 0,
        ),
        reverse=True,
    )

    best = candidates[0]

    question = (
        f"{format_price(budget)} bütçeyle "
        f"hangi {brand} {category} modelini önerirsin?"
    )

    answer = (
        f"{format_price(budget)} bütçe sınırı içinde "
        f"veri setindeki seçenekler değerlendirildiğinde "
        f"{best['product_name']} öne çıkmaktadır. "
        f"{describe_product(best)}."
    )

    answer += (
        " Bu seçim bütçe sınırı içindeki ürünlerin kullanıcı puanı "
        "ve değerlendirme sayısı dikkate alınarak yapılmıştır."
    )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# EN UYGUN FİYATLI ÖNERİ
# ============================================================

def generate_cheapest_recommendation(
    brand,
    category,
    group,
):

    valid = [
        product
        for product
        in group
        if product.get(
            "_price"
        )
        is not None
    ]

    if len(
        valid
    ) < 2:

        return None

    cheapest = min(
        valid,
        key=lambda product:
        product[
            "_price"
        ],
    )

    question = (
        f"En uygun fiyatlı "
        f"{brand} {category} hangisi?"
    )

    answer = (
        f"Veri setindeki {brand} {category} seçenekleri arasında "
        f"en düşük fiyatlı ürün {cheapest['product_name']} olarak "
        f"görünmektedir. Listelenen fiyatı "
        f"{format_price(cheapest['_price'])}."
    )

    if cheapest.get(
        "_rating"
    ) is not None:

        answer += (
            f" Kullanıcı puanı "
            f"{cheapest['_rating']:g}."
        )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# RECOMMENDATION ÜRET
# ============================================================

def generate_recommendations(
    products,
):

    groups = defaultdict(
        list
    )

    for product in products:

        brand = clean_text(
            product.get(
                "brand"
            )
        )

        category = product.get(
            "_category"
        )

        if (
            not brand
            or category
            == "Bilinmeyen"
        ):

            continue

        groups[
            (
                brand,
                category,
            )
        ].append(
            product
        )

    dataset = []

    for (
        brand,
        category,
    ), group in groups.items():

        if len(
            group
        ) < MIN_PRODUCTS_PER_GROUP:

            continue

        generators = [
            generate_price_performance_recommendation,
            generate_best_rated_recommendation,
            generate_budget_recommendation,
            generate_cheapest_recommendation,
        ]

        count = 0

        for generator in generators:

            record = (
                generator(
                    brand,
                    category,
                    group,
                )
            )

            if not record:
                continue

            dataset.append(
                record
            )

            count += 1

            if (
                count
                >= MAX_RECOMMENDATIONS_PER_GROUP
            ):

                break

    return dataset


# ============================================================
# DUPLICATE TEMİZLE
# ============================================================

def remove_duplicates(
    dataset,
):

    result = []

    seen_questions = set()

    for record in dataset:

        try:

            question = (
                record[
                    "messages"
                ][0][
                    "content"
                ]
            )

        except (
            KeyError,
            IndexError,
        ):

            continue

        key = (
            question
            .lower()
            .strip()
        )

        if key in seen_questions:
            continue

        seen_questions.add(
            key
        )

        result.append(
            record
        )

    return result


# ============================================================
# JSON KAYDET
# ============================================================

def save_json(
    records,
    filename,
):

    with open(
        filename,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            records,
            file,
            ensure_ascii=False,
            indent=2,
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "Comparison dataset yükleniyor..."
    )

    comparison_dataset = (
        load_comparison_dataset()
    )

    print(
        "Comparison kayıt sayısı:",
        len(
            comparison_dataset
        ),
    )

    print(
        "\nÜrün verileri yükleniyor..."
    )

    products = (
        load_products()
    )

    print(
        "Toplam ürün:",
        len(
            products
        ),
    )

    print(
        "\nRecommendation örnekleri oluşturuluyor..."
    )

    recommendations = (
        generate_recommendations(
            products
        )
    )

    print(
        "Yeni recommendation kaydı:",
        len(
            recommendations
        ),
    )

    # ========================================================
    # COMPARISON + RECOMMENDATION
    # ========================================================

    final_dataset = (
        comparison_dataset
        + recommendations
    )

    final_dataset = (
        remove_duplicates(
            final_dataset
        )
    )

    random.shuffle(
        final_dataset
    )

    # ========================================================
    # KAYDET
    # ========================================================

    save_json(
        final_dataset,
        OUTPUT_FILE,
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "RECOMMENDATION CHAT DATASET HAZIR"
    )

    print(
        "=" * 70
    )

    print(
        "Comparison kayıtları:",
        len(
            comparison_dataset
        ),
    )

    print(
        "Recommendation kayıtları:",
        len(
            recommendations
        ),
    )

    print(
        "Final birleşik dataset:",
        len(
            final_dataset
        ),
    )

    print(
        "\nDosya:"
    )

    print(
        Path(
            OUTPUT_FILE
        ).resolve()
    )

    if recommendations:

        print(
            "\nÖrnek recommendation:"
        )

        print(
            json.dumps(
                recommendations[0],
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()