"""Required capture fields shared by the prompt and deterministic draft handler."""

FIELDS = {"region": "Регион", "sector": "Сектор", "name": "Название трассы", "grade": "Категория",
          "reached_top": "Дошёл до конца: да или нет",
          "clean_ascent": "Чисто: да или нет", "style": "Стиль: onsight / flash / redpoint / не долез / со срывом / с зависанием",
          "belay": "Страховка: нижняя / верхняя / автостраховка / боулдеринг"}


def missing_fields(facts):
    return [key for key in ("region", "sector", "name", "grade", "belay") if facts.get(key) is None or facts.get(key) == "" or
            facts.get(key) == "unknown"]


