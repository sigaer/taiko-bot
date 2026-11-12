"""Full-length Chinese homophones, with literal non-Chinese characters."""

from functools import lru_cache

from pypinyin import Style, pinyin


def _is_han(char: str) -> bool:
    return '\u3400' <= char <= '\u9fff' or '\U00020000' <= char <= '\U000323af'


@lru_cache(maxsize=8192)
def _tokens(value: str):
    tokens = []
    for char in value:
        if _is_han(char):
            readings = pinyin(char, style=Style.NORMAL, heteronym=True,
                              errors=lambda text: [text])[0]
            tokens.append(frozenset(readings))
        else:
            tokens.append(frozenset(('literal:' + char,)))
    return tuple(tokens)


def same_pronunciation(query: str, candidate: str) -> bool:
    # Do not turn kana, Latin text, bare numbers or short fragments of a long
    # title into Chinese sound matches. Keep syllable boundaries intact.
    return (len(query) == len(candidate) and any(map(_is_han, query))
            and all(left & right for left, right in zip(_tokens(query), _tokens(candidate))))
