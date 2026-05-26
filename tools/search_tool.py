"""
DuckDuckGo search tool + bulletproof official website finder.

Three-phase approach:
  Phase 1 – Direct probe: construct plausible domain names and HTTP-probe them.
             Returns immediately if a confirmed match is found. Follows redirects,
             so generalelectric.com → ge.com is handled automatically.
  Phase 2 – Search + score: run DuckDuckGo with multiple strategies, score each
             root domain using name + title signals. Retries once on empty results.
  Phase 3 – Verify: HTTP-probe the search winner to confirm it's alive (not 404).
             Falls back to next-best candidate if the winner is unreachable.

Wikipedia and all directory/aggregator sites are hard-blocked at every phase.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass

import requests

try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

log = logging.getLogger(__name__)

PROBE_TIMEOUT = 6  # seconds per HTTP probe
PROBE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Hard-blocked domains — never returned as an official website
JUNK_DOMAINS: frozenset[str] = frozenset({
    "linkedin.com", "crunchbase.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "bloomberg.com", "pitchbook.com", "zoominfo.com",
    "glassdoor.com", "g2.com", "capterra.com", "forbes.com", "fortune.com",
    "wikipedia.org", "wikimedia.org", "wikidata.org", "en.m.wikipedia.org",
    "youtube.com", "ycombinator.com", "techcrunch.com", "reuters.com",
    "businesswire.com", "prnewswire.com", "globenewswire.com",
    "indeed.com", "monster.com", "ziprecruiter.com", "wellfound.com",
    "dnb.com", "owler.com", "similarweb.com", "craft.co",
    "trustpilot.com", "yelp.com", "bbb.org", "angel.co",
    "signalhire.com", "rocketreach.co", "apollo.io",
    "sec.gov", "opencorporates.com", "companieshouse.gov.uk",
    "ko-fi.com", "patreon.com", "gofundme.com",
})

# Common legal suffixes that are never part of the domain name
_STOP_WORDS: frozenset[str] = frozenset({
    "inc", "llc", "ltd", "corp", "co", "company", "group", "holdings",
    "the", "and", "of", "for", "technologies", "technology",
    "solutions", "services", "international", "global", "enterprises",
})


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _is_junk(url: str) -> bool:
    url_lower = url.lower()
    return any(j in url_lower for j in JUNK_DOMAINS)


def _domain_from_url(url: str) -> str:
    """Return bare domain (no scheme, no www, no path)."""
    d = re.sub(r"^https?://", "", url.lower())
    d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].split("?")[0]


def _root_domain(url: str) -> str:
    """
    Extract the registrable root domain (eTLD+1).
    techcommunity.microsoft.com → microsoft.com
    aboutamazon.com             → aboutamazon.com
    """
    full = _domain_from_url(url)
    parts = full.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else full


def _homepage(root: str) -> str:
    """Return clean https homepage for a root domain (no www prefix)."""
    clean = re.sub(r"^www\.", "", root)
    return f"https://{clean}/"


# ---------------------------------------------------------------------------
# Phase 1 – Direct probe
# ---------------------------------------------------------------------------

def _company_words(company_name: str) -> list[str]:
    """
    Split company name into lowercase words, dropping stop words.
    Splits on whitespace, slashes, commas AND hyphens so 'Coca-Cola' → ['coca','cola'].
    Preserves short tokens like 'ibm', 'hp', '3m'.
    """
    raw = re.split(r"[\s/\\,\-]+", company_name.strip())
    words = []
    for w in raw:
        w_clean = re.sub(r"[^a-z0-9]", "", w.lower())
        if w_clean and w_clean not in _STOP_WORDS:
            words.append(w_clean)
    return words


def _dot_com_candidates(company_name: str) -> list[str]:
    """
    Generate .com-only domain candidates for the probe phase.
    Non-.com TLDs are skipped to avoid accepting parked/squatted domains
    (which often respond 200 on .io/.ai/.net but are not the real company site).
    """
    words = _company_words(company_name)
    if not words:
        return []

    seen: set[str] = set()
    out: list[str] = []

    def add(d: str) -> None:
        if d and d not in seen:
            seen.add(d)
            out.append(d)

    # Concatenated: generalelectric.com, amazon.com
    add("".join(words) + ".com")
    # Hyphenated: general-electric.com, coca-cola.com
    if len(words) > 1:
        add("-".join(words) + ".com")
    # Abbreviation: ge.com, ibm.com, hp.com
    if 2 <= len(words) <= 5:
        add("".join(w[0] for w in words) + ".com")
    # First word only (for "Amazon Inc" → amazon.com already covered above)
    if len(words) > 1:
        add(words[0] + ".com")

    return out


def _extract_title(html: str) -> str:
    """Extract the <title> tag value from HTML, stripped of whitespace."""
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _probe_and_verify(url: str, words: list[str]) -> tuple[str, str] | None:
    """
    GET a URL, follow redirects, and verify the page title mentions the company.
    Returns (final_url, page_title) on success, None if unreachable or unrelated.

    Title check guards against parked domains that respond 200 with generic content.
    """
    try:
        resp = requests.get(
            url,
            timeout=PROBE_TIMEOUT,
            allow_redirects=True,
            headers=PROBE_HEADERS,
        )
        if resp.status_code >= 400:
            return None

        title = _extract_title(resp.text)
        title_lower = title.lower()

        # For multi-word companies ALL key words must appear in the title —
        # this prevents "general.com" matching "General Electric" just because
        # "general" is a common English word on that page.
        # For single-word companies, one match is sufficient.
        key_words = [w for w in words if len(w) > 1]
        if len(key_words) >= 2:
            matched = sum(1 for w in key_words if w in title_lower)
            if matched < len(key_words):
                log.debug("Title mismatch for %s (need %d words, got %d, title: %s)",
                          url, len(key_words), matched, title[:60])
                return None
        elif key_words:
            if not any(w in title_lower for w in key_words):
                log.debug("Title mismatch for %s (title: %s)", url, title[:60])
                return None

        return str(resp.url), title
    except Exception:
        return None


def _probe(url: str) -> str | None:
    """Lightweight HEAD probe — just checks reachability, no content verification."""
    for method in ("HEAD", "GET"):
        try:
            resp = requests.request(
                method, url,
                timeout=PROBE_TIMEOUT,
                allow_redirects=True,
                headers=PROBE_HEADERS,
            )
            if resp.status_code < 400:
                return str(resp.url)
        except Exception:
            continue
    return None


def _find_by_probe(company_name: str) -> SearchResult | None:
    """
    Phase 1: construct plausible .com domain variants and GET-probe them.

    Only accepts a candidate if the page title contains a company word —
    this filters out parked/squatted domains that return HTTP 200 with
    unrelated placeholder content.

    Returns the highest-scoring confirmed candidate, or None.
    """
    words = _company_words(company_name)
    candidates = _dot_com_candidates(company_name)
    confirmed: list[tuple[int, str, str]] = []  # (score, root, title)

    for domain in candidates:
        for url in (f"https://www.{domain}/", f"https://{domain}/"):
            result = _probe_and_verify(url, words)
            if not result:
                continue
            final_url, title = result
            if _is_junk(final_url):
                continue

            final_root = _root_domain(final_url)
            score = _score_root(final_root, title, words)
            confirmed.append((score, final_root, title))
            log.debug("Probe verified: %s → %s (score %d, title: %s)", url, final_root, score, title[:50])
            break  # both url prefixes target the same domain — stop after first hit

    if not confirmed:
        return None

    confirmed.sort(key=lambda x: (-x[0], len(x[1])))
    best_score, best_root, best_title = confirmed[0]
    log.info("Phase 1 (probe) winner: %s (score %d)", best_root, best_score)
    return SearchResult(title=best_title, url=_homepage(best_root), snippet="")


# ---------------------------------------------------------------------------
# Phase 2 – Search + score
# ---------------------------------------------------------------------------

def _score_root(root_domain: str, title: str, words: list[str]) -> int:
    """Score a root domain for likelihood of being the official company website."""
    bare = root_domain.rsplit(".", 1)[0]
    bare = re.sub(r"^www\.", "", bare)
    title_lower = title.lower()
    score = 0

    if words:
        # Exact match: primary company word IS the bare root domain
        if bare == words[0]:
            score += 16

        # All clean words concatenated match the bare domain (e.g. "generalelectric")
        elif "".join(words) == bare:
            score += 14

        # Hyphenated version matches (e.g. "general-electric")
        elif "-".join(words) == bare:
            score += 14

        # Abbreviation matches (e.g. "ge" for ["general","electric"])
        elif len(words) >= 2 and "".join(w[0] for w in words) == bare:
            score += 10

        # Partial: primary company word appears inside the bare domain
        elif words[0] in bare:
            score += 8

        # Extra words from multi-word names appear in bare domain
        for w in words[1:]:
            if len(w) > 2 and w in bare:
                score += 3

    # Preferred TLDs
    tld = root_domain.rsplit(".", 1)[-1] if "." in root_domain else ""
    if tld in ("com", "io", "co", "ai", "app", "dev"):
        score += 4
    elif tld in ("net", "org", "tech", "solutions", "agency"):
        score += 2

    # Company words in page title (strong signal for abbreviated-domain companies)
    word_matches = sum(1 for w in words if len(w) > 2 and w in title_lower)
    score += min(word_matches * 3, 9)  # up to +9 from title matches

    return score


def _ddgs_search(query: str, max_results: int = 10) -> list[SearchResult]:
    """Run a single DuckDuckGo query, returns empty list on any failure."""
    if DDGS is None:
        return []
    try:
        with DDGS() as ddgs:
            return [
                SearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", r.get("url", "")),
                    snippet=r.get("body", r.get("snippet", "")),
                )
                for r in ddgs.text(query, max_results=max_results)
            ]
    except Exception as e:
        log.debug("DuckDuckGo query failed (%s): %s", query, e)
        return []


def search(query: str, max_results: int = 5) -> list[SearchResult]:
    """Public search helper used elsewhere in the codebase."""
    return _ddgs_search(query, max_results=max_results)


def _find_by_search(company_name: str, industry: str | None = None) -> dict[str, tuple[int, str, str]]:
    """
    Phase 2: run multiple DuckDuckGo strategies, score root domains.
    Returns {root_domain: (score, title, snippet)}.
    Retries once (with a short backoff) if all strategies return empty results.
    """
    words = _company_words(company_name)

    strategies = [
        f'"{company_name}" official website',
        f"{company_name} official site",
        f"{company_name} homepage",
        f"{company_name} company",
    ]
    if industry:
        strategies.insert(1, f"{company_name} {industry} official website")

    best_by_root: dict[str, tuple[int, str, str]] = {}
    total_results = 0

    for attempt in range(2):  # retry once on empty
        for query in strategies:
            results = _ddgs_search(query, max_results=10)
            total_results += len(results)

            for r in results:
                if not r.url or _is_junk(r.url):
                    continue
                root = _root_domain(r.url)
                score = _score_root(root, r.title, words)
                if score <= 0:
                    continue
                if root not in best_by_root or score > best_by_root[root][0]:
                    best_by_root[root] = (score, r.title, r.snippet)

            # Stop early only on very confident exact hit
            if best_by_root:
                top = max(s for s, _, _ in best_by_root.values())
                if top >= 16:
                    return best_by_root

        if total_results > 0:
            break  # got real results, no need to retry

        if attempt == 0:
            log.warning("DuckDuckGo returned empty results — retrying in 2s...")
            time.sleep(2)

    if total_results == 0:
        log.warning("DuckDuckGo returned no results for '%s' after retry.", company_name)

    return best_by_root


# ---------------------------------------------------------------------------
# Phase 3 – Verify
# ---------------------------------------------------------------------------

def _verify(url: str) -> bool:
    """Quick HTTP check that a URL is actually reachable (not 404/500)."""
    final = _probe(url)
    return final is not None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_official_website(company_name: str, industry: str | None = None) -> SearchResult | None:
    """
    Find the official website for a company — bulletproof three-phase approach.

    Phase 1 – Direct probe  : Constructs domain candidates (concatenated, hyphenated,
                               abbreviation) and probes them via HTTP. Follows redirects.
                               Returns immediately on a confirmed hit.
    Phase 2 – Search + score: Runs DuckDuckGo with multiple strategies, scores each
                               root domain by name + title signals, retries on rate-limit.
    Phase 3 – Verify        : Confirms the search winner is accessible. Tries next-best
                               candidates if the top pick is a dead URL.

    Wikipedia and all directory/aggregator sites are hard-blocked throughout.
    Returns None only if all three phases find nothing.
    """
    if DDGS is None:
        raise ImportError("Install ddgs: pip install ddgs")

    words = _company_words(company_name)
    log.info("Finding official website for: '%s' (words: %s)", company_name, words)

    # ------------------------------------------------------------------
    # Phase 1 – Direct probe
    # ------------------------------------------------------------------
    probe_result = _find_by_probe(company_name)
    if probe_result:
        probe_score = _score_root(_root_domain(probe_result.url), "", words)
        # High-confidence probe hit (exact domain match) — return immediately
        if probe_score >= 14:
            log.info("Phase 1 confident hit: %s", probe_result.url)
            return probe_result
        # Low-confidence probe hit — keep it as fallback, continue to search
        log.debug("Phase 1 low-confidence hit (%d): %s — continuing to search.", probe_score, probe_result.url)

    # ------------------------------------------------------------------
    # Phase 2 – Search + score
    # ------------------------------------------------------------------
    by_root = _find_by_search(company_name, industry=industry)

    if not by_root:
        log.warning("Phase 2 returned no candidates. Using probe fallback if available.")
        return probe_result  # may be None

    # Sort candidates: descending score, then ascending domain length (tiebreak)
    ranked = sorted(by_root.items(), key=lambda kv: (-kv[1][0], len(kv[0])))

    # ------------------------------------------------------------------
    # Phase 3 – Verify top candidates
    # ------------------------------------------------------------------
    for root, (score, title, snippet) in ranked[:5]:  # check up to top 5
        url = _homepage(root)
        # Very high-confidence: exact domain match found by search engine — trust it
        # without a live HTTP probe (site may block bot probes: SAP, Salesforce, etc.)
        if score >= 20:
            log.info("Phase 2 high-confidence winner: %s (score %d, title: %s)", url, score, title[:60])
            return SearchResult(title=title, url=url, snippet=snippet)
        log.debug("Phase 3 verifying: %s (score %d)", url, score)
        if _verify(url):
            log.info("Phase 2+3 winner: %s (score %d, title: %s)", url, score, title[:60])
            return SearchResult(title=title, url=url, snippet=snippet)
        log.debug("Verification failed for %s — trying next.", url)

    # All search candidates failed verification — fall back to probe result
    log.warning("All search candidates failed verification. Using probe fallback.")
    return probe_result
