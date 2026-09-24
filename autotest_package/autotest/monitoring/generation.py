"""Phase A orchestration. Imported only by explicit generation commands."""

import os
from urllib.parse import urlsplit

from .runtime import check_blocked, origin
from .store import now


def _matches(page_url, env_name):
    """True si le chemin de l'URL contient un des motifs listés dans la variable d'env."""
    patterns = [p.strip().lower() for p in os.getenv(env_name, "").split(",") if p.strip()]
    path = urlsplit(page_url).path.lower()
    return any(p in path for p in patterns)


def fallback_page(generator, page_url):
    """Script minimal, sans LLM : ouvre la page et vérifie son titre (ou son URL finale)."""
    generator.driver.get(page_url)
    check_blocked(generator.driver)
    final_url = generator.driver.current_url
    if origin(final_url) != origin(page_url):
        raise ValueError("Page redirected outside the monitored origin")
    title = (generator.driver.title or "").strip()
    assertion = "ctx.assert_title(%r)" % title if title else "ctx.assert_url(%r)" % final_url
    source = "def run(ctx):\n    ctx.open(%r)\n    %s\n" % (page_url, assertion)
    analysis = {"fallback": True, "metadata": {"title": title, "url": page_url}, "test_cases": []}
    return source, analysis


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
    report = {"site_url": site_url, "generated_at": now(), "published": [],
              "fallbacks": [], "errors": []}
    for page_url in pages:
        if origin(page_url) != site_origin:
            report["errors"].append({"page_url": page_url,
                                     "error": "Page is outside the monitored origin"})
            continue
        already_published = page_url in store.manifest(site_url)["pages"]
        # Pages purement textuelles (MONITOR_SIMPLE_PAGES=legal,privacy,...) : pas de LLM.
        simple = _matches(page_url, "MONITOR_SIMPLE_PAGES")
        try:
            if simple:
                source, analysis = fallback_page(generator, page_url)
                provider = "fallback"
            else:
                source, analysis = generator.generate_monitoring_page(page_url)
                provider = generator.llm.provider
            record = store.publish(site_url, page_url, source, analysis, provider)
            report["published"].append(record)
        except Exception as exc:
            error = str(exc)
            # Never replace working versions with a failed/empty generation.
            if not already_published and not simple:
                try:
                    source, analysis = fallback_page(generator, page_url)
                    record = store.publish(site_url, page_url, source, analysis, "fallback")
                    report["published"].append(record)
                    report["fallbacks"].append({"page_url": page_url, "reason": error})
                    continue
                except Exception as fallback_exc:
                    error += " | fallback: " + str(fallback_exc)
            report["errors"].append({"page_url": page_url, "error": error})
    return report
