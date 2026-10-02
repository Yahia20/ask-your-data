import pytest

from ask_data.linking import Ambiguous, Linker, NotFound

AGENTS = ["أحمد الغامدي", "محمد العتيبي", "محمد الشهري", "سارة القحطاني"]
linker = Linker({"agent": AGENTS, "destination": ["Istanbul", "Dubai"]},
                {"destination": {"إسطنبول": "Istanbul", "اسطنبول": "Istanbul", "دبي": "Dubai"}})


def test_exact_and_misspelled_names_resolve():
    assert linker.resolve("agent", "سارة القحطاني") == "سارة القحطاني"
    assert linker.resolve("agent", "سارا القحطانى") == "سارة القحطاني"


def test_a_unique_first_name_is_enough():
    assert linker.resolve("agent", "أحمد") == "أحمد الغامدي"
    assert linker.resolve("agent", "احمد") == "أحمد الغامدي"


def test_a_shared_first_name_asks_which():
    with pytest.raises(Ambiguous) as e:
        linker.resolve("agent", "محمد")
    assert set(e.value.options) == {"محمد العتيبي", "محمد الشهري"}


def test_arabic_aliases_and_spelling_variants_map_to_stored_values():
    assert linker.resolve("destination", "استنبول") == "Istanbul"   # fuzzy, close to an alias
    assert linker.resolve("destination", "دبى") == "Dubai"          # ى/ي folded
    assert linker.resolve("destination", "dubai") == "Dubai"


def test_unknown_value_is_reported_not_guessed():
    with pytest.raises(NotFound):
        linker.resolve("destination", "طوكيو")


def test_dimensions_without_a_value_list_pass_through():
    assert linker.resolve("channel", "whatsapp") == "whatsapp"
