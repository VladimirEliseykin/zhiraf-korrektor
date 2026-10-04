"""The one shared morphological analyser.

The dictionary path is passed explicitly: pymorphy3 otherwise discovers it through package entry
points (pkg_resources / importlib.metadata), which an embeddable Python 3.7 does not have.
One instance for every module also keeps the memory of the dictionary paid once.
"""
import pymorphy3
import pymorphy3_dicts_ru

morph = pymorphy3.MorphAnalyzer(path=pymorphy3_dicts_ru.get_path())
