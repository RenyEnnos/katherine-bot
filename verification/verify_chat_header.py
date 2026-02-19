from playwright.sync_api import sync_playwright, expect
import os

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page()

    # Assuming frontend is running on 3000
    page.goto("http://localhost:3000")

    # Wait for the trash icon to be visible
    trash_button = page.get_by_label("Limpar conversa")
    expect(trash_button).to_be_visible()

    # Click trash icon
    trash_button.click()

    # Verify confirmation dialog
    confirm_button = page.get_by_label("Confirmar limpeza")
    cancel_button = page.get_by_label("Cancelar")
    expect(confirm_button).to_be_visible()
    expect(cancel_button).to_be_visible()

    # Verify focus is on Cancel button (autoFocus)
    page.wait_for_timeout(100) # Give React a moment to focus
    is_cancel_focused = page.evaluate("document.activeElement === document.querySelector('button[aria-label=\"Cancelar\"]')")
    print(f"Is Cancel focused? {is_cancel_focused}")

    # Take screenshot of confirmation state
    # We want to verify the visual style (focus ring, layout)
    page.screenshot(path="verification/verification_confirm.png")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
