import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

EUR_TO_USD = Decimal('1.2')

CURRENCY_SYMBOLS = '$€¢'
SYMBOL_USED_AS_DECIMAL_POINT = re.compile(r'(?<=\d)[' + CURRENCY_SYMBOLS + r'](?=\d)')
NOT_PART_OF_NUMBER = re.compile(r'[^\d.]')


def parse_price(raw):
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None

    currency = 'EUR' if ('EUR' in text.upper() or '€' in text) else 'USD'

    normalised = SYMBOL_USED_AS_DECIMAL_POINT.sub('.', text)
    number = NOT_PART_OF_NUMBER.sub('', normalised).rstrip('.')
    if not number or number.count('.') > 1:
        return None, currency

    amount = Decimal(number)
    if currency == 'EUR':
        amount *= EUR_TO_USD
    return amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), currency


MONTH_NUMBERS = {}
for index, month in enumerate(
        ['january', 'february', 'march', 'april', 'may', 'june', 'july',
         'august', 'september', 'october', 'november', 'december'], start=1):
    MONTH_NUMBERS[month] = index
    MONTH_NUMBERS[month[:3]] = index

ASCTIME = re.compile(
    r'^[A-Za-z]{3}\s+([A-Za-z]{3})\s+(\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})\s+(\d{4})$')

ISO_DATE = re.compile(r'(\d{4})-(\d{1,2})-(\d{1,2})')
DAY_MONTHNAME_YEAR = re.compile(r'(\d{1,2})-([A-Za-z]+)-(\d{4})')
MONTH_DAY_YEAR = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{2,4})')
DAY_MONTH_YEAR = re.compile(r'(\d{1,2})\.(\d{1,2})\.(\d{4})')

CLOCK = re.compile(r'(\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?')
MERIDIEM = re.compile(r'\b([AaPp])\.?\s?[Mm]\.?')


def four_digit_year(value):
    year = int(value)
    return year + 2000 if year < 100 else year


def find_date(text):
    found = ISO_DATE.search(text)
    if found:
        year, month, day = found.groups()
        return int(year), int(month), int(day), found.span()

    found = DAY_MONTHNAME_YEAR.search(text)
    if found:
        day, month_name, year = found.groups()
        month = MONTH_NUMBERS.get(month_name.lower())
        if month:
            return int(year), month, int(day), found.span()

    found = MONTH_DAY_YEAR.search(text)
    if found:
        month, day, year = found.groups()
        return four_digit_year(year), int(month), int(day), found.span()

    found = DAY_MONTH_YEAR.search(text)
    if found:
        day, month, year = found.groups()
        return int(year), int(month), int(day), found.span()

    return None


def find_time(text):
    clock = CLOCK.search(text)
    if not clock:
        return 0, 0, 0, 0

    hour, minute = int(clock.group(1)), int(clock.group(2))
    second = int(clock.group(3) or 0)
    fraction = clock.group(4)
    microsecond = int(fraction.ljust(6, '0')[:6]) if fraction else 0

    meridiem = MERIDIEM.search(text)
    if meridiem:
        if meridiem.group(1).lower() == 'p' and hour != 12:
            hour += 12
        elif meridiem.group(1).lower() == 'a' and hour == 12:
            hour = 0

    return hour, minute, second, microsecond


def parse_timestamp(raw):
    if raw is None:
        return None
    text = ' '.join(str(raw).split())
    if not text or text.lower() in ('nan', 'nat', 'null', 'none'):
        return None

    asctime = ASCTIME.match(text)
    if asctime:
        month_name, day, hour, minute, second, year = asctime.groups()
        month = MONTH_NUMBERS.get(month_name.lower())
        if not month:
            return None
        return datetime(int(year), month, int(day), int(hour), int(minute), int(second))

    date = find_date(text)
    if not date:
        return None
    year, month, day, (start, end) = date

    hour, minute, second, microsecond = find_time(text[:start] + ' ' + text[end:])
    try:
        return datetime(year, month, day, hour, minute, second, microsecond)
    except ValueError:
        return None


HONORIFICS = {
    'mr', 'mrs', 'ms', 'miss', 'mx', 'dr', 'prof', 'professor', 'fr', 'father',
    'rev', 'reverend', 'msgr', 'monsignor', 'sr', 'sister', 'br', 'brother',
    'amb', 'ambassador', 'hon', 'honorable', 'sen', 'senator', 'rep', 'gov',
    'capt', 'captain', 'col', 'colonel', 'gen', 'general', 'lt', 'lieutenant',
    'maj', 'major', 'sgt', 'sergeant', 'adm', 'admiral', 'cmdr', 'ofc', 'det',
}

SUFFIXES = {
    'jr', 'sr', 'i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x',
    'phd', 'md', 'dds', 'dvm', 'esq', 'cpa', 'jd', 'mba', 'rn', 'do', 'edd',
    'psyd', 'ma', 'ms', 'msc', 'bsc', 'ba', 'bs', 'llm', 'llb', 'cfa', 'pe',
}

AUTHOR_SEPARATOR = re.compile(r'\s*(?:,|;|&|\band\b)\s*')


def normalise_person(name):
    if name is None:
        return ''
    words = [re.sub(r'[^A-Za-z]', '', word).lower() for word in str(name).split()]
    words = [word for word in words if word]

    while words and words[0] in HONORIFICS:
        words.pop(0)
    while words and words[-1] in SUFFIXES:
        words.pop()

    return ' '.join(words)


def split_authors(raw):
    if raw is None:
        return frozenset()
    names = {normalise_person(part) for part in AUTHOR_SEPARATOR.split(str(raw))}
    return frozenset(name for name in names if name)
