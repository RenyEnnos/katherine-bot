from playwright.sync_api import sync_playwright, expect
import os
import time

def test_copy_functionality(page):
    print("Navigating to page...")
    page.goto("http://localhost:3000")

    print("Waiting for content...")
    expect(page.get_by_text("Here is some code")).to_be_visible()

    print("Hovering...")
    # Hover over the container to trigger group-hover
    # The message bubble is inside a group container.
    # We can hover the text.
    page.get_by_text("Here is some code").hover()

    # Wait a bit for transition
    time.sleep(0.5)

    copy_button = page.get_by_label("Copiar mensagem")

    print("Clicking copy button...")
    copy_button.click()

    print("Verifying feedback...")
    expect(page.get_by_label("Copiado para área de transferência")).to_be_visible()
    expect(page.get_by_text("Copiado!")).to_be_visible()

    print("Taking screenshot...")
    page.screenshot(path="frontend/verification_copy.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        try:
            test_copy_functionality(page)
            print("Verification passed!")
        except Exception as e:
            print(f"Verification failed: {e}")
            page.screenshot(path="frontend/verification_failed.png")
            raise
        finally:
            browser.close()
