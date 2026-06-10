import os
import time
import urllib.parse
from urllib.parse import urlparse, parse_qs
import requests
import pyotp
from dotenv import load_dotenv

# We use undetected_chromedriver to avoid bot detection by Upstox
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import logging

logger = logging.getLogger(__name__)

def get_upstox_access_token():
    """
    Automates the Upstox Login flow using Selenium and undetected_chromedriver.
    Returns the access_token string if successful, else None.
    """
    load_dotenv()
    api_key = os.getenv("UPSTOX_CLIENT_ID", os.getenv("UPSTOX_API_KEY"))
    api_secret = os.getenv("UPSTOX_CLIENT_SECRET", os.getenv("UPSTOX_API_SECRET"))
    redirect_uri = os.getenv("UPSTOX_REDIRECT_URI", "http://127.0.0.1")
    mobile = os.getenv("UPSTOX_MOBILE")
    pin = os.getenv("UPSTOX_PIN")
    totp_secret = os.getenv("UPSTOX_TOTP_SECRET")

    if not all([api_key, api_secret, redirect_uri, mobile, pin, totp_secret]):
        logger.error("Missing Upstox credentials in .env")
        return None

    # Step 1: Generate Login URL
    login_url = f"https://api.upstox.com/v2/login/authorization/dialog?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}"

    options = uc.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")

    driver = None
    try:
        logger.info("Starting headless Chrome for Upstox login...")
        driver = uc.Chrome(options=options)
        driver.get(login_url)

        wait = WebDriverWait(driver, 15)

        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains

        # Entering Mobile Number
        logger.info("Entering mobile number...")
        mobile_input = wait.until(EC.presence_of_element_located((By.ID, "mobileNum")))
        mobile_input.clear()
        for digit in mobile:
            mobile_input.send_keys(digit)
            time.sleep(0.05)
            
        time.sleep(1)
        
        get_otp_btn = wait.until(EC.element_to_be_clickable((By.ID, "getOtp")))
        ActionChains(driver).move_to_element(get_otp_btn).click().perform()

        # Upstox now asks for TOTP *first* after mobile number
        logger.info("Generating and entering TOTP...")
        totp = pyotp.TOTP(totp_secret)
        current_totp = totp.now()

        totp_input = wait.until(EC.presence_of_element_located((By.ID, "otpNum")))
        totp_input.clear()
        
        # Type the TOTP slowly to trigger React events
        for digit in current_totp:
            totp_input.send_keys(digit)
            time.sleep(0.05)
            
        time.sleep(1)
        
        # Click Continue using ActionChains
        try:
            continue_btn = wait.until(EC.element_to_be_clickable((By.ID, "continueBtn")))
            ActionChains(driver).move_to_element(continue_btn).click().perform()
            time.sleep(2)
        except Exception as e:
            logger.error(f"Could not click continueBtn: {e}")

        # Try to find PIN input or check if we already redirected
        logger.info("Entering PIN...")
        try:
            pin_input = wait.until(EC.presence_of_element_located((By.ID, "val")))
            pin_input.send_keys(pin)
            pin_input.send_keys(Keys.RETURN)
        except Exception:
            logger.error("Failed to find PIN input.")
            driver.save_screenshot("upstox_pin_error.png")
            with open("upstox_page.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)
            raise
        
        # In the new UI, entering the 6-digit PIN automatically submits.
        # If it doesn't, we can try to click continue.
        try:
            pin_continue_btn = wait.until(EC.element_to_be_clickable((By.ID, "pinContinueBtn")))
            pin_continue_btn.click()
        except Exception:
            pass

        # Wait for redirect
        logger.info("Waiting for redirect...")
        wait.until(EC.url_contains("code="))

        current_url = driver.current_url
        parsed_url = urlparse(current_url)
        code = parse_qs(parsed_url.query).get('code')

        if not code:
            logger.error("Failed to extract authorization code from URL.")
            return None

        auth_code = code[0]
        logger.info("Successfully acquired auth code. Exchanging for access token...")

        # Step 2: Exchange code for Access Token
        url = 'https://api.upstox.com/v2/login/authorization/token'
        headers = {
            'accept': 'application/json',
            'Api-Version': '2.0',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {
            'code': auth_code,
            'client_id': api_key,
            'client_secret': api_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }

        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')
            
            # Save token to file so other processes can use it
            with open(".upstox_token", "w") as f:
                f.write(access_token)
            logger.info("Upstox Access Token generated and saved to .upstox_token")
            return access_token
        else:
            logger.error(f"Failed to get access token: {response.text}")
            return None

    except Exception as e:
        logger.error(f"Upstox automated login failed: {e}")
        # Capture screenshot for debugging if it fails
        if driver:
            driver.save_screenshot("upstox_error.png")
            logger.info("Saved error screenshot to upstox_error.png")
        return None
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = get_upstox_access_token()
    if token:
        print("SUCCESS! Token acquired.")
    else:
        print("FAILED to acquire token.")
