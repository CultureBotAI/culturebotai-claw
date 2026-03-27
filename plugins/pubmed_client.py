"""
PubMed Client Plugin

Provides citation validation and abstract fetching via NCBI E-utilities API.

Features:
- PMID validation (verify PMID exists)
- Abstract fetching
- Snippet verification (check if snippet appears in abstract)
- Rate limiting (NCBI: 3 req/sec with API key, 1 req/sec without)
- Caching to reduce API calls

NCBI E-utilities Documentation:
https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, List
from urllib.parse import quote
import requests
from pathlib import Path
import json

logger = logging.getLogger(__name__)


@dataclass
class PubMedArticle:
    """PubMed article metadata."""
    pmid: str
    title: str
    abstract: str
    authors: List[str]
    journal: str
    year: str
    doi: Optional[str] = None


@dataclass
class CitationValidationResult:
    """Result of citation validation."""
    pmid: str
    valid: bool
    article: Optional[PubMedArticle]
    snippet_found: bool = False
    snippet_score: float = 0.0  # 0.0-1.0
    error: Optional[str] = None


class PubMedClient:
    """
    Client for PubMed E-utilities API.

    Provides citation validation and abstract fetching with rate limiting and caching.
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        tool: str = "culturebotai-claw",
        cache_dir: Optional[Path] = None,
        rate_limit_delay: float = 0.34  # ~3 req/sec with API key
    ):
        """
        Initialize PubMed client.

        Args:
            api_key: NCBI API key (optional, increases rate limit)
            email: Contact email (required by NCBI)
            tool: Tool name for NCBI tracking
            cache_dir: Directory for caching responses
            rate_limit_delay: Delay between requests (seconds)
        """
        self.api_key = api_key
        self.email = email or "culturebot@example.com"
        self.tool = tool
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0.0

        # Setup cache
        self.cache_dir = cache_dir
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)
            self.cache_file = cache_dir / "pubmed_cache.json"
            self._load_cache()
        else:
            self.cache = {}

    def _load_cache(self):
        """Load cache from disk."""
        if self.cache_file and self.cache_file.exists():
            try:
                with open(self.cache_file) as f:
                    self.cache = json.load(f)
                logger.info(f"Loaded {len(self.cache)} cached PubMed entries")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")
                self.cache = {}
        else:
            self.cache = {}

    def _save_cache(self):
        """Save cache to disk."""
        if self.cache_file:
            try:
                with open(self.cache_file, 'w') as f:
                    json.dump(self.cache, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to save cache: {e}")

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self.last_request_time = time.time()

    def _build_params(self, **kwargs) -> Dict[str, str]:
        """Build common API parameters."""
        params = {
            "tool": self.tool,
            "email": self.email,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        params.update(kwargs)
        return params

    def fetch_article(self, pmid: str, use_cache: bool = True) -> Optional[PubMedArticle]:
        """
        Fetch article metadata and abstract from PubMed.

        Args:
            pmid: PubMed ID (with or without "PMID:" prefix)
            use_cache: Use cached result if available

        Returns:
            PubMedArticle or None if not found
        """
        # Normalize PMID
        pmid = pmid.replace("PMID:", "").strip()

        # Check cache
        if use_cache and pmid in self.cache:
            logger.debug(f"Cache hit for PMID:{pmid}")
            cached = self.cache[pmid]
            if cached is None:
                return None
            return PubMedArticle(**cached)

        # Rate limit
        self._rate_limit()

        # Fetch from EFetch
        try:
            url = f"{self.BASE_URL}/efetch.fcgi"
            params = self._build_params(
                db="pubmed",
                id=pmid,
                retmode="xml",
                rettype="abstract"
            )

            logger.debug(f"Fetching PMID:{pmid} from PubMed")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            # Parse XML (basic parsing, could use lxml for robustness)
            xml = response.text

            # Extract fields (simplified parsing)
            article = self._parse_article_xml(pmid, xml)

            # Cache result
            if article:
                self.cache[pmid] = {
                    "pmid": article.pmid,
                    "title": article.title,
                    "abstract": article.abstract,
                    "authors": article.authors,
                    "journal": article.journal,
                    "year": article.year,
                    "doi": article.doi
                }
            else:
                self.cache[pmid] = None

            self._save_cache()
            return article

        except Exception as e:
            logger.error(f"Failed to fetch PMID:{pmid}: {e}")
            # Cache failures to avoid repeated attempts
            self.cache[pmid] = None
            self._save_cache()
            return None

    def _parse_article_xml(self, pmid: str, xml: str) -> Optional[PubMedArticle]:
        """
        Parse article metadata from PubMed XML.

        This is a simplified parser. For production, consider using lxml or xmltodict.
        """
        try:
            # Check if article exists
            if "<PubmedArticle>" not in xml:
                logger.warning(f"PMID:{pmid} not found in PubMed")
                return None

            # Extract title
            title = self._extract_xml_field(xml, "ArticleTitle")

            # Extract abstract
            abstract_parts = []
            # Look for AbstractText tags
            import re
            abstract_matches = re.findall(r'<AbstractText[^>]*>(.*?)</AbstractText>', xml, re.DOTALL)
            abstract = " ".join(abstract_matches) if abstract_matches else ""

            # Extract authors
            author_matches = re.findall(r'<LastName>(.*?)</LastName>', xml)
            authors = author_matches[:3]  # First 3 authors

            # Extract journal
            journal = self._extract_xml_field(xml, "Title")  # Journal title

            # Extract year
            year_match = re.search(r'<PubDate>.*?<Year>(\d{4})</Year>', xml, re.DOTALL)
            year = year_match.group(1) if year_match else "Unknown"

            # Extract DOI
            doi_match = re.search(r'<ArticleId IdType="doi">(.*?)</ArticleId>', xml)
            doi = doi_match.group(1) if doi_match else None

            return PubMedArticle(
                pmid=pmid,
                title=title or "Unknown",
                abstract=abstract,
                authors=authors,
                journal=journal or "Unknown",
                year=year,
                doi=doi
            )

        except Exception as e:
            logger.error(f"Failed to parse XML for PMID:{pmid}: {e}")
            return None

    def _extract_xml_field(self, xml: str, tag: str) -> str:
        """Extract field from XML by tag name."""
        import re
        match = re.search(f'<{tag}[^>]*>(.*?)</{tag}>', xml, re.DOTALL)
        return match.group(1).strip() if match else ""

    def validate_citation(
        self,
        pmid: str,
        snippet: Optional[str] = None,
        medium_name: Optional[str] = None
    ) -> CitationValidationResult:
        """
        Validate a citation and optionally verify snippet.

        Args:
            pmid: PubMed ID to validate
            snippet: Text snippet that should appear in abstract
            medium_name: Medium name that should be mentioned

        Returns:
            CitationValidationResult with validation details
        """
        pmid = pmid.replace("PMID:", "").strip()

        # Fetch article
        article = self.fetch_article(pmid)

        if not article:
            return CitationValidationResult(
                pmid=pmid,
                valid=False,
                article=None,
                error="PMID not found in PubMed"
            )

        # If no snippet to verify, just return valid
        if not snippet and not medium_name:
            return CitationValidationResult(
                pmid=pmid,
                valid=True,
                article=article
            )

        # Verify snippet
        snippet_found = False
        snippet_score = 0.0

        full_text = f"{article.title} {article.abstract}".lower()

        if snippet:
            snippet_lower = snippet.lower()
            # Check exact match
            if snippet_lower in full_text:
                snippet_found = True
                snippet_score = 1.0
            else:
                # Check partial match (>50% of words found)
                snippet_words = snippet_lower.split()
                found_words = sum(1 for word in snippet_words if word in full_text)
                snippet_score = found_words / len(snippet_words) if snippet_words else 0.0
                snippet_found = snippet_score >= 0.5

        # Check medium name mentioned
        if medium_name and not snippet_found:
            if medium_name.lower() in full_text:
                snippet_found = True
                snippet_score = max(snippet_score, 0.7)

        return CitationValidationResult(
            pmid=pmid,
            valid=True,
            article=article,
            snippet_found=snippet_found,
            snippet_score=snippet_score
        )

    def search_pubmed(
        self,
        query: str,
        max_results: int = 10
    ) -> List[str]:
        """
        Search PubMed and return PMIDs.

        Args:
            query: Search query
            max_results: Maximum results to return

        Returns:
            List of PMIDs
        """
        self._rate_limit()

        try:
            url = f"{self.BASE_URL}/esearch.fcgi"
            params = self._build_params(
                db="pubmed",
                term=query,
                retmax=max_results,
                retmode="json"
            )

            logger.debug(f"Searching PubMed: {query}")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            pmids = data.get("esearchresult", {}).get("idlist", [])

            logger.info(f"Found {len(pmids)} results for query: {query}")
            return pmids

        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            return []


# Singleton instance for reuse
_pubmed_client_instance = None


def get_pubmed_client(
    api_key: Optional[str] = None,
    cache_dir: Optional[Path] = None
) -> PubMedClient:
    """Get or create PubMed client singleton."""
    global _pubmed_client_instance

    if _pubmed_client_instance is None:
        _pubmed_client_instance = PubMedClient(
            api_key=api_key,
            cache_dir=cache_dir
        )

    return _pubmed_client_instance
