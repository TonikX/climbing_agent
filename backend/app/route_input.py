"""Recover a route name when an extractor puts a labelled ascent card in it."""
import re

_FIELD = re.compile(
    r"(?:^|[\s;])(?P<label>Название\s+трассы|Категория|Регион|Сектор|Чисто|Стиль|Страховка|Дош[её]л\s+до\s+конца)\s*:\s*",
    re.IGNORECASE,
)


def route_name(value):
    if not isinstance(value, str):
        return value
    fields = list(_FIELD.finditer(value))
    labels = {re.sub(r"\s+", " ", field["label"].casefold()) for field in fields}
    if "название трассы" not in labels or not labels.intersection({"регион", "сектор", "категория"}):
        return value
    # The innermost name wins if a card itself was nested in another card's name.
    for index in range(len(fields)-1, -1, -1):
        if re.sub(r"\s+", " ", fields[index]["label"].casefold()) == "название трассы":
            end = fields[index+1].start() if index+1 < len(fields) else len(value)
            return value[fields[index].end():end].strip()
    return value
