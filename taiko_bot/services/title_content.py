"""Public official titles; no account unlock state or local custom titles."""
from taiko_bot.services.title_catalog import load_title_catalog_items


def get_official_titles_content():
    items = load_title_catalog_items()
    if not items:
        raise ValueError("Official title catalog unavailable")
    titles = []
    for item in items:
        condition = str(item.get("subtitle") or "").strip()
        if not condition or all(character in "?？ \t\n" for character in condition):
            condition = ""
        titles.append({
            "id": item.get("id", item.get("uid", 0)),
            "name": item["name"],
            "rarity": item["rarity"],
            "condition": condition,
            "songIds": [],
        })
    return {"titles": titles, "total": len(titles)}
