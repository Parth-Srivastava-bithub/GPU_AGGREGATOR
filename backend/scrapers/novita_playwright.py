from playwright.sync_api import sync_playwright
from time import sleep

chrome_url = "http://127.0.0.1:9222"


def parse_gpu_availability(text: str):

    if "Data Center GPU Availability" in text:
        text = text.split("Data Center GPU Availability", 1)[1]

    if "*Volume Name" in text:
        text = text.split("*Volume Name", 1)[0]

    lines = [x.strip() for x in text.splitlines() if x.strip()]

    available = []
    unavailable = []

    current = None

    for line in lines:

        if line == "Available":
            current = "available"
            continue

        if line == "None":
            current = "unavailable"
            continue

        if current == "available":
            available.append(line)

        elif current == "unavailable":
            unavailable.append(line)

    return {
        "available": available,
        "unavailable": unavailable
    }


def scrape_novita_datacenters():

    results = []

    with sync_playwright() as p:

        browser = p.chromium.connect_over_cdp(chrome_url)
        context = browser.contexts[0]

        page = next(
            pg for pg in context.pages
            if "novita.ai/gpus-console/storage" in pg.url
        )

        dialog = page.locator('[role="dialog"]')

        cards = page.locator("span.addNetworkVolume_dataCenterItem__lcduA")

        for i in range(cards.count()):

            card = page.locator(
                "span.addNetworkVolume_dataCenterItem__lcduA"
            ).nth(i)

            name = card.locator(
                "div.addNetworkVolume_dataCenterName__HSF3V"
            ).inner_text()

            card.click(force=True)

            page.wait_for_timeout(1000)

            if not card.locator("img[src*='checked']").count():
                continue

            parsed = parse_gpu_availability(dialog.inner_text())

            results.append({
                "cluster": name,
                "available": parsed["available"],
                "unavailable": parsed["unavailable"]
            })

    return results

def __beta__scrape_novita_datacenters():

    results = []

    with sync_playwright() as p:

        browser = p.chromium.connect_over_cdp(chrome_url)
        context = browser.contexts[0]

        page = next(
            pg for pg in context.pages
            if "novita.ai/gpus-console/storage" in pg.url
        )

        dialog = page.locator('[role="dialog"]')
        cards = page.locator("span.addNetworkVolume_dataCenterItem__lcduA")

        for i in range(cards.count()):

            # Fresh locator after any re-render
            card = page.locator(
                "span.addNetworkVolume_dataCenterItem__lcduA"
            ).nth(i)

            card.scroll_into_view_if_needed()

            name = card.locator(
                "div.addNetworkVolume_dataCenterName__HSF3V"
            ).inner_text()

            before = dialog.inner_text()

            card.click()

            # Wait until dialog content changes, with a timeout fallback
            try:
                page.wait_for_function(
                    """([selector, previous]) => {
                        const el = document.querySelector(selector);
                        return el && el.innerText !== previous;
                    }""",
                    arg=["[role='dialog']", before],
                    timeout=3000,
                )
            except Exception:
                # Some clusters don't change; continue with current content
                pass

            parsed = parse_gpu_availability(dialog.inner_text())

            results.append({
                "cluster": name,
                "available": parsed["available"],
                "unavailable": parsed["unavailable"]
            })

            # Small pause to reduce load on the site
            sleep(0.5)

    return results