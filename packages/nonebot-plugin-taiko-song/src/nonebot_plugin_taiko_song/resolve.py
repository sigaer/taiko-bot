def resolve_query(raw_q: str, stripped_q: str, query_with_mode):
    def queryMusic(q, **kwargs):
        return query_with_mode(q, **kwargs)[0]
    if not stripped_q or stripped_q == raw_q:
        return queryMusic(raw_q)

    # 先保留真正存在的“里xxx/鬼xxx”精确别名或曲名，再优先解析去前缀后的关键词。
    raw_exact_results, _ = query_with_mode(
        raw_q, allow_partial=False, allow_fuzzy=False
    )
    if raw_exact_results:
        return raw_exact_results

    stripped_non_fuzzy_results = queryMusic(stripped_q, allow_fuzzy=False)
    if stripped_non_fuzzy_results:
        return stripped_non_fuzzy_results

    raw_non_fuzzy_results = queryMusic(raw_q, allow_fuzzy=False)
    if raw_non_fuzzy_results:
        return raw_non_fuzzy_results

    stripped_results = queryMusic(stripped_q)
    if stripped_results:
        return stripped_results

    return queryMusic(raw_q)
