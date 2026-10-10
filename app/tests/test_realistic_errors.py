"""The realistic error generator (train/corrupt.py corrupt_realistic, train/error_context.py).

Every sentence is invented; no gold, corpus or document text is used here."""
import collections
import os
import random
import sys

import zhiraf

sys.path.insert(0, os.path.join(zhiraf.ROOT, "train"))
import corrupt as cr  # noqa: E402
import error_context as ec  # noqa: E402

SENTENCES = [
    "Компания получила большую прибыль от продажи акций, поэтому руководство пересмотрело планы на следующий год.",
    "Пользователь вводит пароль, который хранится в защищенной базе данных, и получает доступ к системе.",
    "При выполнении задания сотрудник проверяет документы, подготовленные накануне, и передает их начальнику отдела.",
    "Для защиты информации используются межсетевые экраны, системы обнаружения вторжений и средства шифрования данных.",
    "Администратор назначает роли пользователям, а руководитель утверждает перечень доступных им ресурсов.",
    "Система хранит данные пользователей и передает их в центр обработки запросов клиентов компании.",
    "Если запрос не прошел проверку, сервер возвращает ошибку и записывает событие в журнал безопасности.",
    "Модель угроз описывает нарушителей, возможные способы атак и последствия реализации каждой из них.",
]


def same(a, b):
    """pymorphy writes ё where the invented text has е: that spelling difference is not a label error."""
    return a.replace("ё", "е") == b.replace("ё", "е")


def many(fn, seeds=range(300)):
    for seed in seeds:
        for text in SENTENCES:
            yield text, fn(text, random.Random(seed))


DENSE = dict(realistic=True, error_rate=40.0, max_edits=4)


def test_labels_align_and_restore_the_clean_text():
    changed = 0
    for text, (c, comma, form) in many(lambda t, r: cr.corrupt(t, r, **DENSE)):
        assert len(cr.words_of(c)) == len(comma) == len(form)
        assert same(cr.restore(c, comma, form), text)
        changed += c != text
    assert changed > 300  # a dense rate really corrupts


def test_realistic_labels_use_the_same_label_set_as_the_old_recipes():
    comma_labels, forms = set(), set()
    for _, (_, comma, form) in many(lambda t, r: cr.corrupt(t, r, **DENSE)):
        comma_labels |= set(comma)
        forms |= set(form)
    assert comma_labels == {cr.COMMA_KEEP, cr.COMMA_ADD, cr.COMMA_DEL}
    assert cr.FORM_KEEP in forms and len(forms) > 3
    assert all(f == "KEEP" or f.split("|")[0].split(":")[0] in ("case", "number", "gender", "person") for f in forms)


def test_flags_off_reproduce_the_old_recipes_exactly():
    for seed in range(40):
        for text in SENTENCES:
            old = cr.corrupt(text, random.Random(seed))
            assert cr.corrupt(text, random.Random(seed), realistic=False) == old
            assert cr.corrupt(text, random.Random(seed), realistic=False, error_rate=7.0, form_scale=3.0) == old
            assert cr.corrupt_spell(text, random.Random(seed)) == old + (["KEEP"] * len(old[1]),)


def edits_of(c, comma, form):
    return sum(x != "KEEP" for x in comma) + sum(x != "KEEP" for x in form)


def test_real_density_leaves_most_sentences_clean_and_errors_follow_the_length():
    clean = total = 0
    for text, (c, comma, form) in many(lambda t, r: cr.corrupt(t, r, realistic=True, error_rate=1.0), range(200)):
        clean += c == text
        total += 1
    assert clean / total > 0.75          # real documents: about nine sentences in ten are clean

    def mean_edits(text):
        return sum(edits_of(*cr.corrupt(text, random.Random(s), realistic=True, error_rate=10.0)) for s in range(500)) / 500

    short, long_text = "Система хранит данные пользователей.", " ".join([SENTENCES[1], SENTENCES[3]])
    assert mean_edits(long_text) > 2 * mean_edits(short)


def test_the_count_of_errors_is_capped():
    for seed in range(100):
        for text in SENTENCES:
            c, comma, form = cr.corrupt(text, random.Random(seed), realistic=True, error_rate=1000.0, max_edits=2)
            assert edits_of(c, comma, form) <= 2


def test_tiny_sentences_are_never_touched():
    for seed in range(50):
        assert cr.corrupt("Да, нет.", random.Random(seed), realistic=True, error_rate=50.0)[0] == "Да, нет."


def test_context_classes_of_commas():
    def ctx(text, i, has_comma_before=False):
        return ec.comma_features(text, cr.words_of(text), i, has_comma_before)["ctx"]
    assert ctx("Файл хранится в базе который создал администратор", 3) == "subord"
    assert ctx("Мы создали отчет но не успели его отправить", 2) == "advers"
    assert ctx("Роли получают сотрудники и руководители", 2) == "and_or"
    assert ctx("Мы используем ключи, подписи и сертификаты", 4, True) in ("and_or", "homogeneous", "other")


def frequencies(text, label_list, n=4000, **kwargs):
    counts = collections.Counter()
    for seed in range(n):
        _, comma, form = cr.corrupt(text, random.Random(seed), realistic=True, **kwargs)
        for i, label in enumerate(comma):
            counts[i] += label == label_list
    return {i: c / n for i, c in counts.items()}


def expected(text, kind, rate):
    ms = cr.words_of(text)
    drop, add = cr.comma_candidates(text, ms)
    cands, table, base = (drop, cr.MISSING_WEIGHT, cr.BASE_RATE["missing"]) if kind == "drop" \
        else (add, cr.SPURIOUS_WEIGHT, cr.BASE_RATE["spurious"])
    return {i: min(cr.P_MAX, rate * base * cr.comma_weight(table, f)) for i, f in cands}


def test_spurious_commas_follow_the_measured_rates_and_prefer_the_real_contexts():
    text = SENTENCES[5]
    ms = cr.words_of(text)
    before_and = next(i for i, m in enumerate(ms) if m.group(0) == "и") - 1
    exp = expected(text, "add", 40.0)
    seen = frequencies(text, cr.COMMA_DEL, error_rate=40.0, max_edits=99)
    for i, p in exp.items():
        assert abs(seen.get(i, 0.0) - p) < 0.02
    plain = [p for i, p in exp.items() if i != before_and]
    assert exp[before_and] > 2 * sorted(plain)[len(plain) // 2]     # a comma before "и" beats a median place


def test_missing_commas_follow_the_measured_rates():
    text = SENTENCES[2]
    exp = expected(text, "drop", 40.0)
    seen = frequencies(text, cr.COMMA_ADD, error_rate=40.0, max_edits=99)
    assert len(exp) == 2
    for i, p in exp.items():
        assert abs(seen.get(i, 0.0) - p) < 0.02


def test_wrong_cases_are_mostly_the_unmarked_nominative_and_genitive():
    seen = collections.Counter()
    for seed in range(600):
        res = cr.corrupt_form_realistic("документе", "after_preposition", random.Random(seed))
        if res:
            seen[res[1]] += 1
    assert sum(seen.values()) > 500
    cases = {label: n for label, n in seen.items() if label.startswith("case:")}
    assert sum(cases.values()) > 0.8 * sum(seen.values())            # a noun after a preposition: case errors mostly
    assert set(cases) == {"case:loct"}                               # the label restores the original case


def test_fitted_tables_are_complete_positive_and_ordered_as_the_counts():
    for counts, weights in ((cr.MISSING_COUNTS, cr.MISSING_WEIGHT), (cr.SPURIOUS_COUNTS, cr.SPURIOUS_WEIGHT)):
        assert set(weights) == set(counts)
        for feature in counts:
            assert set(weights[feature]) == set(counts[feature])
            assert all(w > 0 for w in weights[feature].values())
    assert set(cr.FORM_WEIGHT) == set(cr.FORM_COUNTS) and all(w > 0 for w in cr.FORM_WEIGHT.values())
    assert all(0 < r < 0.1 for r in cr.BASE_RATE.values())
    assert cr.MISSING_WEIGHT["ctx"]["and_or"] > cr.MISSING_WEIGHT["ctx"]["other"] > cr.MISSING_WEIGHT["ctx"]["advers"]
    assert cr.SPURIOUS_WEIGHT["ctx"]["and_or"] > cr.SPURIOUS_WEIGHT["ctx"]["other"]
    assert cr.FORM_WEIGHT["participle_after_noun"] > cr.FORM_WEIGHT["noun_after_adj"]
    assert cr.FORM_WEIGHT["after_numeral"] > cr.FORM_WEIGHT["noun_after_adj"]


def test_install_weights_changes_the_placement_and_can_be_restored():
    text = SENTENCES[2]
    saved = (cr.BASE_RATE, cr.MISSING_WEIGHT, cr.SPURIOUS_WEIGHT, cr.FORM_WEIGHT)
    try:
        cr.install_weights(missing={}, spurious={}, forms={})        # no weights: every place alike
        flat = expected(text, "drop", 10.0)
        assert len(set(flat.values())) == 1
    finally:
        cr.install_weights(*saved)
    assert len(set(expected(text, "drop", 10.0).values())) > 1
