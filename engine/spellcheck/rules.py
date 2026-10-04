"""Rule checks for the error kinds the neural tagger does not handle: spelling, joined/hyphenated
writing and capitalisation.

check(text, lexicon, ctx) returns findings {"start", "end", "level", "rule", "fix", "message"}:
  level "error" — a sure error with a fix; "check" — a place the reader should look at
  ("fix" may be None). Char offsets are into text.
lexicon: Lexicon (pymorphy + hunspell + corpus frequency list); ctx: DocContext of the whole
document (recurring unknown words are its terms; lemmas it writes in lower case).
"""
import collections
import re

from .morph import morph
from .guards import BIBLIOGRAPHY


CYR_WORD = re.compile(r"[А-Яа-яЁё]+(?:-[А-Яа-яЁё]+)*")
TOKEN = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:[-‑][A-Za-zА-Яа-яЁё0-9]+)*")
QUOTED = re.compile(r"«[^»]*»|\"[^\"]*\"|“[^”]*”")

PRONOUN_TO = ("кто|что|какой|какая|какое|какие|какого|какой|каких|какому|каким|какую|какими|где|куда|когда|"
              "откуда|почему|зачем|чей|чья|чьё|чье|чьи|сколько|кого|кому|чем|чего|ком|как")
INDEFINITE = re.compile(r"\b(%s) (то|либо|нибудь)\b(?![,:])" % PRONOUN_TO, re.I)
KOE = re.compile(r"\b(кое) (кто|что|как|где|когда|куда|какой\w*|какая|какое|какие|чей\w*|кого|кому|чем|чего|ком)\b", re.I)
TAK_ZHE = re.compile(r"\b([Тт]ак) же\b")
GLUED_DIGIT = re.compile(r"\b([А-ЯЁа-яё][а-яё]{2,})(\d+)\b")
NUM_ADJ = re.compile(r"\b(\d+) ((?:часов|летн|дневн|месячн|недельн|кратн|процентн|минутн|секундн|разрядн|битн|"
                     r"байтн|ядерн|этажн|комнатн|уровнев|факторн|значн|потоков|канальн)[а-яё]*)\b")
ABOVE = re.compile(r"\b([Вв]ыше|[Нн]иже) ([а-яё]+)\b")
DOUBLE = re.compile(r"\b([А-Яа-яЁё]{2,}) \1\b", re.I)
IH_NIH = re.compile(r"\b([Ии])х (них|которых)\b")
NE_WORD = re.compile(r"\b([Нн]е) ([а-яё]{3,})\b")
NE_BLOCKERS = {"далеко", "вовсе", "отнюдь", "ничуть", "нисколько", "совсем", "ни"}
LATIN_PREFIX = re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*|[Вв]еб|[Ии]нтернет|[Оо]нлайн|[Оо]флайн|"
                          r"ИТ|IT) ([а-яё]+)\b")
HYPHEN_HEADS = {
    "сервер", "порт", "соединение", "подключение", "адаптер", "провайдер", "технология", "обозреватель", "атака",
    "сайт", "страница", "адрес", "ресурс", "приложение", "браузер", "клиент", "сервис", "шлюз", "туннель", "канал",
    "интерфейс", "запрос", "пакет", "трафик", "сканер", "сканирование", "модуль", "плагин", "ключ", "токен",
    "файл", "форма", "разработка", "разработчик", "магазин", "банкинг", "камера", "платформа", "сертификат",
    "инъекция", "фильтр", "аккаунт", "рассылка", "уведомление", "сообщение", "код", "карта", "накопитель",
    "флешка", "устройство", "точка", "роутер", "маршрутизатор", "коммутатор", "сканирование", "служба",
    "консоль", "скрипт", "агент", "кластер", "хранилище", "сеть", "реклама", "магазин", "конференция",
    "специалист", "отдел", "инфраструктура", "безопасность", "компания", "проект", "решение",
}
# capitalised mid-sentence by official convention
CAPITAL_OK = re.compile(r"^(Российск|Федераци|Президент|Правительств|Государственн|Дум|Конституци|Федеральн|"
                        r"Собрани|Совет|Суд|Министерств|Банк|Генеральн|Верховн|Центральн|Прокуратур|Палат|"
                        r"Администраци|Управлени|Республик|Кра[йе]|Област|Округ|Город|Москв|Санкт|Интернет|"
                        r"Бог|Отечеств|Родин|Герой|Орден|Евро|Союз|СССР|Россия|России)", re.I)
NAME_TAGS = ("Name", "Surn", "Patr", "Geox", "Orgn", "Trad", "Abbr", "Init")


ALPHABET = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
COMPOUND_PREFIX = re.compile(r"^(кибер|нано|нейро|крипто|био|эко|медиа|видео|аудио|теле|радио|авто|микро|макро|"
                             r"мега|гига|тера|экза|мини|мульти|анти|контр|псевдо|квази|супер|гипер|интер|транс|"
                             r"пост|суб|полу|само|мало|много|двух|трех|трёх|четырех|пяти|одно|разно|ново|"
                             r"сверх|меж|вне|сверх|около|после|пред)")


class Lexicon:
    """Spelling knowledge: pymorphy, hunspell (words it rejects) and a corpus frequency list."""

    def __init__(self, unknown=None, vocab_path=None):
        self.unknown = unknown
        self.freq = {}
        if vocab_path:
            for line in open(vocab_path, encoding="utf-8"):
                w, n = line.rstrip("\n").split("\t")
                self.freq[w] = int(n)

    def known(self, word):
        w = word.lower()
        if w in self.freq or morph.word_is_known(w) or (self.unknown is not None and word not in self.unknown):
            return True
        m = COMPOUND_PREFIX.match(w)  # "кибератака", "нанокапсула": productive prefix + known word
        return bool(m) and len(w) - m.end() >= 4 and (w[m.end():] in self.freq or morph.word_is_known(w[m.end():]))

    def known_strict(self, word):
        """Known to both dictionaries (used to confirm a joined spelling)."""
        return morph.word_is_known(word.lower()) and (self.unknown is None or word not in self.unknown)

    def suggest(self, word):
        """Most frequent known word within one or two letter edits, or None (then it is likely a term)."""
        w = word.lower()
        e1 = edits1(w)
        best = max((c for c in e1 if c in self.freq), key=self.freq.get, default=None)
        if best is None and len(w) >= 6:
            best = max((c for e in e1 for c in edits1(e) if c in self.freq), key=self.freq.get, default=None)
        if best is None:
            return None
        return best.capitalize() if word[0].isupper() else best


def edits1(w):
    splits = [(w[:i], w[i:]) for i in range(len(w) + 1)]
    return {a + b[1:] for a, b in splits if b} | {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1} | \
        {a + c + b[1:] for a, b in splits if b for c in ALPHABET} | {a + c + b for a, b in splits for c in ALPHABET}


class DocContext:
    """What the rest of the document tells about a sentence: recurring unknown words are terms, and
    the lemmas the author writes in lower case show which capitals are inconsistent."""

    def __init__(self, sentences=(), lexicon=None):
        unknown = collections.Counter()
        self.lower = collections.Counter()    # lemma -> times written in lower case
        self.capital = collections.Counter()  # lemma -> times capitalised mid-sentence
        for s in sentences:
            for m in CYR_WORD.finditer(s):
                w = m.group(0)
                if lexicon is not None and not lexicon.known(w):
                    unknown[w] += 1
                if w[0].islower():
                    self.lower[morph.parse(w)[0].normal_form] += 1
                elif w[1:].islower() and not sentence_start(s, m.start()):
                    self.capital[morph.parse(w)[0].normal_form] += 1
        self.terms = frozenset(w for w, n in unknown.items() if n >= 2)


CODE = re.compile(r"(\d|[A-ZА-ЯЁ]{2,}[.\d]*)$")  # "УБИ.156 Угроза", "06.1.1 Признание", "ЗНИ.1 Учет"
HARD_SIGN_END = re.compile(r"\b[А-Яа-яЁё]{2,}ъ\b")
NE_GOVERNING = {"способен", "способна", "способно", "способны", "должен", "должна", "должно", "должны", "готов",
                "готова", "готово", "готовы", "обязан", "обязана", "обязаны", "намерен", "согласен", "рад",
                "склонен", "склонна", "склонны", "вправе", "состоянии"}


LAT2CYR = str.maketrans("ABEKMHOPCTXaeopcxyi", "АВЕКМНОРСТХаеорсхуі")
CYR2LAT = str.maketrans("АВЕКМНОРСТХаеорсхуІі", "ABEKMHOPCTXaeopcxyIi")


def mixed_script(m, w, lexicon):
    """A word typed in two alphabets ("Cведения" with a latin C, "ХIХ" in Cyrillic and latin):
    invisible on screen, but it breaks search, sorting and spell checking."""
    cyr = w.translate(LAT2CYR)
    if not re.search(r"[A-Za-z]", cyr) and lexicon.known(cyr):
        return finding(m, 0, "error", "MIXED_SCRIPT", cyr, "Латинские буквы в русском слове")
    lat = w.translate(CYR2LAT)
    if not re.search(r"[А-Яа-яЁё]", lat):
        return finding(m, 0, "check", "MIXED_SCRIPT", lat, "Русские буквы в латинском слове или числе")
    return finding(m, 0, "check", "MIXED_SCRIPT", None, "В слове смешаны латинские и русские буквы")


def finding(m, group, level, rule, fix, message):
    s, e = m.span(group)
    return {"start": s, "end": e, "level": level, "rule": rule, "fix": fix, "message": message}


def sentence_start(text, pos):
    before = text[:pos].rstrip(" ")
    if not before or before[-1] in ".!?:;«(\"“•–—-" or before.endswith("№"):
        return True
    return bool(CODE.search(before.split(" ")[-1]))  # a list item after its number or code


def check(text, lexicon, ctx=None):
    ctx = ctx or DocContext()
    if BIBLIOGRAPHY.search(text):
        return []  # GOST 7.1 entries: abbreviations, names and their own capitalisation
    out = []
    quotes = [m.span() for m in QUOTED.finditer(text)]

    def in_quotes(pos):
        return any(a <= pos < b for a, b in quotes)

    # --- joined / hyphenated writing ---
    for m in INDEFINITE.finditer(text):
        word = m.group(1)
        if word.lower() == "как" and m.group(2) == "то":
            continue  # "как то:" introducing a list, "как то, так и" — leave to the reader
        out.append(finding(m, 0, "error", "DEFIS_PARTICLE", "%s-%s" % (word, m.group(2)),
                           "Частицы -то, -либо, -нибудь пишутся через дефис"))
    for m in KOE.finditer(text):
        out.append(finding(m, 0, "error", "DEFIS_KOE", "%s-%s" % (m.group(1), m.group(2)),
                           "«Кое-» пишется через дефис"))
    for m in TAK_ZHE.finditer(text):
        rest = text[m.end():m.end() + 80]
        if re.match(r"\s*[,.;:)]|\s*$", rest) or re.search(r"\bкак\b", rest.split(".")[0]):
            continue  # "так же, как ..." / "сделано так же."
        prev = text[:m.start()].rstrip()
        sure = not prev or prev[-1] in ".!?" or prev.endswith(" а") or prev.endswith(",а") or prev.endswith(", а")
        out.append(finding(m, 0, "error" if sure else "check", "TAKZHE", m.group(1) + "же",
                           "«Также» (= тоже, кроме того) пишется слитно; раздельно — только «так же, как»"))
    for m in GLUED_DIGIT.finditer(text):
        out.append(finding(m, 0, "error", "GLUED_DIGIT", "%s %s" % (m.group(1), m.group(2)),
                           "Между словом и числом нужен пробел"))
    for m in NUM_ADJ.finditer(text):
        if any(p.tag.POS == "ADJF" for p in morph.parse(m.group(2))):
            out.append(finding(m, 0, "error", "NUM_ADJ", "%s-%s" % (m.group(1), m.group(2)),
                               "Сложное прилагательное с цифрой пишется через дефис: «8-часовой»"))
    for m in ABOVE.finditer(text):
        joined = m.group(1) + m.group(2)
        if any(p.tag.POS in ("PRTF", "ADJF") for p in morph.parse(m.group(2))) and lexicon.known_strict(joined):
            out.append(finding(m, 0, "error", "ABOVE_JOIN", joined,
                               "«Вышеуказанный», «нижеперечисленный» и т. п. пишутся слитно"))
    for m in LATIN_PREFIX.finditer(text):
        head = m.group(2)
        lemmas = {p.normal_form for p in morph.parse(head) if p.tag.POS == "NOUN"}
        if lemmas & HYPHEN_HEADS and not in_quotes(m.start()):
            out.append(finding(m, 0, "check", "LATIN_HYPHEN", "%s-%s" % (m.group(1), head),
                               "Составные термины с латиницей или «веб-», «интернет-» обычно пишутся через дефис"))
    for m in NE_WORD.finditer(text):
        word = m.group(2)
        prev = text[:m.start()].split()[-1:] or [""]
        if prev[0].lower().strip(",") in NE_BLOCKERS | {"но", "а"}:
            continue  # "далеко не однозначными", contrast "но не исходная"
        parses = morph.parse(word)
        # participles in documents nearly always carry dependents ("не предусмотренные законом") and
        # are then written apart; comparatives ("не позднее") likewise
        if not parses or parses[0].tag.POS not in ("ADJF", "ADJS") or any(p.tag.POS == "PRTF" for p in parses) \
                or any("Cmp2" in p.tag or "COMP" in p.tag for p in parses) or word in NE_GOVERNING \
                or word in ("позднее", "ранее", "более", "менее"):
            continue
        nxt = text[m.end():].split()[:1]
        if nxt and any(p.tag.POS == "PREP" for p in morph.parse(nxt[0].strip(",.;:"))):
            continue  # a dependent follows: "не согласные с заключением", "не знакомы с инструментом"
        joined = m.group(1) + word
        tail = text[m.end():m.end() + 60]
        if not lexicon.known_strict(joined) or re.match(r"[^.;]*?,?\s+а\s", tail):
            continue  # unknown joined form, or contrast "не ..., а ..."
        out.append(finding(m, 0, "check", "NE_JOIN", joined,
                           "«Не» с прилагательными без противопоставления обычно пишется слитно"))

    # --- spelling ---
    for m in IH_NIH.finditer(text):
        out.append(finding(m, 0, "error", "IH_NIH", "%sз %s" % (m.group(1), m.group(2)), "Опечатка: «из них»"))
    for m in DOUBLE.finditer(text):
        out.append(finding(m, 0, "error", "DOUBLE_WORD", m.group(1), "Слово повторено дважды"))
    for m in HARD_SIGN_END.finditer(text):
        w = m.group(0)
        if lexicon.known(w[:-1] + "ь"):
            out.append(finding(m, 0, "error", "HARD_SIGN", w[:-1] + "ь", "Опечатка: «ъ» вместо «ь»"))
    for m in TOKEN.finditer(text):
        w = m.group(0)
        if in_quotes(m.start()):
            continue
        letters = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", w)
        if re.search(r"[A-Za-z]", letters) and re.search(r"[А-Яа-яЁё]", letters) and not re.search(r"[-‑\d]", w):
            out.append(mixed_script(m, w, lexicon))
            continue
        if not re.fullmatch(r"[А-Яа-яЁё]+(-[А-Яа-яЁё]+)*", w) or len(w) < 4 or w.isupper() or w in ctx.terms:
            continue
        if any(c.isupper() for c in w):
            continue  # names and abbreviations (a sentence may start with a surname split off its initials)
        if w.endswith("ъ") or all(lexicon.known(p) for p in w.split("-") if p) or lexicon.known(w):
            continue
        fix = lexicon.suggest(w)
        if fix is None:
            continue  # nothing close in the dictionary: a term or a name, not a typo
        out.append(finding(m, 0, "check", "TYPO", fix, "Возможна опечатка: «%s»?" % fix))

    # --- capitalisation: a capital mid-sentence on a word the author elsewhere writes in lower case ---
    for m in CYR_WORD.finditer(text):
        w = m.group(0)
        if not (w[0].isupper() and w[1:].replace("-", "").islower() and len(w) >= 3):
            continue
        if sentence_start(text, m.start()) or in_quotes(m.start()) or CAPITAL_OK.match(w):
            continue
        parses = morph.parse(w)
        if not parses or any(t in parses[0].tag for t in NAME_TAGS) or not morph.word_is_known(w.lower()):
            continue
        lemma = parses[0].normal_form
        if ctx.lower[lemma] <= ctx.capital[lemma]:
            continue  # capitalised as often as not in this document: a defined term ("Заказчик") or a name
        prev = text[:m.start()].rstrip().split(" ")[-1:]
        nxt = text[m.end():].lstrip().split(" ")[:1]
        if prev and prev[0][:1].isupper() and not sentence_start(text, m.start() - len(prev[0]) - 1):
            continue  # inside a multi-word name: "Содружества Независимых Государств"
        if nxt and nxt[0][:1].isupper() and nxt[0][1:2].islower():
            continue  # the first word of one: "Вооруженных Сил"
        # off by default: these documents legitimately capitalise document titles, roles and UI names
        # ("к Порядку", "Заказчик", "вкладку Безопасность") — 7 right vs 47 false on the 3100-sentence gold
        out.append(finding(m, 0, "strict", "CAPITAL_MID", w[0].lower() + w[1:],
                           "В остальном тексте это слово написано со строчной буквы"))
    return out


def apply(text, findings, levels=("error",)):
    """Apply the fixes of findings of the given levels (non-overlapping, left to right)."""
    out, last = [], 0
    for f in sorted((f for f in findings if f["level"] in levels and f["fix"]), key=lambda f: f["start"]):
        if f["start"] < last:
            continue
        out.append(text[last:f["start"]])
        out.append(f["fix"])
        last = f["end"]
    out.append(text[last:])
    return "".join(out)
