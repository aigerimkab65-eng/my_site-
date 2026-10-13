"""Amount in words for invoice totals (KZT)."""

from __future__ import annotations

import math
from typing import Optional

_ONES_M = {
    0: "",
    1: "один",
    2: "два",
    3: "три",
    4: "четыре",
    5: "пять",
    6: "шесть",
    7: "семь",
    8: "восемь",
    9: "девять",
}
_ONES_F = {
    0: "",
    1: "одна",
    2: "две",
    3: "три",
    4: "четыре",
    5: "пять",
    6: "шесть",
    7: "семь",
    8: "восемь",
    9: "девять",
}
_TEENS = {
    10: "десять",
    11: "одиннадцать",
    12: "двенадцать",
    13: "тринадцать",
    14: "четырнадцать",
    15: "пятнадцать",
    16: "шестнадцать",
    17: "семнадцать",
    18: "восемнадцать",
    19: "девятнадцать",
}
_TENS = {
    2: "двадцать",
    3: "тридцать",
    4: "сорок",
    5: "пятьдесят",
    6: "шестьдесят",
    7: "семьдесят",
    8: "восемьдесят",
    9: "девяносто",
}
_HUNDREDS = {
    1: "сто",
    2: "двести",
    3: "триста",
    4: "четыреста",
    5: "пятьсот",
    6: "шестьсот",
    7: "семьсот",
    8: "восемьсот",
    9: "девятьсот",
}

# Kazakh (simplified, sufficient for homework invoices)
_KZ_ONES = {
    0: "",
    1: "бір",
    2: "екі",
    3: "үш",
    4: "төрт",
    5: "бес",
    6: "алты",
    7: "жеті",
    8: "сегіз",
    9: "тоғыз",
}
_KZ_TEENS = {
    10: "он",
    11: "он бір",
    12: "он екі",
    13: "он үш",
    14: "он төрт",
    15: "он бес",
    16: "он алты",
    17: "он жеті",
    18: "он сегіз",
    19: "он тоғыз",
}
_KZ_TENS = {
    2: "жиырма",
    3: "отыз",
    4: "қырық",
    5: "елу",
    6: "алпыс",
    7: "жетпіс",
    8: "сексен",
    9: "тоқсан",
}
_KZ_HUNDREDS = {
    1: "жүз",
    2: "екі жүз",
    3: "үш жүз",
    4: "төрт жүз",
    5: "бес жүз",
    6: "алты жүз",
    7: "жеті жүз",
    8: "сегіз жүз",
    9: "тоғыз жүз",
}

_EN_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


def _triad_ru(n: int, feminine: bool = False) -> str:
    ones = _ONES_F if feminine else _ONES_M
    parts = []
    h = n // 100
    rem = n % 100
    if h:
        parts.append(_HUNDREDS[h])
    if rem >= 10 and rem <= 19:
        parts.append(_TEENS[rem])
    else:
        t = rem // 10
        o = rem % 10
        if t:
            parts.append(_TENS[t])
        if o:
            parts.append(ones[o])
    return " ".join(parts)


def _plural_ru(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def _split_amount(amount):
    """Whole units and a 0–99 minor part. Rejects NaN, infinity, negatives, and ≥ 1 trillion."""
    number = float(amount)
    if not math.isfinite(number) or number < 0 or number >= 1_000_000_000_000:
        raise ValueError("bad amount")
    whole = int(math.floor(number + 1e-9))
    minor = int(round((number - whole) * 100))
    if minor == 100:
        whole += 1
        minor = 0
    if whole >= 1_000_000_000_000:
        raise ValueError("bad amount")
    return whole, minor


def _currency_code(currency: str) -> str:
    code = (currency or "kzt").strip().lower()
    return code if code in {"kzt", "usd", "rub"} else "kzt"


def _groups(whole: int):
    billions = whole // 1_000_000_000
    millions = (whole % 1_000_000_000) // 1_000_000
    thousands = (whole % 1_000_000) // 1000
    rest = whole % 1000
    return billions, millions, thousands, rest


def amount_words_ru(amount, currency: str = "kzt") -> str:
    """e.g. 25000 → 'Двадцать пять тысяч тенге 00 тиын'."""
    whole, minor = _split_amount(amount)
    code = _currency_code(currency)
    majors = {
        "kzt": ("тенге", "тенге", "тенге"),
        "usd": ("доллар", "доллара", "долларов"),
        "rub": ("рубль", "рубля", "рублей"),
    }[code]
    minors = {
        "kzt": ("тиын", "тиын", "тиын"),
        "usd": ("цент", "цента", "центов"),
        "rub": ("копейка", "копейки", "копеек"),
    }[code]

    if whole == 0:
        words = "ноль"
    else:
        billions, millions, thousands, rest = _groups(whole)
        chunks = []
        if billions:
            chunks.append(_triad_ru(billions, feminine=False))
            chunks.append(_plural_ru(billions, "миллиард", "миллиарда", "миллиардов"))
        if millions:
            chunks.append(_triad_ru(millions, feminine=False))
            chunks.append(_plural_ru(millions, "миллион", "миллиона", "миллионов"))
        if thousands:
            chunks.append(_triad_ru(thousands, feminine=True))
            chunks.append(_plural_ru(thousands, "тысяча", "тысячи", "тысяч"))
        if rest or not chunks:
            chunks.append(_triad_ru(rest, feminine=False))
        words = " ".join(p for p in chunks if p).strip()

    words = words[:1].upper() + words[1:] if words else "Ноль"
    major = _plural_ru(whole, *majors)
    minor_name = _plural_ru(minor, *minors)
    return f"{words} {major} {minor:02d} {minor_name}"


def _triad_kz(n: int) -> str:
    parts = []
    h = n // 100
    rem = n % 100
    if h:
        parts.append(_KZ_HUNDREDS[h])
    if rem >= 10 and rem <= 19:
        parts.append(_KZ_TEENS[rem])
    else:
        t = rem // 10
        o = rem % 10
        if t:
            parts.append(_KZ_TENS[t])
        if o:
            parts.append(_KZ_ONES[o])
    return " ".join(parts)


def amount_words_kz(amount, currency: str = "kzt") -> str:
    whole, minor = _split_amount(amount)
    code = _currency_code(currency)
    major = {"kzt": "теңге", "usd": "АҚШ доллары", "rub": "рубль"}[code]
    minor_name = {"kzt": "тиын", "usd": "цент", "rub": "копейка"}[code]
    if whole == 0:
        words = "нөл"
    else:
        billions, millions, thousands, rest = _groups(whole)
        chunks = []
        if billions:
            chunks.append(_triad_kz(billions))
            chunks.append("миллиард")
        if millions:
            chunks.append(_triad_kz(millions))
            chunks.append("миллион")
        if thousands:
            chunks.append(_triad_kz(thousands))
            chunks.append("мың")
        if rest or not chunks:
            chunks.append(_triad_kz(rest))
        words = " ".join(p for p in chunks if p).strip()
    words = words[:1].upper() + words[1:] if words else "Нөл"
    return f"{words} {major} {minor:02d} {minor_name}"


def _en_under_1000(n: int) -> str:
    if n < 20:
        return _EN_ONES[n]
    if n < 100:
        t, o = divmod(n, 10)
        return _EN_TENS[t] + (f"-{_EN_ONES[o]}" if o else "")
    h, rem = divmod(n, 100)
    return _EN_ONES[h] + " hundred" + (f" {_en_under_1000(rem)}" if rem else "")


def amount_words_en(amount, currency: str = "kzt") -> str:
    whole, minor = _split_amount(amount)
    code = _currency_code(currency)
    major_one, major_many = {
        "kzt": ("tenge", "tenge"),
        "usd": ("dollar", "dollars"),
        "rub": ("ruble", "rubles"),
    }[code]
    minor_one, minor_many = {
        "kzt": ("tiyin", "tiyin"),
        "usd": ("cent", "cents"),
        "rub": ("kopeck", "kopecks"),
    }[code]
    if whole == 0:
        words = "zero"
    else:
        billions, millions, thousands, rest = _groups(whole)
        parts = []
        if billions:
            parts.append(_en_under_1000(billions) + " billion")
        if millions:
            parts.append(_en_under_1000(millions) + " million")
        if thousands:
            parts.append(_en_under_1000(thousands) + " thousand")
        if rest or not parts:
            parts.append(_en_under_1000(rest))
        words = " ".join(parts)
    words = words[:1].upper() + words[1:]
    major = major_one if whole == 1 else major_many
    minor_name = minor_one if minor == 1 else minor_many
    return f"{words} {major} {minor:02d} {minor_name}"


def amount_in_words(amount, lang: str = "ru", currency: str = "kzt") -> str:
    if lang == "kz":
        return amount_words_kz(amount, currency)
    if lang == "en":
        return amount_words_en(amount, currency)
    return amount_words_ru(amount, currency)


def split_vat_from_gross(gross, vat_rate: float) -> tuple:
    """
    Extract VAT from a gross price.
    vat = gross * rate / (100 + rate); net = gross - vat.
    Rounded to 2 decimal places.
    """
    if gross is None or gross == "":
        return None, None, None
    gross_f = float(gross)
    rate = float(vat_rate or 0)
    if rate <= 0:
        return round(gross_f, 2), 0.0, round(gross_f, 2)
    vat = round(gross_f * rate / (100.0 + rate), 2)
    net = round(gross_f - vat, 2)
    return net, vat, round(gross_f, 2)
