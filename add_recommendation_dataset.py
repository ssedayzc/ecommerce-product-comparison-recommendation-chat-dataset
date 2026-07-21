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
    "recommendation_chat_dataset_v2.json"
)

RANDOM_SEED = 42

# Recommendation hedefi
TARGET_RECOMMENDATION_COUNT = 2500

# Bir cevapta gösterilecek maksimum ürün
TOP_N_RECOMMENDATIONS = 3

# Grup oluşturmak için minimum ürün
MIN_PRODUCTS_PER_GROUP = 2

# Rating filtresi
MIN_GOOD_RATING = 4.0

# Teknik özellik önerilerinde minimum eşleşen ürün
MIN_ATTRIBUTE_MATCH_COUNT = 2


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

    except (
        ValueError,
        TypeError,
    ):

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
# KATEGORİ
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

    # LENOVO Laptop -> Laptop
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

            except json.JSONDecodeError:

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

            product[
                "_brand"
            ] = clean_text(
                product.get(
                    "brand"
                )
            )

            products.append(
                product
            )

    return products


# ============================================================
# COMPARISON DATASET
# ============================================================

def load_comparison_dataset():

    path = Path(
        COMPARISON_FILE
    )

    if not path.exists():

        raise FileNotFoundError(
            f"{COMPARISON_FILE} bulunamadı."
        )

    with open(
        path,
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
                "role": "user",
                "content": question,
            },
            {
                "role": "assistant",
                "content": answer,
            },
        ]
    }


# ============================================================
# ÜRÜN TANIMI
# ============================================================

def describe_product(
    product,
):

    name = product[
        "product_name"
    ]

    parts = [
        name
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
            format_price(
                price
            )
        )

    if rating is not None:

        parts.append(
            f"{rating:g} puan"
        )

    if review_count:

        parts.append(
            f"{review_count} değerlendirme"
        )

    return ", ".join(
        parts
    )


# ============================================================
# FİYAT PERFORMANS SKORU
# ============================================================

def calculate_value_score(
    product,
    group,
):

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

    if len(
        valid_prices
    ) < 2:

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

    rating_score = (
        rating
        / 5.0
    )

    review_score = min(
        math.log10(
            review_count
            + 1
        )
        / 4,
        1.0,
    )

    attribute_score = min(
        len(
            attributes
        )
        / 30,
        1.0,
    )

    return (
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


# ============================================================
# GRUP İÇİN EN İYİ F/P
# ============================================================

def get_best_value_products(
    group,
    limit=3,
):

    scored = []

    for product in group:

        score = calculate_value_score(
            product,
            group,
        )

        if score is None:
            continue

        scored.append(
            (
                score,
                product,
            )
        )

    scored.sort(
        key=lambda item:
        item[0],
        reverse=True,
    )

    return [
        product
        for score,
        product
        in scored[
            :limit
        ]
    ]


# ============================================================
# KISA CEVAP OLUŞTUR
# ============================================================

def recommendation_answer(
    best,
    alternatives=None,
    reason=None,
):

    answer = (
        f"{best['product_name']} öne çıkıyor. "
        f"{describe_product(best)}."
    )

    if reason:

        answer += (
            " "
            + reason
        )

    if alternatives:

        alt_text = "; ".join(
            describe_product(
                product
            )
            for product
            in alternatives[
                :2
            ]
        )

        answer += (
            " Alternatif olarak "
            + alt_text
            + " değerlendirilebilir."
        )

    return answer


# ============================================================
# F/P ÖNERİLERİ
# ============================================================

def generate_value_records(
    label,
    group,
):

    best_products = (
        get_best_value_products(
            group,
            TOP_N_RECOMMENDATIONS,
        )
    )

    if len(
        best_products
    ) < 1:

        return []

    best = best_products[
        0
    ]

    alternatives = best_products[
        1:
    ]

    questions = [

        (
            f"En iyi fiyat performans "
            f"{label} hangisi?"
        ),

        (
            f"Fiyat performans açısından "
            f"hangi {label} modelini önerirsin?"
        ),

        (
            f"{label} almak istiyorum. "
            "Fiyat performans açısından "
            "hangi ürünü seçmeliyim?"
        ),

        (
            f"Uygun fiyatlı ve iyi puanlı "
            f"bir {label} önerir misin?"
        ),
    ]

    answer = recommendation_answer(
        best,
        alternatives,
        (
            "Öneri fiyat, kullanıcı puanı, "
            "değerlendirme sayısı ve mevcut "
            "teknik özellikler birlikte dikkate "
            "alınarak yapılmıştır."
        ),
    )

    return [
        create_chat_record(
            question,
            answer,
        )
        for question
        in questions
    ]


# ============================================================
# EN YÜKSEK PUAN
# ============================================================

def generate_rating_records(
    label,
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

    if not valid:
        return []

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

    best = valid[
        0
    ]

    alternatives = valid[
        1:3
    ]

    questions = [

        f"En yüksek puanlı {label} hangisi?",

        (
            f"Kullanıcı puanlarına göre "
            f"hangi {label} modelini önerirsin?"
        ),

        (
            f"Kullanıcıların en çok beğendiği "
            f"{label} seçeneklerinden birini öner."
        ),
    ]

    answer = recommendation_answer(
        best,
        alternatives,
        (
            "Seçim kullanıcı puanı ve "
            "değerlendirme sayısına göre yapılmıştır."
        ),
    )

    return [
        create_chat_record(
            question,
            answer,
        )
        for question
        in questions
    ]


# ============================================================
# EN ÇOK DEĞERLENDİRME
# ============================================================

def generate_popularity_records(
    label,
    group,
):

    valid = [
        product
        for product
        in group
        if product.get(
            "_review_count",
            0,
        ) > 0
    ]

    if not valid:
        return []

    valid.sort(
        key=lambda product:
        product.get(
            "_review_count",
            0,
        ),
        reverse=True,
    )

    best = valid[
        0
    ]

    alternatives = valid[
        1:3
    ]

    questions = [

        (
            f"En çok değerlendirilen "
            f"{label} hangisi?"
        ),

        (
            f"Popüler bir {label} "
            "önerisinde bulun."
        ),

        (
            f"Kullanıcılar tarafından çok "
            f"değerlendirilen bir {label} öner."
        ),
    ]

    answer = recommendation_answer(
        best,
        alternatives,
        (
            "Bu öneri değerlendirme sayısı "
            "önceliklendirilerek yapılmıştır."
        ),
    )

    return [
        create_chat_record(
            question,
            answer,
        )
        for question
        in questions
    ]


# ============================================================
# EN UCUZ
# ============================================================

def generate_cheapest_records(
    label,
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

    if not valid:
        return []

    valid.sort(
        key=lambda product:
        product[
            "_price"
        ],
    )

    cheapest = valid[
        0
    ]

    alternatives = valid[
        1:3
    ]

    questions = [

        f"En uygun fiyatlı {label} hangisi?",

        (
            f"Bütçemi düşük tutmak istiyorum. "
            f"Hangi {label} modelini önerirsin?"
        ),

        (
            f"Ekonomik bir {label} "
            "önerisinde bulun."
        ),
    ]

    answer = recommendation_answer(
        cheapest,
        alternatives,
        (
            "Bu seçim mevcut ürünler "
            "arasındaki fiyat bilgilerine dayanmaktadır."
        ),
    )

    return [
        create_chat_record(
            question,
            answer,
        )
        for question
        in questions
    ]


# ============================================================
# BÜTÇE ÖNERİLERİ
# ============================================================

def create_budget_levels(
    group,
):

    prices = sorted(
        [
            float(
                product[
                    "_price"
                ]
            )
            for product
            in group
            if product.get(
                "_price"
            )
            is not None
        ]
    )

    if len(
        prices
    ) < 2:

        return []

    # Farklı percentile benzeri bütçe seviyeleri
    indexes = [
        int(
            len(
                prices
            )
            * 0.35
        ),
        int(
            len(
                prices
            )
            * 0.55
        ),
        int(
            len(
                prices
            )
            * 0.75
        ),
        len(
            prices
        )
        - 1,
    ]

    budgets = set()

    for index in indexes:

        index = min(
            index,
            len(
                prices
            )
            - 1,
        )

        raw = prices[
            index
        ]

        rounded = max(
            1000,
            round(
                raw
                / 1000
            )
            * 1000,
        )

        budgets.add(
            Decimal(
                str(
                    rounded
                )
            )
        )

    return sorted(
        budgets
    )


def generate_budget_records(
    label,
    group,
):

    records = []

    budgets = (
        create_budget_levels(
            group
        )
    )

    for budget in budgets:

        candidates = [
            product
            for product
            in group
            if (
                product.get(
                    "_price"
                )
                is not None
                and product[
                    "_price"
                ]
                <= budget
            )
        ]

        if not candidates:
            continue

        # Bütçe içindeki ürünlerde F/P
        best_list = (
            get_best_value_products(
                candidates,
                3,
            )
        )

        if not best_list:

            # Skor oluşmadıysa rating'e göre
            candidates.sort(
                key=lambda product:
                (
                    product.get(
                        "_rating"
                    )
                    or 0,
                    product.get(
                        "_review_count",
                        0,
                    ),
                ),
                reverse=True,
            )

            best_list = candidates[
                :3
            ]

        best = best_list[
            0
        ]

        alternatives = best_list[
            1:
        ]

        questions = [

            (
                f"{format_price(budget)} bütçeyle "
                f"hangi {label} modelini önerirsin?"
            ),

            (
                f"{format_price(budget)} altında "
                f"iyi bir {label} öner."
            ),

            (
                f"Bütçem {format_price(budget)}. "
                f"Hangi {label} daha mantıklı?"
            ),
        ]

        answer = recommendation_answer(
            best,
            alternatives,
            (
                f"Bu ürün {format_price(budget)} "
                "bütçe sınırı içindeki seçenekler "
                "arasından seçilmiştir."
            ),
        )

        for question in questions:

            records.append(
                create_chat_record(
                    question,
                    answer,
                )
            )

    return records


# ============================================================
# YÜKSEK PUAN + UYGUN FİYAT
# ============================================================

def generate_affordable_high_rating_records(
    label,
    group,
):

    valid = [
        product
        for product
        in group
        if (
            product.get(
                "_price"
            )
            is not None
            and product.get(
                "_rating"
            )
            is not None
            and product[
                "_rating"
            ]
            >= MIN_GOOD_RATING
        )
    ]

    if len(
        valid
    ) < 2:

        return []

    valid.sort(
        key=lambda product:
        (
            product[
                "_price"
            ],
            -product[
                "_rating"
            ],
        )
    )

    best = valid[
        0
    ]

    alternatives = valid[
        1:3
    ]

    questions = [

        (
            f"Uygun fiyatlı ama yüksek puanlı "
            f"bir {label} önerir misin?"
        ),

        (
            f"Hem ekonomik hem kullanıcı puanı "
            f"iyi olan bir {label} arıyorum."
        ),

        (
            f"Fiyatı uygun ve kullanıcıları memnun "
            f"eden bir {label} öner."
        ),
    ]

    answer = recommendation_answer(
        best,
        alternatives,
        (
            f"Seçilen ürünün kullanıcı puanı "
            f"{best['_rating']:g} ve fiyatı "
            f"{format_price(best['_price'])}."
        ),
    )

    return [
        create_chat_record(
            question,
            answer,
        )
        for question
        in questions
    ]


# ============================================================
# TEKNİK ÖZELLİK BAZLI ÖNERİLER
# ============================================================

IMPORTANT_ATTRIBUTE_KEYWORDS = [

    "ram",
    "bellek",
    "ssd",
    "disk",
    "işlemci",
    "ekran kartı",
    "gpu",
    "ekran boyutu",
    "çözünürlük",
    "kapasite",
]


def normalize_attribute_key(
    key,
):

    return (
        clean_text(
            key
        )
        .lower()
    )


def generate_attribute_records(
    label,
    group,
):

    attribute_groups = defaultdict(
        list
    )

    for product in group:

        attributes = product.get(
            "attributes",
            {},
        )

        for key, value in (
            attributes.items()
        ):

            key_clean = (
                normalize_attribute_key(
                    key
                )
            )

            value_clean = (
                clean_text(
                    value
                )
            )

            if not value_clean:
                continue

            if not any(
                keyword
                in key_clean
                for keyword
                in IMPORTANT_ATTRIBUTE_KEYWORDS
            ):
                continue

            attribute_groups[
                (
                    key_clean,
                    value_clean,
                )
            ].append(
                product
            )

    records = []

    # Çok fazla teknik örnek üretmemek için
    candidates = []

    for (
        key,
        value,
    ), products in (
        attribute_groups.items()
    ):

        if len(
            products
        ) < MIN_ATTRIBUTE_MATCH_COUNT:

            continue

        candidates.append(
            (
                key,
                value,
                products,
            )
        )

    random.shuffle(
        candidates
    )

    # Grup başına maksimum 10 teknik özellik varyasyonu
    for (
        key,
        value,
        products,
    ) in candidates[
        :10
    ]:

        best_list = (
            get_best_value_products(
                products,
                3,
            )
        )

        if not best_list:

            continue

        best = best_list[
            0
        ]

        alternatives = best_list[
            1:
        ]

        questions = [

            (
                f"{value} {key} özelliğine sahip "
                f"bir {label} önerir misin?"
            ),

            (
                f"{key} değeri {value} olan "
                f"iyi bir {label} hangisi?"
            ),
        ]

        answer = recommendation_answer(
            best,
            alternatives,
            (
                f"Bu ürünün {key} bilgisi "
                f"{value} olarak listelenmiştir."
            ),
        )

        for question in questions:

            records.append(
                create_chat_record(
                    question,
                    answer,
                )
            )

    return records


# ============================================================
# TEK GRUPTAN TÜM ÖNERİLER
# ============================================================

def generate_group_records(
    label,
    group,
):

    if len(
        group
    ) < MIN_PRODUCTS_PER_GROUP:

        return []

    records = []

    records.extend(
        generate_value_records(
            label,
            group,
        )
    )

    records.extend(
        generate_rating_records(
            label,
            group,
        )
    )

    records.extend(
        generate_popularity_records(
            label,
            group,
        )
    )

    records.extend(
        generate_cheapest_records(
            label,
            group,
        )
    )

    records.extend(
        generate_budget_records(
            label,
            group,
        )
    )

    records.extend(
        generate_affordable_high_rating_records(
            label,
            group,
        )
    )

    records.extend(
        generate_attribute_records(
            label,
            group,
        )
    )

    return records


# ============================================================
# RECOMMENDATION ÜRETİMİ
# ============================================================

def generate_recommendations(
    products,
):

    # 1. Kategori grupları
    category_groups = defaultdict(
        list
    )

    # 2. Marka + kategori grupları
    brand_category_groups = defaultdict(
        list
    )

    # 3. Marka grupları
    brand_groups = defaultdict(
        list
    )

    for product in products:

        category = product.get(
            "_category"
        )

        brand = product.get(
            "_brand"
        )

        if (
            category
            and category
            != "Bilinmeyen"
        ):

            category_groups[
                category
            ].append(
                product
            )

        if brand:

            brand_groups[
                brand
            ].append(
                product
            )

        if (
            brand
            and category
            and category
            != "Bilinmeyen"
        ):

            brand_category_groups[
                (
                    brand,
                    category,
                )
            ].append(
                product
            )

    dataset = []

    # ========================================================
    # SADECE KATEGORİ
    # ========================================================

    for (
        category,
        group,
    ) in category_groups.items():

        label = category

        dataset.extend(
            generate_group_records(
                label,
                group,
            )
        )

    # ========================================================
    # MARKA + KATEGORİ
    # ========================================================

    for (
        brand,
        category,
    ), group in (
        brand_category_groups.items()
    ):

        label = (
            f"{brand} {category}"
        )

        dataset.extend(
            generate_group_records(
                label,
                group,
            )
        )

    # ========================================================
    # MARKA GENEL
    # ========================================================

    for (
        brand,
        group,
    ) in brand_groups.items():

        if len(
            group
        ) < 3:

            continue

        label = (
            f"{brand} ürünü"
        )

        dataset.extend(
            generate_value_records(
                label,
                group,
            )
        )

        dataset.extend(
            generate_rating_records(
                label,
                group,
            )
        )

        dataset.extend(
            generate_cheapest_records(
                label,
                group,
            )
        )

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
        "\nRecommendation V2 örnekleri oluşturuluyor..."
    )

    recommendations = (
        generate_recommendations(
            products
        )
    )

    print(
        "Duplicate öncesi recommendation:",
        len(
            recommendations
        ),
    )

    recommendations = (
        remove_duplicates(
            recommendations
        )
    )

    print(
        "Duplicate sonrası recommendation:",
        len(
            recommendations
        ),
    )

    # ========================================================
    # HEDEF SAYIYA GÖRE SINIRLA
    # ========================================================

    random.shuffle(
        recommendations
    )

    if (
        len(
            recommendations
        )
        > TARGET_RECOMMENDATION_COUNT
    ):

        recommendations = (
            recommendations[
                :TARGET_RECOMMENDATION_COUNT
            ]
        )

    print(
        "Final recommendation kayıt sayısı:",
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
        + "=" * 75
    )

    print(
        "RECOMMENDATION CHAT DATASET V2 HAZIR"
    )

    print(
        "=" * 75
    )

    print(
        "Comparison kayıtları:",
        len(
            comparison_dataset
        ),
    )

    print(
        "Recommendation V2 kayıtları:",
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
                recommendations[
                    0
                ],
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()