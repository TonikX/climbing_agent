"""Required capture fields shared by the prompt and deterministic draft handler."""

FIELDS = {"region": "Регион", "sector": "Сектор", "name": "Название трассы", "grade": "Категория",
          "clean_ascent": "Чисто: да или нет", "style": "Стиль: onsight / flash / redpoint / со срывом / с зависанием",
          "belay": "Страховка: нижняя / верхняя / автостраховка / боулдеринг"}


def missing_fields(facts):
    return [key for key in FIELDS if facts.get(key) is None or facts.get(key) == "" or
            (facts.get(key) == "unknown" and (key == "belay" or not facts.get("manual")))]


