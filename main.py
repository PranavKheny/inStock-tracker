import os
import re
import smtplib
from email.message import EmailMessage
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

# ====== Environment Variables ======
PRODUCT_URL = os.environ.get(
    "BUTTERMILK_PRODUCT_URL",
    "https://shop.amul.com/en/product/amul-high-protein-buttermilk-200-ml-or-pack-of-30",
)
PINCODE = os.environ.get("PINCODE", "560060")

# ====== Email Configuration ======
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "pranavkheny@gmail.com")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", "khenyaditya97@gmail.com")

# ====== State (ephemeral; consider Firestore/GCS for durability) ======
STATE_FILE = "/tmp/buttermilk_stock_status.txt"


def send_email_notification(product_name: str) -> None:
    """Sends an email notification."""
    try:
        msg = EmailMessage()
        msg["Subject"] = f"Stock Alert: {product_name} is back in stock!"
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECIPIENT_EMAIL
        msg.set_content(
            f"The product ({product_name}) is now in stock in Bangalore at: {PRODUCT_URL}\n\n"
            f"This is an automated notification. Please check the website to confirm."
        )

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        print("Email notification sent successfully.")
    except Exception as e:
        print(f"Failed to send email notification: {e}")


def _open_pincode_modal(page) -> None:
    """Ensure the 'Select Delivery Pincode' modal is open (robust to small copy/layout changes)."""
    # If it's already visible, we're done.
    if page.locator("text=/select delivery pincode/i").first.is_visible():
        return

    # Try a few header/link variants without throwing if missing
    candidates = ["Change Delivery Pincode", "Change Pincode", "Change Delivery Pin", "Deliver to"]
    for txt in candidates:
        el = page.get_by_text(txt, exact=False)
        if el.count() > 0:
            try:
                el.first.click()
                page.wait_for_selector("text=/select delivery pincode/i", timeout=5000)
                return
            except Exception:
                pass  # try the next variant

    # Fallback: try the "Get my location" button in the modal (may open/prime flow)
    loc_btn = page.get_by_role("button", name=re.compile("get my location", re.I))
    if loc_btn.count() > 0:
        try:
            loc_btn.first.click()
            page.wait_for_timeout(1500)
        except Exception:
            pass

    # One last short wait so subsequent queries can still succeed even if modal didn't appear
    page.wait_for_timeout(500)


def _enter_pincode(page, pincode: str) -> None:
    """Fill pincode into the modal input (or global field) and submit."""
    # Prefer input inside modal; otherwise fall back to a global selector
    in_modal = page.locator("div.modal-dialog")
    if in_modal.count() > 0 and in_modal.first.is_visible():
        input_loc = in_modal.locator("input#search, input[placeholder*='Pincode' i]").first
    else:
        input_loc = page.locator("input#search, input[placeholder*='Pincode' i]").first

    input_loc.wait_for(state="visible", timeout=10000)
    input_loc.fill(pincode)
    input_loc.press("Enter")

    # Let the site validate/update UI
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)


def get_stock_status_playwright(url: str) -> str | None:
    """Visit product page, set PIN, and decide stock status: 'in-stock' | 'out-of-stock' | None on error."""
    try:
        with sync_playwright() as p:
            # Important for Cloud Run
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            try:
                print("Navigating to product page…")
                page.goto(url, wait_until="networkidle")

                print("Ensuring pincode modal is open…")
                _open_pincode_modal(page)

                print(f"Entering pincode {PINCODE}…")
                _enter_pincode(page, PINCODE)

                # ----- Negative signal: explicit Sold Out alert/banner -----
                sold_out_selector = "div.alert.alert-danger.mt-3:has-text('Sold Out')"
                if page.locator(sold_out_selector).first.is_visible():
                    print("Detected 'Sold Out' alert → out-of-stock")
                    return "out-of-stock"

                # ----- Positive signal: visible & enabled Add to Cart -----
                add_to_cart = page.locator("button:has-text('Add to Cart')").first
                if add_to_cart.count() > 0 and add_to_cart.is_visible() and add_to_cart.is_enabled():
                    print("Add to Cart is visible and enabled → in-stock")
                    return "in-stock"

                # ----- Other negative signals: undeliverable copy -----
                undeliverable = page.get_by_text(re.compile(r"not deliverable|not available at", re.I))
                if undeliverable.count() > 0:
                    print("Detected 'not deliverable' message → out-of-stock")
                    return "out-of-stock"

                # Conservative default
                print("No positive in-stock signal; defaulting to out-of-stock.")
                return "out-of-stock"

            except PWTimeout as te:
                print(f"Playwright timeout: {te}")
                # Optional: capture a screenshot to /tmp for debugging
                try:
                    page.screenshot(path="/tmp/amul_debug.png", full_page=True)
                    print("Saved debug screenshot to /tmp/amul_debug.png")
                except Exception:
                    pass
                return None
            except Exception as e:
                print(f"Error inside page flow: {e}")
                try:
                    page.screenshot(path="/tmp/amul_debug.png", full_page=True)
                    print("Saved debug screenshot to /tmp/amul_debug.png")
                except Exception:
                    pass
                return None
            finally:
                browser.close()
    except Exception as e:
        # Launch-level errors (shouldn’t happen with the Playwright base image)
        print(f"Error with Playwright (launch/session): {e}")
        return None


def save_state(status: str) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            f.write(status)
    except Exception as e:
        print(f"Failed to save state: {e}")


def load_state() -> str:
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return f.read().strip()
    except Exception as e:
        print(f"Failed to load state: {e}")
    return "out-of-stock"


def buttermilk_checker_v2_function(request) -> str:
    """HTTP handler used by Cloud Run/Scheduler."""
    try:
        current_status = get_stock_status_playwright(PRODUCT_URL)

        if current_status:
            last_status = load_state()
            print(f"Last status: {last_status}, Current status: {current_status}")

            if last_status == "out-of-stock" and current_status == "in-stock":
                print("Product is now in stock! Triggering notification…")
                send_email_notification("Amul High Protein Buttermilk")

            save_state(current_status)
        else:
            print("Current status is None (error during check); leaving last state unchanged.")

        return "Function executed successfully."
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return f"Function failed with an error: {e}"
