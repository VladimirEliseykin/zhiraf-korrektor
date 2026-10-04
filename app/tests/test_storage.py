import os

from zhiraf import storage


def test_dictionary_ignores_case_and_survives_restart():
    d = storage.Dictionary()
    d.add("ИСПДн")
    assert "испдн" in d and "ИСПДН" in d and " ИСПДн " in d
    assert "ИСПДн" in storage.Dictionary()
    assert storage.Dictionary().words() == ["ИСПДн"]


def test_dictionary_remove():
    d = storage.Dictionary()
    d.add("фаззинг")
    d.remove("ФАЗЗИНГ")
    assert "фаззинг" not in storage.Dictionary()


def test_dictionary_export_and_import_merge(tmp_path):
    a = storage.Dictionary(str(tmp_path / "a.txt"))
    for w in ("ИСПДн", "КИИ"):
        a.add(w)
    a.export(str(tmp_path / "отдел.txt"))
    b = storage.Dictionary(str(tmp_path / "b.txt"))
    b.add("КИИ")
    assert b.import_from(str(tmp_path / "отдел.txt")) == 1
    assert b.words() == ["ИСПДн", "КИИ"]


def test_dictionary_file_holds_one_word_per_line():
    d = storage.Dictionary()
    d.add("Б")
    d.add("а")
    assert open(d.path, encoding="utf-8").read() == "а\nБ\n"


def test_settings_defaults_and_persistence():
    s = storage.Settings()
    assert s["show_checks"] is True and s["strict_mode"] is False and s["remember_recent"] is True
    s.set("strict_mode", True)
    assert storage.Settings()["strict_mode"] is True


def test_settings_survive_a_damaged_file():
    s = storage.Settings()
    with open(s.path, "w", encoding="utf-8") as f:
        f.write("{не json")
    assert storage.Settings()["show_checks"] is True


def test_recent_newest_first_without_duplicates(tmp_path):
    r = storage.Recent(storage.Settings())
    r.touch(str(tmp_path / "a.docx"), {"fixed": 1})
    r.touch(str(tmp_path / "b.docx"))
    r.touch(str(tmp_path / "a.docx"))
    items = storage.Recent(storage.Settings()).items()
    assert [os.path.basename(i["path"]) for i in items] == ["a.docx", "b.docx"]
    assert items[0]["stats"] == {"fixed": 1}  # counters are kept when the file is opened again


def test_recent_is_limited_and_clearable(tmp_path):
    r = storage.Recent(storage.Settings())
    for n in range(storage.MAX_RECENT + 5):
        r.touch(str(tmp_path / ("%d.docx" % n)))
    assert len(r.items()) == storage.MAX_RECENT
    r.clear()
    assert storage.Recent(storage.Settings()).items() == []


def test_recent_not_written_when_disabled(tmp_path):
    s = storage.Settings()
    s.set("remember_recent", False)
    storage.Recent(s).touch(str(tmp_path / "secret.docx"))
    assert storage.Recent(s).items() == []


def test_clean_tmp_removes_leftovers():
    leftover = os.path.join(storage.tmp_dir(), "copy.docx")
    open(leftover, "w").close()
    storage.clean_tmp()
    assert os.path.isdir(storage.tmp_dir()) and not os.path.exists(leftover)


def test_folders_follow_profile_override(zhiraf_home):
    assert storage.data_dir() == str(zhiraf_home)
    assert storage.tmp_dir() == os.path.join(str(zhiraf_home), "tmp")


def test_dictionary_loads_cp1251_encoded_file(tmp_path):
    path = str(tmp_path / "cp1251_dict.txt")
    # Write file in cp1251 encoding
    with open(path, "wb") as f:
        f.write("слово\nтест\n".encode("cp1251"))
    d = storage.Dictionary(path)
    assert "слово" in d
    assert "тест" in d
    assert d.words() == ["слово", "тест"]


def test_dictionary_import_from_cp1251_file(tmp_path):
    # Create a cp1251 encoded file
    src_path = str(tmp_path / "cp1251_import.txt")
    with open(src_path, "wb") as f:
        f.write("импорт\nданные\n".encode("cp1251"))

    d = storage.Dictionary(str(tmp_path / "main_dict.txt"))
    d.add("существующее")
    count = d.import_from(src_path)
    assert count == 2  # both words are new
    assert "импорт" in d
    assert "данные" in d
    assert "существующее" in d


def test_recent_with_invalid_entries_loads_valid_ones(tmp_path):
    import json
    import time

    recent_path = str(tmp_path / "recent.json")
    # Write a file with mixed valid and invalid entries
    data = [
        {"path": "a.docx", "opened_at": time.time(), "stats": {}},
        "x",  # invalid: not a dict
        {"opened_at": 1},  # invalid: missing "path"
        {"path": "b.docx", "opened_at": time.time(), "stats": {}},
    ]
    with open(recent_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    r = storage.Recent(storage.Settings(), recent_path)
    items = r.items()
    assert len(items) == 2
    paths = [os.path.basename(i["path"]) for i in items]
    assert set(paths) == {"a.docx", "b.docx"}

    # touch() should work after loading corrupted file
    r.touch(str(tmp_path / "c.docx"), {"fixed": 5})
    assert len(r.items()) == 3
