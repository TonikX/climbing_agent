"""Russian/Latin/Turkish search key; never an entity identity or a translation."""
_letters = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n",
    "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f",
    "х": "kh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y",
    "ь": "", "э": "e", "ю": "yu", "я": "ya",
}
_expression = """regexp_replace(translate(replace(replace(lower(replace(value,'İ','I')),'ş','sh'),'ç','ch'),
 'ığşçöüâîûáàäãåéèêëíìïóòôõúùÿñё',
 'igscouaiuaaaaaeeeeiiioooouuynе'), '[^[:alnum:]]+', '', 'g')"""
for _letter, _latin in _letters.items():
    _expression = f"replace({_expression},'{_letter}','{_latin}')"
# y/i and kh/h are common alternative spellings. Collisions remain suggestions.
_expression = f"replace(replace({_expression},'kh','h'),'y','i')"
# Turkish c is commonly written дж, j is ж. Preserve ch from ç/ч.
# The original spelling is still checked separately for exact matches.
_expression = f"regexp_replace(replace(replace({_expression},'dzh','j'),'zh','j'),'c(?!h)','j','g')"
TRANSLIT_SQL = f"""CREATE OR REPLACE FUNCTION catalog_translit(value text) RETURNS text
LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$ SELECT {_expression} $$"""
