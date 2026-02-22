from bs4 import Tag


def text(selector: str, soup: Tag) -> str:
    el = soup.select_one(selector)
    return el.get_text(strip=True) if el else ""