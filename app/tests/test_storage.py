import os

import pytest

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
    assert storage.tmp_dir() == os.path.join(str(zhiraf_home), "tmp", str(os.getpid()))


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


def blocked_dictionary(tmp_path):
    path = tmp_path / "словарь.txt"
    path.mkdir()                      # a folder where the file should be: every write fails
    return storage.Dictionary(str(path))


def test_dictionary_add_rolls_back_when_write_fails(tmp_path):
    d = blocked_dictionary(tmp_path)
    with pytest.raises(OSError):
        d.add("Жирафик")
    assert "Жирафик" not in d and len(d) == 0


def test_dictionary_remove_rolls_back_when_write_fails(tmp_path):
    path = tmp_path / "словарь.txt"
    path.write_text("Жирафик\n", encoding="utf-8")
    d = storage.Dictionary(str(path))
    path.unlink()
    path.mkdir()
    with pytest.raises(OSError):
        d.remove("Жирафик")
    assert "Жирафик" in d


def test_dictionary_import_rolls_back_when_write_fails(tmp_path):
    src = tmp_path / "чужой.txt"
    src.write_text("Жирафик\n", encoding="utf-8")
    d = blocked_dictionary(tmp_path)
    with pytest.raises(OSError):
        d.import_from(str(src))
    assert len(d) == 0


def test_settings_set_rolls_back_when_write_fails(tmp_path):
    bad = tmp_path / "настройки.json"
    bad.mkdir()
    s = storage.Settings(str(bad))
    with pytest.raises(OSError):
        s.set("strict_mode", True)
    assert s["strict_mode"] is False


def test_failed_write_leaves_no_tmp_file(tmp_path):
    target = tmp_path / "папка.txt"
    target.mkdir()                    # os.replace onto a folder fails after the .tmp is written
    with pytest.raises(OSError):
        storage._write_atomic(str(target), "текст")
    assert not os.path.exists(str(target) + ".tmp")


def test_tmp_dir_is_per_process_and_clean_keeps_a_live_neighbour(zhiraf_home):
    mine = storage.tmp_dir()
    assert os.path.basename(mine) == str(os.getpid())
    neighbour = os.path.join(os.path.dirname(mine), str(os.getppid()))   # a live process
    dead = os.path.join(os.path.dirname(mine), "999999999")
    for p in (neighbour, dead):
        os.makedirs(p, exist_ok=True)
    storage.clean_tmp()
    assert os.path.isdir(neighbour) and not os.path.exists(dead) and os.path.isdir(storage.tmp_dir())


def test_recent_normalises_malformed_entries(tmp_path):
    import json
    raw = [
        {"path": "/a.docx", "opened_at": "yesterday", "stats": "oops"},
        {"path": "/b.docx", "opened_at": 1e300, "stats": {"fixed": 2, "skipped": -1, "handled": None, "total": "5", "x": 1}},
        {"path": "/c.docx", "opened_at": 1700000000, "stats": {"fixed": 1, "skipped": 2, "handled": 3, "total": 4}},
        {"path": "/d.docx", "opened_at": float("nan"), "stats": [1]},
        {"path": 5}, "junk",
    ]
    p = tmp_path / "r.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    items = storage.Recent(storage.Settings(), str(p)).items()
    assert [i["path"] for i in items] == ["/a.docx", "/b.docx", "/c.docx", "/d.docx"]
    assert items[0]["opened_at"] is None and items[0]["stats"] == {}
    assert items[1]["opened_at"] is None and items[1]["stats"] == {"fixed": 2}
    assert items[2]["opened_at"] == 1700000000.0
    assert items[2]["stats"] == {"fixed": 1, "skipped": 2, "handled": 3, "total": 4}
    assert items[3]["opened_at"] is None and items[3]["stats"] == {}


def test_recent_touch_cleans_stats(tmp_path):
    r = storage.Recent(storage.Settings(), str(tmp_path / "r.json"))
    r.touch(str(tmp_path / "a.docx"), {"fixed": "x", "handled": None, "total": True, "skipped": 2})
    assert r.items()[0]["stats"] == {"skipped": 2}
    assert storage.Recent(storage.Settings(), str(tmp_path / "r.json")).items()[0]["stats"] == {"skipped": 2}


def test_recent_load_survives_huge_and_bool_time(tmp_path):
    p = tmp_path / "r.json"
    p.write_text('[{"path": "/a", "opened_at": 1%s}, {"path": "/b", "opened_at": true},'
                 ' {"path": "/c", "opened_at": -5}]' % ("0" * 400), encoding="utf-8")
    items = storage.Recent(storage.Settings(), str(p)).items()
    assert [i["opened_at"] for i in items] == [None, None, None]
