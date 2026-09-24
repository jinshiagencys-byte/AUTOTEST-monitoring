"""Generic techniques adapted from rewards-farmer; MIT attribution in NOTICE.

Uses its keyboard delay distribution, cubic Bezier control points and Fitts
constants, without the Rewards/account logic or Windows calibration GUI.
"""

import math
import random

from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.common.exceptions import ElementClickInterceptedException


def movement_time(distance, width):
    return max(0.15, 0.5500 + 0.1276 * math.log2(max(1, 2 * distance / max(1, width))))


def bezier_points(start, end, count=24):
    def offset():
        return random.choice((-1, 1)) * random.randint(20, 40)
    p1 = (start[0] + offset(), start[1] + offset())
    p2 = (end[0] + offset(), end[1] + offset())
    for i in range(1, count + 1):
        # Same sigmoid velocity profile; force the exact final endpoint.
        t = 1 if i == count else 2 / (1 + math.exp(-4.5 * i / count)) - 1
        yield tuple((1-t)**3 * start[j] + 3*t*(1-t)**2 * p1[j] +
                    3*(1-t)*t*t * p2[j] + t**3 * end[j] for j in (0, 1))


class HumanInteractions:
    def __init__(self, driver):
        self.driver = driver
        self.position = (0, 0)

    def click(self, element):
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block:'center',inline:'center'});", element)
        x, y, width, height, vw, vh = self.driver.execute_script(
            "const r=arguments[0].getBoundingClientRect();"
            "return [r.x,r.y,r.width,r.height,innerWidth,innerHeight];", element)
        left, right = max(0, x), min(vw - 1, x + width)
        top, bottom = max(0, y), min(vh - 1, y + height)
        if right <= left or bottom <= top:
            raise ElementClickInterceptedException("Target outside viewport")
        end = (random.uniform(left + (right-left)*.25, left + (right-left)*.75),
               random.uniform(top + (bottom-top)*.25, top + (bottom-top)*.75))
        duration = movement_time(math.hypot(end[0]-self.position[0],
                                            end[1]-self.position[1]), (width+height)/2)
        actions = ActionBuilder(self.driver, duration=max(1, int(duration * 1000 / 24)))
        for px, py in bezier_points(self.position, end):
            actions.pointer_action.move_to_location(
                int(min(max(px, 0), vw-1)), int(min(max(py, 0), vh-1)))
        actions.perform()
        self.position = end
        # Never silently click an overlay that appeared while moving.
        hit = self.driver.execute_script(
            "const e=document.elementFromPoint(arguments[1],arguments[2]);"
            "return e===arguments[0] || arguments[0].contains(e);",
            element, int(end[0]), int(end[1]))
        if not hit:
            raise ElementClickInterceptedException("Target covered by another element")
        actions = ActionBuilder(self.driver)
        actions.pointer_action.click()
        actions.perform()

    def type_text(self, element, text):
        self.click(element)
        element.clear()
        actions = ActionChains(self.driver, duration=0)
        for key in text:
            interval = random.choices(((0.0, 0.1), (0.1, 0.2), (0.2, 0.4)),
                                      weights=(0.377, 0.5492, 0.0738))[0]
            actions.send_keys(key).pause(random.uniform(*interval))
        actions.perform()