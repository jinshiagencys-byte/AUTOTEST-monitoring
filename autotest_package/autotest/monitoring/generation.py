"""Phase A orchestration. Imported only by explicit generation commands."""

from .runtime import check_blocked, origin
from .store import now


def generate_site(store, site_url, generator, max_depth=2, pages=None):
    site_origin = origin(site_url)
    if pages is None:
        # Check the landing page before crawling a challenge page.
        generator.driver.get(site_url)
        check_blocked(generator.driver)
        pages = generator.url_extractor.extract_urls(site_url, max_depth=max_depth)
    pages = sorted(set(pages))
    if not pages:
        raise ValueError("Crawl returned no pages; no scripts replaced")
    report = {"site_url": site_url, "generated_at": now(), "published": [], "errors": []}
    for page_url in pages:
        try:
            if origin(page_url) != site_origin:
                raise ValueError("Page is outside the monitored origin")
            source, analysis = generator.generate_monitoring_page(page_url)
            record = store.publish(site_url, page_url, source, analysis, generator.llm.provider)
            report["published"].append(record)
        except Exception as exc:
            # Never replace working versions with a failed/empty generation.
            report["errors"].append({"page_url": page_url, "error": str(exc)})
    return report