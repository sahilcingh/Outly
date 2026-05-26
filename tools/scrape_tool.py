"""
Web scrape tool using BeautifulSoup and requests.
Extracts main body text from HTML (excludes nav, footer, scripts).
"""

import logging
import urllib.request
import urllib.error
import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive"
}

def _fetch_html(url: str) -> str:
    """Fetch HTML with robust fallback mechanisms."""
    try:
        # Attempt 1: Standard requests with robust headers
        session = requests.Session()
        resp = session.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        log.debug("requests.get failed (%s) — trying urllib fallback.", e)
        try:
            # Attempt 2: urllib request (sometimes bypasses basic requests blocks)
            req = urllib.request.Request(
                url, 
                data=None, 
                headers={"User-Agent": HEADERS["User-Agent"], "Accept": HEADERS["Accept"]}
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read().decode('utf-8', errors='ignore')
        except Exception as fallback_e:
            raise Exception(f"All scraping attempts failed. Last error: {fallback_e}")

def scrape(url: str) -> str:
    """
    Fetch URL and extract main body text from HTML.

    Removes nav, header, footer, scripts, styles. Uses heuristics to find
    the main content block.

    Args:
        url: Full URL to scrape.

    Returns:
        Extracted text (raw, not yet cleaned - use text_cleaner.clean_text).
    """
    html = _fetch_html(url)
    return _extract_body(html)


def extract_social_links(html: str) -> list[str]:
    """Extract social media links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    social_domains = [
        "linkedin.com/company", "linkedin.com/in",
        "twitter.com", "x.com", 
        "facebook.com", "instagram.com", "youtube.com"
    ]
    links = set()
    for a in soup.find_all("a", href=True):
        try:
            href = a["href"].lower()
            if any(domain in href for domain in social_domains):
                links.add(a["href"])
        except KeyError:
            continue
    return list(links)


def scrape_with_socials(url: str) -> tuple[str, list[str]]:
    """
    Fetch URL, extract main body text, and find social media links.
    """
    html = _fetch_html(url)
    return _extract_body(html), extract_social_links(html)


def _extract_body(html: str) -> str:
    """Extract main content from HTML string."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove non-content elements
    for tag in soup.find_all(
        ["script", "style", "noscript", "svg", "iframe", "nav", "header", "footer", "aside"]
    ):
        tag.decompose()

    # Remove common boilerplate by role/class/id
    for sel in ['[role="navigation"]', '[role="banner"]', '[role="contentinfo"]', ".navbar", ".footer", ".sidebar", ".ads"]:
        for el in soup.select(sel):
            el.decompose()

    # Prefer <main> or <article>
    for selector in ["main", "article"]:
        el = soup.select_one(selector)
        if el and len(el.get_text(strip=True)) > 200:
            return el.get_text(separator=" ", strip=True)

    # Heuristic: largest text block with low link density
    best = None
    best_score = 0
    for el in soup.find_all(["article", "section", "div", "main"]):
        text = el.get_text(separator=" ", strip=True)
        if len(text) < 200:
            continue
        link_text_len = sum(len(a.get_text(strip=True)) for a in el.find_all("a"))
        link_density = link_text_len / len(text) if text else 0
        score = len(text) * (1 - link_density)
        if score > best_score:
            best_score = score
            best = el

    if best:
        return best.get_text(separator=" ", strip=True)

    return soup.body.get_text(separator=" ", strip=True) if soup.body else ""
