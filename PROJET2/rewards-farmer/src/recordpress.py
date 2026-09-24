import textwrap
import keyboard as kb
import pygetwindow as pygw
from matplotlib import pyplot as plt
from selenium import webdriver
from constants import USER_DATA_DIR, PROFILE_NAME

keypress_times: list[float] = []

def key_event_handler(event: kb.KeyboardEvent):
	if event.event_type == kb.KEY_DOWN:
		timestamp = event.time
		key = event.name

		window = pygw.getActiveWindow()

		if window and "Edge" in window.title:
			keypress_times.append(timestamp)

kb.hook(key_event_handler)

options = webdriver.EdgeOptions()

options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("--disable-blink-features=AutomationControlled")
options.add_argument(f"--user-data-dir={USER_DATA_DIR}")
options.add_argument(f"--profile-directory={PROFILE_NAME}")

driver = webdriver.Edge(options=options)

driver.get("https://rewards.bing.com/")

input("Press Enter to exit...")

press_time_differences = [t2 - t1 for t1, t2 in zip(keypress_times[:-1], keypress_times[1:])]

plt.hist(press_time_differences)
plt.savefig("keypress_times.png")

open("keypress_times.txt", "w").writelines(str(diff)+'\n' for diff in press_time_differences)

driver.quit()