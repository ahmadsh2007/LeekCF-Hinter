class ScrapingValidationError(Exception):
    """Raised when scraped content fails strict validation requirements. Permanent: retrying will not help."""
    pass

class TransientScrapeError(Exception):
    """Raised when a page could not be fetched for a reason that may pass: network error, rate limit, challenge page."""
    pass
