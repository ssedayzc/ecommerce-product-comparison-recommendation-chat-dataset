import json
import random
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit, parse_qs


# ============================================================
# AYARLAR
# ============================================================

INPUT_FILE = "scraping/trendyol_electronics_products.jsonl"

OUTPUT_FILE = "comparison_chat_dataset.json"


RANDOM_SEED = 42

# Her ürün için aynı kategoriden en fazla kaç ürünle
# karşılaştırma yapılacak?
MAX_COMPARISONS_PER_PRODUCT = 3

# Genel karşılaştırma çiftlerinin maksimum sayısı
MAX_PRODUCT_PAIRS = 1500

# Kullanıcı yorumlarından cevapta kaç örnek kullanılacak?
MAX_REVIEW_EXAMPLES = 3

# Teknik karşılaştırmada en fazla kaç ortak özellik kullanılacak?
MAX_COMMON_ATTRIBUTES = 8


random.seed(RANDOM_SEED)


# ============================================================
# GENEL YARDIMCI FONKSİYONLAR
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
    """
    Bir alan gerçekten kullanılabilir veri içeriyor mu?
    """

    if value in MISSING_VALUES:
        return False

    if isinstance(value, str):
        return bool(value.strip())

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
    """
    Örnekleri parse eder:

    13673.38 TRY
    24.597 TL
    47.799,00 TL
    """

    if not is_valid(price):
        return None

    text = str(price).upper()

    text = (
        text
        .replace("TRY", "")
        .replace("TL", "")
        .replace("₺", "")
        .strip()
    )

    # 47.799,00 -> 47799.00
    if "." in text and "," in text:

        text = (
            text
            .replace(".", "")
            .replace(",", ".")
        )

    # 24.597 gibi değer
    elif text.count(".") == 1:

        left, right = text.split(".")

        # Sağ taraf 3 haneliyse binlik ayracı olabilir
        if len(right) == 3:

            text = left + right

    elif "," in text:

        text = text.replace(
            ",",
            ".",
        )

    text = re.sub(
        r"[^\d.]",
        "",
        text,
    )

    try:
        return Decimal(text)

    except (
        InvalidOperation,
        ValueError,
    ):
        return None


def format_price(price):
    """
    Decimal fiyatı Türkçe gösterime çevirir.
    """

    if price is None:
        return None

    value = float(price)

    return (
        f"{value:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
        + " TL"
    )


# ============================================================
# URL'DEN PRODUCT / MERCHANT ID
# ============================================================

def extract_product_id(url):

    if not url:
        return None

    match = re.search(
        r"-p-(\d+)",
        url,
    )

    if match:
        return match.group(1)

    return None


def extract_merchant_id(url):

    if not url:
        return None

    query = parse_qs(
        urlsplit(url).query
    )

    return (
        query
        .get(
            "merchantId",
            [None],
        )[0]
    )


# ============================================================
# KATEGORİ BELİRLEME
# ============================================================

def get_comparison_category(product):
    """
    En anlamlı karşılaştırma kategorisini belirler.

    Örnek:

    Trendyol
    Elektronik
    Bilgisayar&Tablet
    Bilgisayar
    Laptop
    LENOVO Laptop

    -> Laptop
    """

    categories = product.get(
        "categories",
        [],
    )

    if not categories:
        return "Bilinmeyen"

    categories = [
        clean_text(category)
        for category in categories
        if clean_text(category)
    ]

    ignored = {
        "Trendyol",
        "Elektronik",
    }

    categories = [
        category
        for category in categories
        if category not in ignored
    ]

    if not categories:
        return "Bilinmeyen"

    brand = (
        product.get(
            "brand",
            ""
        )
        or ""
    ).lower()

    # Son kategori marka + kategori ise
    # bir önceki kategoriyi kullan.
    if (
        len(categories) >= 2
        and brand
        and brand
        in categories[-1].lower()
    ):
        return categories[-2]

    return categories[-1]


# ============================================================
# ÜRÜNLERİ YÜKLE
# ============================================================

def load_products():

    products = []

    with open(
        INPUT_FILE,
        "r",
        encoding="utf-8",
    ) as file:

        for line in file:

            line = line.strip()

            if not line:
                continue

            try:
                product = json.loads(
                    line
                )

            except json.JSONDecodeError:
                continue

            name = product.get(
                "product_name"
            )

            if not is_valid(name):
                continue

            # Yardımcı alanlar
            product["_price"] = (
                parse_price(
                    product.get(
                        "price"
                    )
                )
            )

            product["_category"] = (
                get_comparison_category(
                    product
                )
            )

            product["_product_id"] = (
                extract_product_id(
                    product.get(
                        "source_url"
                    )
                )
            )

            product["_merchant_id"] = (
                extract_merchant_id(
                    product.get(
                        "source_url"
                    )
                )
            )

            products.append(
                product
            )

    return products


# ============================================================
# TEKNİK BENZERLİK
# ============================================================

def attribute_similarity(
    product_a,
    product_b,
):
    """
    Ortak teknik özellik anahtarlarına göre
    basit Jaccard benzerliği hesaplar.
    """

    attributes_a = product_a.get(
        "attributes",
        {},
    )

    attributes_b = product_b.get(
        "attributes",
        {},
    )

    if not attributes_a or not attributes_b:
        return 0

    keys_a = set(
        attributes_a.keys()
    )

    keys_b = set(
        attributes_b.keys()
    )

    union = (
        keys_a
        | keys_b
    )

    if not union:
        return 0

    intersection = (
        keys_a
        & keys_b
    )

    return (
        len(intersection)
        / len(union)
    )


# ============================================================
# ÜRÜN ÇİFTLERİ
# ============================================================

def create_product_pairs(
    products,
):
    """
    Aynı kategorideki ürünleri teknik özellik
    benzerliğine göre eşleştirir.
    """

    category_groups = defaultdict(
        list
    )

    for product in products:

        category_groups[
            product["_category"]
        ].append(
            product
        )

    pairs = []

    seen_pairs = set()

    for category, group in (
        category_groups.items()
    ):

        if len(group) < 2:
            continue

        for product_a in group:

            candidates = []

            for product_b in group:

                if product_a is product_b:
                    continue

                # Tam olarak aynı product_id +
                # merchant ise tekrar karşılaştırma yapma
                if (
                    product_a["_product_id"]
                    == product_b["_product_id"]
                    and
                    product_a["_merchant_id"]
                    == product_b["_merchant_id"]
                ):
                    continue

                similarity = (
                    attribute_similarity(
                        product_a,
                        product_b,
                    )
                )

                candidates.append(
                    (
                        similarity,
                        product_b,
                    )
                )

            candidates.sort(
                key=lambda item:
                item[0],
                reverse=True,
            )

            for (
                similarity,
                product_b,
            ) in candidates[
                :MAX_COMPARISONS_PER_PRODUCT
            ]:

                name_a = product_a[
                    "product_name"
                ]

                name_b = product_b[
                    "product_name"
                ]

                pair_key = tuple(
                    sorted(
                        [
                            product_a.get(
                                "source_url",
                                name_a,
                            ),
                            product_b.get(
                                "source_url",
                                name_b,
                            ),
                        ]
                    )
                )

                if pair_key in seen_pairs:
                    continue

                seen_pairs.add(
                    pair_key
                )

                pairs.append(
                    (
                        product_a,
                        product_b,
                        similarity,
                    )
                )

    random.shuffle(
        pairs
    )

    return pairs[
        :MAX_PRODUCT_PAIRS
    ]


# ============================================================
# AYNI ÜRÜN / FARKLI SATICI ÇİFTLERİ
# ============================================================

def create_same_product_seller_pairs(
    products,
):
    """
    Aynı product_id fakat farklı merchantId olan
    kayıtları eşleştirir.
    """

    groups = defaultdict(
        list
    )

    for product in products:

        product_id = product.get(
            "_product_id"
        )

        merchant_id = product.get(
            "_merchant_id"
        )

        if (
            not product_id
            or not merchant_id
        ):
            continue

        groups[
            product_id
        ].append(
            product
        )

    pairs = []

    seen = set()

    for product_id, group in (
        groups.items()
    ):

        if len(group) < 2:
            continue

        for i in range(
            len(group)
        ):

            for j in range(
                i + 1,
                len(group),
            ):

                product_a = group[i]
                product_b = group[j]

                merchant_a = (
                    product_a[
                        "_merchant_id"
                    ]
                )

                merchant_b = (
                    product_b[
                        "_merchant_id"
                    ]
                )

                if merchant_a == merchant_b:
                    continue

                key = (
                    product_id,
                    *sorted(
                        [
                            merchant_a,
                            merchant_b,
                        ]
                    ),
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                pairs.append(
                    (
                        product_a,
                        product_b,
                    )
                )

    return pairs


# ============================================================
# ORTAK TEKNİK ÖZELLİKLER
# ============================================================

def get_common_attributes(
    product_a,
    product_b,
):

    attrs_a = product_a.get(
        "attributes",
        {},
    )

    attrs_b = product_b.get(
        "attributes",
        {},
    )

    common_keys = [
        key
        for key in attrs_a
        if (
            key in attrs_b
            and is_valid(
                attrs_a[key]
            )
            and is_valid(
                attrs_b[key]
            )
        )
    ]

    # Değerleri farklı olan özellikleri önce göster
    common_keys.sort(
        key=lambda key:
        attrs_a[key]
        == attrs_b[key]
    )

    return common_keys[
        :MAX_COMMON_ATTRIBUTES
    ]


# ============================================================
# YORUM ÖRNEKLERİ
# ============================================================

def get_review_examples(
    product,
    limit=MAX_REVIEW_EXAMPLES,
):
    """
    Yorumların tamamını modele vermek yerine
    birkaç gerçek kullanıcı yorumu seçer.

    Cümlelere bölmez.
    Her yorum bütün olarak kalır.
    """

    reviews = product.get(
        "reviews",
        [],
    )

    valid_reviews = []

    for review in reviews:

        review = clean_text(
            review
        )

        if not review:
            continue

        if len(review) < 15:
            continue

        # Çok uzun yorumları sınırla
        if len(review) > 500:

            review = (
                review[:497]
                + "..."
            )

        valid_reviews.append(
            review
        )

    if not valid_reviews:
        return []

    # İlk yorumları sürekli seçmemek için
    # deterministik rastgele örnek
    sample_size = min(
        limit,
        len(valid_reviews),
    )

    return random.sample(
        valid_reviews,
        sample_size,
    )


# ============================================================
# CHAT KAYDI
# ============================================================

def create_chat_record(
    question,
    answer,
):
    """
    NULL YOK.

    Sadece role ve content.
    """

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
# GENEL KARŞILAŞTIRMA
# ============================================================

def generate_general_comparison(
    product_a,
    product_b,
):

    name_a = product_a[
        "product_name"
    ]

    name_b = product_b[
        "product_name"
    ]

    question = (
        f"{name_a} ile {name_b} ürünlerini "
        "fiyat, kullanıcı puanı ve teknik özellikleri "
        "açısından karşılaştırır mısın?"
    )

    sections = []

    # --------------------------------------------------------
    # Fiyat
    # --------------------------------------------------------

    price_a = product_a[
        "_price"
    ]

    price_b = product_b[
        "_price"
    ]

    if (
        price_a is not None
        and price_b is not None
    ):

        if price_a < price_b:

            price_text = (
                f"{name_a}, "
                f"{format_price(price_a)} fiyatıyla "
                f"{format_price(price_b)} fiyatındaki "
                f"{name_b} ürününden daha uygun fiyatlıdır."
            )

        elif price_b < price_a:

            price_text = (
                f"{name_b}, "
                f"{format_price(price_b)} fiyatıyla "
                f"{format_price(price_a)} fiyatındaki "
                f"{name_a} ürününden daha uygun fiyatlıdır."
            )

        else:

            price_text = (
                "İki ürünün fiyatı aynıdır: "
                f"{format_price(price_a)}."
            )

        sections.append(
            price_text
        )

    # --------------------------------------------------------
    # Rating
    # --------------------------------------------------------

    rating_a = product_a.get(
        "rating"
    )

    rating_b = product_b.get(
        "rating"
    )

    if (
        is_valid(rating_a)
        and is_valid(rating_b)
    ):

        sections.append(
            f"Kullanıcı puanları açısından "
            f"{name_a} {rating_a}, "
            f"{name_b} ise {rating_b} puana sahiptir."
        )

    # --------------------------------------------------------
    # Teknik özellikler
    # --------------------------------------------------------

    common_keys = (
        get_common_attributes(
            product_a,
            product_b,
        )
    )

    if common_keys:

        comparisons = []

        for key in common_keys[:5]:

            value_a = (
                product_a[
                    "attributes"
                ][key]
            )

            value_b = (
                product_b[
                    "attributes"
                ][key]
            )

            comparisons.append(
                f"{key}: "
                f"{name_a} = {value_a}; "
                f"{name_b} = {value_b}"
            )

        sections.append(
            "Ortak teknik özelliklerden bazıları şöyledir: "
            + " | ".join(
                comparisons
            )
            + "."
        )

    sections.append(
        "Tercih yaparken fiyat ile ihtiyaç duyduğunuz "
        "teknik özellikleri birlikte değerlendirmeniz daha uygundur."
    )

    answer = " ".join(
        sections
    )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# FİYAT KARŞILAŞTIRMASI
# ============================================================

def generate_price_comparison(
    product_a,
    product_b,
):

    price_a = product_a[
        "_price"
    ]

    price_b = product_b[
        "_price"
    ]

    if (
        price_a is None
        or price_b is None
    ):
        return None

    name_a = product_a[
        "product_name"
    ]

    name_b = product_b[
        "product_name"
    ]

    question = (
        f"{name_a} ile {name_b} arasında "
        "hangisi daha uygun fiyatlı?"
    )

    if price_a < price_b:

        difference = (
            price_b
            - price_a
        )

        answer = (
            f"{name_a} {format_price(price_a)}, "
            f"{name_b} ise {format_price(price_b)} fiyatla listelenmiştir. "
            f"Bu verilere göre {name_a}, "
            f"{format_price(difference)} daha uygun fiyatlıdır."
        )

    elif price_b < price_a:

        difference = (
            price_a
            - price_b
        )

        answer = (
            f"{name_a} {format_price(price_a)}, "
            f"{name_b} ise {format_price(price_b)} fiyatla listelenmiştir. "
            f"Bu verilere göre {name_b}, "
            f"{format_price(difference)} daha uygun fiyatlıdır."
        )

    else:

        answer = (
            f"Her iki ürün de "
            f"{format_price(price_a)} fiyatla listelenmiştir."
        )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# TEKNİK ÖZELLİK KARŞILAŞTIRMASI
# ============================================================

def generate_technical_comparison(
    product_a,
    product_b,
):

    common_keys = (
        get_common_attributes(
            product_a,
            product_b,
        )
    )

    if len(common_keys) < 2:
        return None

    name_a = product_a[
        "product_name"
    ]

    name_b = product_b[
        "product_name"
    ]

    question = (
        f"{name_a} ve {name_b} arasındaki "
        "teknik özellik farkları nelerdir?"
    )

    differences = []

    similarities = []

    for key in common_keys:

        value_a = (
            product_a[
                "attributes"
            ][key]
        )

        value_b = (
            product_b[
                "attributes"
            ][key]
        )

        if value_a == value_b:

            similarities.append(
                f"{key} açısından iki ürün de {value_a}"
            )

        else:

            differences.append(
                f"{key} bakımından "
                f"{name_a} {value_a}, "
                f"{name_b} ise {value_b}"
            )

    sections = []

    if differences:

        sections.append(
            "Farklılıklar: "
            + "; ".join(
                differences[:6]
            )
            + "."
        )

    if similarities:

        sections.append(
            "Benzerlikler: "
            + "; ".join(
                similarities[:3]
            )
            + "."
        )

    if not sections:
        return None

    answer = " ".join(
        sections
    )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# PUAN / DEĞERLENDİRME KARŞILAŞTIRMASI
# ============================================================

def generate_rating_comparison(
    product_a,
    product_b,
):

    rating_a = product_a.get(
        "rating"
    )

    rating_b = product_b.get(
        "rating"
    )

    if (
        not is_valid(rating_a)
        or not is_valid(rating_b)
    ):
        return None

    name_a = product_a[
        "product_name"
    ]

    name_b = product_b[
        "product_name"
    ]

    question = (
        f"Kullanıcı değerlendirmelerine göre "
        f"{name_a} mı yoksa {name_b} mı daha yüksek puana sahip?"
    )

    review_count_a = product_a.get(
        "review_count"
    )

    review_count_b = product_b.get(
        "review_count"
    )

    answer = (
        f"{name_a} ürününün puanı {rating_a}"
    )

    if is_valid(
        review_count_a
    ):

        answer += (
            f" ve {review_count_a} değerlendirmesi bulunmaktadır"
        )

    answer += (
        f". {name_b} ürününün puanı {rating_b}"
    )

    if is_valid(
        review_count_b
    ):

        answer += (
            f" ve {review_count_b} değerlendirmesi bulunmaktadır"
        )

    answer += "."

    try:

        number_a = float(
            str(rating_a)
            .replace(",", ".")
        )

        number_b = float(
            str(rating_b)
            .replace(",", ".")
        )

        if number_a > number_b:

            answer += (
                f" Bu verilere göre {name_a} "
                "daha yüksek kullanıcı puanına sahiptir."
            )

        elif number_b > number_a:

            answer += (
                f" Bu verilere göre {name_b} "
                "daha yüksek kullanıcı puanına sahiptir."
            )

        else:

            answer += (
                " İki ürünün kullanıcı puanı aynıdır."
            )

    except ValueError:
        pass

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# YORUM TABANLI KARŞILAŞTIRMA
# ============================================================

def generate_review_comparison(
    product_a,
    product_b,
):

    reviews_a = (
        get_review_examples(
            product_a
        )
    )

    reviews_b = (
        get_review_examples(
            product_b
        )
    )

    if (
        not reviews_a
        or not reviews_b
    ):
        return None

    name_a = product_a[
        "product_name"
    ]

    name_b = product_b[
        "product_name"
    ]

    question = (
        f"{name_a} ve {name_b} hakkında "
        "kullanıcı yorumlarında neler söyleniyor?"
    )

    text_a = " | ".join(
        f"“{review}”"
        for review in reviews_a
    )

    text_b = " | ".join(
        f"“{review}”"
        for review in reviews_b
    )

    answer = (
        f"{name_a} için veri setindeki örnek kullanıcı yorumları: "
        f"{text_a}. "
        f"{name_b} için veri setindeki örnek kullanıcı yorumları: "
        f"{text_b}. "
        "Bu yorumlar kullanıcıların bireysel deneyimlerini yansıtır; "
        "ürün tercihi yapılırken teknik özellikler ve genel kullanıcı "
        "puanlarıyla birlikte değerlendirilmelidir."
    )

    return create_chat_record(
        question,
        answer,
    )


# ============================================================
# AYNI ÜRÜN / FARKLI SATICI KARŞILAŞTIRMASI
# ============================================================

def generate_seller_comparison(
    product_a,
    product_b,
):

    merchant_a = product_a.get(
        "_merchant_id"
    )

    merchant_b = product_b.get(
        "_merchant_id"
    )

    if (
        not merchant_a
        or not merchant_b
    ):
        return None

    name = product_a[
        "product_name"
    ]

    price_a = product_a[
        "_price"
    ]

    price_b = product_b[
        "_price"
    ]

    question = (
        f"{name} ürününün {merchant_a} ve {merchant_b} "
        "numaralı satıcı tekliflerini karşılaştırır mısın?"
    )

    sections = []

    if (
        price_a is not None
        and price_b is not None
    ):

        sections.append(
            f"{merchant_a} numaralı satıcıdaki fiyat "
            f"{format_price(price_a)}, "
            f"{merchant_b} numaralı satıcıdaki fiyat ise "
            f"{format_price(price_b)}."
        )

        if price_a < price_b:

            sections.append(
                f"Fiyat açısından {merchant_a} numaralı "
                "satıcının teklifi daha uygundur."
            )

        elif price_b < price_a:

            sections.append(
                f"Fiyat açısından {merchant_b} numaralı "
                "satıcının teklifi daha uygundur."
            )

        else:

            sections.append(
                "İki satıcıdaki fiyat aynıdır."
            )

    rating_a = product_a.get(
        "rating"
    )

    rating_b = product_b.get(
        "rating"
    )

    if (
        is_valid(rating_a)
        and is_valid(rating_b)
    ):

        sections.append(
            f"Ürün puanı kayıtlarında sırasıyla "
            f"{rating_a} ve {rating_b} değerleri bulunmaktadır."
        )

    sections.append(
        "Veri setinde satıcı adı veya satıcı hizmet puanı "
        "bulunmadığı için karşılaştırma yalnızca mevcut ürün "
        "ve teklif bilgilerine dayanmaktadır."
    )

    return create_chat_record(
        question,
        " ".join(
            sections
        ),
    )


# ============================================================
# DATASET OLUŞTUR
# ============================================================

def generate_dataset(
    products,
):

    dataset = []

    # ========================================================
    # NORMAL ÜRÜN KARŞILAŞTIRMALARI
    # ========================================================

    pairs = create_product_pairs(
        products
    )

    print(
        "Ürün karşılaştırma çifti:",
        len(pairs),
    )

    for (
        product_a,
        product_b,
        similarity,
    ) in pairs:

        generators = [
            generate_general_comparison,
            generate_price_comparison,
            generate_technical_comparison,
            generate_rating_comparison,
            generate_review_comparison,
        ]

        for generator in generators:

            record = generator(
                product_a,
                product_b,
            )

            if record:
                dataset.append(
                    record
                )

    # ========================================================
    # AYNI ÜRÜN FARKLI SATICI
    # ========================================================

    seller_pairs = (
        create_same_product_seller_pairs(
            products
        )
    )

    print(
        "Aynı ürün / farklı satıcı çifti:",
        len(
            seller_pairs
        ),
    )

    for (
        product_a,
        product_b,
    ) in seller_pairs:

        record = (
            generate_seller_comparison(
                product_a,
                product_b,
            )
        )

        if record:

            dataset.append(
                record
            )

    # ========================================================
    # DUPLICATE SORULARI KALDIR
    # ========================================================

    unique_dataset = []

    seen_questions = set()

    for record in dataset:

        question = (
            record[
                "messages"
            ][0][
                "content"
            ]
        )

        normalized = (
            question
            .lower()
            .strip()
        )

        if normalized in seen_questions:
            continue

        seen_questions.add(
            normalized
        )

        unique_dataset.append(
            record
        )

    random.shuffle(
        unique_dataset
    )

    return unique_dataset


# ============================================================
# JSON KAYDET
# ============================================================

def save_json(records, filename):
    """
    Dataset'i gerçek JSON array formatında kaydeder.

    Çıktı:

    [
      {
        "messages": [
          {
            "role": "user",
            "content": "..."
          },
          {
            "role": "assistant",
            "content": "..."
          }
        ]
      }
    ]
    """

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
        "Ürünler yükleniyor..."
    )

    products = (
        load_products()
    )

    print(
        "Toplam geçerli ürün:",
        len(products),
    )

    print(
        "\nComparison chat dataset oluşturuluyor..."
    )

    dataset = (
        generate_dataset(
            products
        )
    )

    print(
        "Toplam comparison chat örneği:",
        len(dataset),
    )

    # ========================================================
    # JSON KAYDET
    # ========================================================

    save_json(
        dataset,
        OUTPUT_FILE,
    )

    print(
        "\n"
        + "=" * 70
    )

    print(
        "COMPARISON CHAT DATASET HAZIR"
    )

    print(
        "=" * 70
    )

    print(
        "Toplam kayıt:",
        len(dataset),
    )

    print(
        "\nDosya:"
    )

    print(
        Path(
            OUTPUT_FILE
        ).resolve()
    )

    # ========================================================
    # ÖRNEK
    # ========================================================

    if dataset:

        print(
            "\nÖrnek kayıt:"
        )

        print(
            json.dumps(
                dataset[0],
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()