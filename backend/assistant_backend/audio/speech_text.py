import re


ONES = {
    0: "ноль",
    1: "один",
    2: "два",
    3: "три",
    4: "четыре",
    5: "пять",
    6: "шесть",
    7: "семь",
    8: "восемь",
    9: "девять",
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
TENS = {
    20: "двадцать",
    30: "тридцать",
    40: "сорок",
    50: "пятьдесят",
    60: "шестьдесят",
    70: "семьдесят",
    80: "восемьдесят",
    90: "девяносто",
}
HUNDREDS = {
    100: "сто",
    200: "двести",
    300: "триста",
    400: "четыреста",
    500: "пятьсот",
    600: "шестьсот",
    700: "семьсот",
    800: "восемьсот",
    900: "девятьсот",
}
GENITIVE_ONES = {
    0: "нуля",
    1: "одного",
    2: "двух",
    3: "трёх",
    4: "четырёх",
    5: "пяти",
    6: "шести",
    7: "семи",
    8: "восьми",
    9: "девяти",
    10: "десяти",
    11: "одиннадцати",
    12: "двенадцати",
    13: "тринадцати",
    14: "четырнадцати",
    15: "пятнадцати",
    16: "шестнадцати",
    17: "семнадцати",
    18: "восемнадцати",
    19: "девятнадцати",
}
GENITIVE_TENS = {
    20: "двадцати",
    30: "тридцати",
    40: "сорока",
    50: "пятидесяти",
    60: "шестидесяти",
    70: "семидесяти",
    80: "восьмидесяти",
    90: "девяноста",
}
GENITIVE_HUNDREDS = {
    100: "ста",
    200: "двухсот",
    300: "трёхсот",
    400: "четырёхсот",
    500: "пятисот",
    600: "шестисот",
    700: "семисот",
    800: "восьмисот",
    900: "девятисот",
}
GROUPS = [
    (1_000_000_000, ("миллиард", "миллиарда", "миллиардов")),
    (1_000_000, ("миллион", "миллиона", "миллионов")),
    (1_000, ("тысяча", "тысячи", "тысяч")),
]
UNITS = {
    "гб": "гигабайт",
    "gb": "гигабайт",
    "мб": "мегабайт",
    "mb": "мегабайт",
    "кб": "килобайт",
    "kb": "килобайт",
    "тб": "терабайт",
    "tb": "терабайт",
    "мс": "миллисекунд",
    "ms": "миллисекунд",
    "сек": "секунд",
    "с": "секунд",
    "мин": "минут",
    "ч": "часов",
    "гц": "герц",
    "hz": "герц",
    "кг": "килограмм",
    "км": "километров",
    "м": "метров",
    "%": "процентов",
}
EMOJI = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0000FE0F"
    "\U0000200D"
    "]+"
)


def _plural(value: int, forms: tuple[str, str, str]) -> str:
    value = abs(value) % 100
    if 11 <= value <= 19:
        return forms[2]
    tail = value % 10
    if tail == 1:
        return forms[0]
    if 2 <= tail <= 4:
        return forms[1]
    return forms[2]


def _small(value: int, genitive: bool = False) -> str:
    if value == 0:
        return ""
    hundreds = GENITIVE_HUNDREDS if genitive else HUNDREDS
    tens = GENITIVE_TENS if genitive else TENS
    ones = GENITIVE_ONES if genitive else ONES
    parts: list[str] = []
    hundred = value // 100 * 100
    if hundred:
        parts.append(hundreds[hundred])
    remainder = value % 100
    if remainder < 20:
        if remainder:
            parts.append(ones[remainder])
    else:
        ten = remainder // 10 * 10
        parts.append(tens[ten])
        one = remainder % 10
        if one:
            parts.append(ones[one])
    return " ".join(parts)


def number_words(value: int, genitive: bool = False) -> str:
    if value == 0:
        return GENITIVE_ONES[0] if genitive else ONES[0]
    if value < 0:
        return f"минус {number_words(abs(value), genitive)}"
    if value >= 1_000_000_000_000:
        return str(value)
    parts: list[str] = []
    rest = value
    for multiplier, forms in GROUPS:
        amount = rest // multiplier
        if amount:
            parts.append(_small(amount, genitive))
            parts.append(_plural(amount, forms))
            rest %= multiplier
    if rest:
        parts.append(_small(rest, genitive))
    return " ".join(part for part in parts if part)


def _range(match: re.Match[str]) -> str:
    prefix = "примерно " if match.group(1) else ""
    left = number_words(int(match.group(2)), True)
    right = number_words(int(match.group(3)), True)
    unit = UNITS.get((match.group(4) or "").lower(), (match.group(4) or "").lower())
    return f"{prefix}от {left} до {right} {unit}".strip()


def _number(match: re.Match[str]) -> str:
    value = match.group(0)
    if len(value) > 11:
        return value
    return number_words(int(value))


def normalize_for_speech(text: str) -> str:
    value = text or ""
    value = re.sub(r"```.*?```", " Код показан на экране. ", value, flags=re.S)
    value = re.sub(r"`([^`]*)`", r"\1", value)
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ссылка ", value)
    value = EMOJI.sub(" ", value)
    units = "|".join(sorted((re.escape(item) for item in UNITS), key=len, reverse=True))
    value = re.sub(rf"\b(около|примерно)?\s*(\d+)\s*[-–—]\s*(\d+)\s*({units})?\b", _range, value, flags=re.I)
    value = re.sub(rf"\b(\d+)\s*({units})\b", lambda m: f"{number_words(int(m.group(1)))} {UNITS[m.group(2).lower()]}", value, flags=re.I)
    value = re.sub(r"\b\d+\b", _number, value)
    value = value.replace("&", " и ").replace("+", " плюс ").replace("=", " равно ")
    value = value.replace("@", " собака ")
    value = re.sub(r"[*_#~|<>[\]{}^$\\]+", " ", value)
    value = re.sub(r"[«»\"“”]", "", value)
    value = re.sub(r"\s*[-–—]\s*", ", ", value)
    value = re.sub(r"\s+([,.!?;:])", r"\1", value)
    value = re.sub(r"([,.!?;:]){2,}", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()
