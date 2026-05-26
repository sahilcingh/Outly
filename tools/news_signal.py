"""
News signal fetcher: finds recent company news via DuckDuckGo News search.
Returns headlines that indicate growth signals (funding, launches, expansion).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_GROWTH_QUERY = (
    '"{name}" funding OR launch OR raises OR expansion OR '
    'partnership OR acquires OR product OR series'
)


def find_recent_news(company_name: str, max_results: int = 3) -> list[dict]:
    """
    Return recent news items about the company.
    Each item: {"title": str, "snippet": str, "date": str}
    Returns empty list on failure.
    """
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        log.warning("duckduckgo_search not installed — skipping news signals")
        return []

    query = _GROWTH_QUERY.format(name=company_name)
    try:
        with DDGS() as ddgs:
            raw = list(ddgs.news(query, max_results=max_results * 2, safesearch="off"))
    except Exception as e:
        log.warning("News search failed for '%s': %s", company_name, e)
        return []

    news: list[dict] = []
    for r in raw:
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        date = (r.get("date") or "").strip()
        if not title or not body:
            continue
        news.append({"title": title, "snippet": body[:220], "date": date})
        if len(news) >= max_results:
            break

    if news:
        log.info("News signals for '%s': %d items found", company_name, len(news))
    return news
