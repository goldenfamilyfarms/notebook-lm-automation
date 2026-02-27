"""Packt companion eBook claim and download automation.

Navigates to https://www.packtpub.com/page/companion-ebook, selects
"Humble Bundle" as the purchase source, searches each book title, expands
the "Upload Purchase Proof" section, uploads the invoice PDF, then
downloads the resulting eBook PDF to the Downloads folder.

Usage (LOCAL):
    python -m notebooklm_automation.packt_claim \
        --invoice "C:/Users/derri/notebooklm/packt_invoice_198NcCVCPTmQ4Jcv.pdf"

Requirements:
    - Same persistent Chrome profile as the NotebookLM automation
    - Invoice PDF must exist at the given path
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page, async_playwright

from notebooklm_automation.config import DEFAULT_DOWNLOADS_DIR, DEFAULT_USER_DATA_DIR
from notebooklm_automation.pdf_splitter import sanitize_filename

logger = logging.getLogger(__name__)

PACKT_CLAIM_URL = "https://www.packtpub.com/en-us/unlock"

TITLES: list[str] = [
    # Advanced Python & Core Development
    "Expert Python Programming",
    "Advanced Python Programming",
    "Modern Python Cookbook",
    "Python Architecture Patterns",
    "CPython Internals",
    "Robust Python",
    "Clean Code in Python",
    "Python High Performance",
    "Mastering Python Networking",
    "Python for Geeks",
    # Data Structures, Algorithms, & C++
    "Data Structures and Algorithms with the C++ STL",
    "C++ Data Structures and Algorithm Design Principles",
    "50 Algorithms Every Programmer Should Know",
    "Modern C++ Programming Cookbook",
    "C++ High Performance",
    "C++ Memory Management",
    "Asynchronous Programming with C++",
    "Advanced C++ Programming Cookbook",
    "Modern CMake for C++",
    "Debunking C++ Myths",
    # SRE, DevOps, & Kubernetes
    "The Kubernetes Bible",
    "Mastering Terraform",
    "The Kubernetes Operator Framework Book",
    "Automating DevOps with GitLab CI/CD Pipelines",
    "The Ultimate Docker Container Book",
    "Site Reliability Engineering with Azure",
    "Cloud Native DevOps with Kubernetes",
    "DevSecOps for Azure",
    "Continuous Testing, Quality, Security, and Feedback",
    "Kubernetes Cookbook",
    "AWS DevOps Simplified",
    # System Design & Solutions Architecture
    "Solutions Architect's Handbook",
    "AWS for Solutions Architects",
    "Design Microservices Architecture with Patterns",
    "Software Architecture with C# 12 and .NET 8",
    "Clean Architecture with .NET",
    "Cloud Architecture Patterns",
    "Building Event-Driven Microservices",
    "Hands-On High Performance with Go",
    "The Software Architect's Guide to AI",
    "Modernizing Legacy Applications",
    # Observability & Monitoring
    "Observability with Grafana",
    "Mastering Distributed Tracing",
    "Monitoring Cloud-Native Applications",
    "Cloud Observability with OpenTelemetry",
    "Grafana Dashboards Cookbook",
    "Hands-On Infrastructure Monitoring with Prometheus",
    "Logging in Action with Fluentd and Loki",
    "Performance Monitoring with Grafana Pyroscope",
    "AIOps with Grafana",
    "Service Level Objectives (SLOs) with Grafana",
    # Agentic AI & Distributed Systems
    "The Agentic AI Handbook",
    "Agentic AI Systems",
    "Agentic LLM Architectures for Developers",
    "Building Agentic AI Systems",
    "Big Data on Kubernetes",
    "Generative AI with LangChain",
    "Mastering Distributed Computing with Go",
    "Autonomous AI Agents with AutoGPT",
    "Vector Databases for AI",
    "Multi-Agent Systems with LLMs",
    # Computer Architecture
    "Modern Computer Architecture and Organization",
    "Digital Logic Design and Computer Organization",
    "RISC-V Assembly Language Programming",
    "Hardware Security with FPGA",
    "Quantum Computing Architecture",
    # TypeScript & React
    "Modern Full-Stack React Projects",
    "React 18 Design Patterns and Best Practices",
    "Advanced TypeScript Programming Projects",
    "Mastering TypeScript",
    "Building Micro Frontends with React 18",
    "React and React Native",
    "Full-Stack React, TypeScript, and Node",
    "Next.js 14 Cookbook",
    "Testing React Applications",
]


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )


async def ensure_packt_signed_in(page: Page) -> None:
    """Navigate to the claim page and sign in to Packt once if needed.

    Uses the persistent Chrome profile so subsequent runs skip this step.
    """
    await page.goto(PACKT_CLAIM_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(2_000)

    try:
        signin_btn = (
            page.get_by_role("button", name="Sign in with Google")
            .or_(page.get_by_role("link", name="Sign in with Google"))
            .or_(page.locator("button:has-text('Sign in with Google')"))
        )
        if await signin_btn.first.is_visible(timeout=3_000):
            logger.info("Packt sign-in required — clicking 'Sign in with Google'")
            await signin_btn.first.click()
            input(
                "\n>>> Please complete Packt sign-in in the browser window, "
                "then press ENTER here to continue... "
            )
            await page.wait_for_load_state("domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(2_000)
            logger.info("Packt sign-in complete")
        else:
            logger.info("Already signed in to Packt")
    except Exception:
        logger.info("Packt sign-in check skipped (already authenticated)")


async def claim_title(
    page: Page,
    title: str,
    invoice_path: Path,
    downloads_dir: Path,
) -> Path | None:
    """Claim one title and download the PDF. Returns the downloaded Path or None.

    Flow (matches actual Packt UI at /en-us/unlock):
      1. Navigate to unlock page
      2. Type title in search box, wait for dropdown, click best match
      3. Click "Continue to Step 2"
      4. Click "Humble Bundle" radio button
      5. Set file input to invoice PDF, wait for "Invoice uploaded" confirmation
      6. Click "Unlock Benefits"
      7. Wait for success / download link, trigger download
    """
    logger.info("Claiming: %s", title)

    try:
        await page.goto(PACKT_CLAIM_URL, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(2_000)
    except Exception as exc:
        logger.error("Failed to load claim page: %s", exc)
        return None

    # --- Step 1: Type title into search box, press Enter, click first dropdown result ---
    try:
        search_box = page.locator("input#search-product").first
        await search_box.wait_for(state="visible", timeout=10_000)
        await search_box.click()
        await search_box.fill(title)
        await page.keyboard.press("Enter")
        # Wait for dropdown results to appear
        await page.wait_for_timeout(1_500)

        # Click the first item in the dropdown list
        first_result = page.locator(
            "ul#search-product-results li.search-results-list-item a.search-results-list-item-link"
        ).first
        await first_result.wait_for(state="visible", timeout=8_000)
        await first_result.click()
        await page.wait_for_timeout(1_500)
        logger.debug("Selected first dropdown result for: %s", title)
    except Exception as exc:
        logger.error("Could not find/select title '%s': %s", title, exc)
        return None

    # --- Step 2: Click "Continue to Step 2" ---
    try:
        # After clicking a result the page navigates to /en-us/unlock/<isbn>?step=1
        await page.wait_for_url("**/unlock/**", timeout=10_000)

        continue_btn = page.locator("button.cta-action").filter(
            has_text="CONTINUE TO STEP 2"
        ).or_(
            page.locator("a.cta-action").filter(has_text="CONTINUE TO STEP 2")
        ).first
        await continue_btn.wait_for(state="visible", timeout=15_000)
        await continue_btn.click()
        await page.wait_for_timeout(1_500)
        logger.debug("Clicked 'Continue to Step 2' for: %s", title)
    except Exception as exc:
        logger.error("Could not click 'Continue to Step 2' for '%s': %s", title, exc)
        return None

    # --- Step 3: Select "Humble Bundle" radio button ---
    try:
        humble_radio = page.locator("label:has-text('Humble Bundle'), input[value*='Humble' i]").first
        await humble_radio.wait_for(state="visible", timeout=8_000)
        await humble_radio.click()
        await page.wait_for_timeout(500)
        logger.debug("Selected Humble Bundle for: %s", title)
    except Exception as exc:
        logger.error("Could not select 'Humble Bundle' for '%s': %s", title, exc)
        return None

    # --- Step 4: Upload invoice PDF via file input ---
    try:
        file_input = page.locator("input[type='file']").first
        await file_input.set_input_files(str(invoice_path), timeout=10_000)

        # Wait for "Invoice uploaded." confirmation text
        try:
            await page.wait_for_selector(
                "text=Invoice uploaded.",
                timeout=15_000,
            )
            logger.debug("Invoice upload confirmed for: %s", title)
        except Exception:
            await page.wait_for_timeout(4_000)
    except Exception as exc:
        logger.error("Could not upload invoice for '%s': %s", title, exc)
        return None

    # --- Step 5: Click "Unlock Benefits" ---
    try:
        unlock_btn = page.locator("button.cta-action").filter(has_text="UNLOCK BENEFITS").or_(
            page.locator("button:has-text('UNLOCK BENEFITS')")
        ).or_(
            page.get_by_role("button", name="Unlock Benefits", exact=False)
        )
        await unlock_btn.first.wait_for(state="visible", timeout=10_000)
        await unlock_btn.first.click()
        logger.info("Clicked 'Unlock Benefits' for: %s", title)
    except Exception as exc:
        logger.error("Could not click 'Unlock Benefits' for '%s': %s", title, exc)
        return None

    # --- Step 6: Wait for redirect to /my-account/orders then download PDF ---
    try:
        await page.wait_for_url("**/my-account/orders**", timeout=30_000)
        await page.wait_for_timeout(1_500)

        # Dismiss cookie banner if present
        try:
            cookie_btn = page.locator("button:has-text('Allow all')").first
            if await cookie_btn.is_visible(timeout=2_000):
                await cookie_btn.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass

        # Find the DOWNLOAD PDF button for this specific title.
        # The orders page lists all books — find the one matching our title,
        # then click its DOWNLOAD PDF button.
        # Strategy: look for a book card containing the title text, then find
        # the DOWNLOAD PDF button within that card.
        async with page.expect_download(timeout=60_000) as dl_info:
            # Try scoped click first — find card containing title text
            try:
                card = page.locator(
                    f"div:has-text('{title[:30]}')"
                ).filter(
                    has=page.locator("button:has-text('DOWNLOAD PDF'), a:has-text('DOWNLOAD PDF')")
                ).first
                await card.locator(
                    "button:has-text('DOWNLOAD PDF'), a:has-text('DOWNLOAD PDF')"
                ).first.click(timeout=10_000)
            except Exception:
                # Fallback: click the first DOWNLOAD PDF on the page
                # (the most recently claimed book is at the top)
                await page.locator(
                    "button:has-text('DOWNLOAD PDF'), a:has-text('DOWNLOAD PDF')"
                ).first.click(timeout=10_000)

        download = await dl_info.value
        safe_title = sanitize_filename(title)
        dest = downloads_dir / f"{safe_title}.pdf"
        await download.save_as(str(dest))
        logger.info("Downloaded: %s → %s", title, dest)
        return dest
    except Exception as exc:
        logger.error("Could not download PDF for '%s': %s", title, exc)
        return None


async def run(
    invoice_path: Path,
    user_data_dir: Path,
    downloads_dir: Path,
) -> dict[str, Path]:
    """Claim and download all titles. Returns {title: pdf_path} for successes."""
    invoice_path = invoice_path.expanduser().resolve()
    if not invoice_path.exists():
        logger.error("Invoice PDF not found: %s", invoice_path)
        return {}

    downloads_dir.mkdir(parents=True, exist_ok=True)

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=False,
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.pages[0] if context.pages else await context.new_page()

    results: dict[str, Path] = {}
    failed: list[str] = []

    # Sign in to Packt once — session persists via the Chrome profile
    await ensure_packt_signed_in(page)

    for title in TITLES:
        pdf_path = await claim_title(page, title, invoice_path, downloads_dir)
        if pdf_path:
            results[title] = pdf_path
        else:
            failed.append(title)

    await context.close()
    await pw.stop()

    logger.info("Done. %d downloaded, %d failed.", len(results), len(failed))
    if failed:
        logger.warning("Failed titles: %s", ", ".join(failed))

    return results


def main() -> None:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Claim and download Packt companion eBooks")
    parser.add_argument(
        "--invoice",
        type=Path,
        default=Path("C:/Users/derri/notebooklm/packt_invoice_198NcCVCPTmQ4Jcv.pdf"),
        help="Path to the Packt invoice PDF",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=DEFAULT_USER_DATA_DIR,
        help="Chromium profile directory",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=DEFAULT_DOWNLOADS_DIR,
        help="Directory to save downloaded PDFs",
    )
    args = parser.parse_args()
    asyncio.run(run(args.invoice, args.user_data_dir, args.downloads_dir))


if __name__ == "__main__":
    main()
