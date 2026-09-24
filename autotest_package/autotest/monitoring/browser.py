"""Chrome setup adapted from rewards-farmer browser.py (see NOTICE)."""

import os

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service


def build_options(headless=True):
    options = Options()
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1920,1080")
    if headless:
        options.add_argument("--headless=new")
    if os.environ.get("MONITOR_CHROME_BINARY"):
        options.binary_location = os.environ["MONITOR_CHROME_BINARY"]
    return options


def create_driver(headless=True):
    service = Service(executable_path=os.environ.get("MONITOR_CHROMEDRIVER"))
    driver = webdriver.Chrome(service=service, options=build_options(headless))
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(15)
    return driver