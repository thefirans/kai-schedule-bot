"""
NAU Cabinet Schedule Scraper
Logs into cabinet.nau.edu.ua and parses the schedule HTML.

Updated for the new layout: 18 week panes (week-pane-1 to week-pane-18)
instead of the old 2-tab system (w0-tab0, w0-tab1).
"""

import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass, field
import re


@dataclass
class Lesson:
    day: str
    time_start: str
    time_end: str
    name: str
    lesson_type: str
    teacher: str
    room: str
    groups: str = ""
    tags: list[str] = field(default_factory=list)
    week: int = 1  # semester week number (1-18)

    def format(self, include_tags: bool = True) -> str:
        tags_str = ""
        if include_tags and self.tags:
            tags_str = f"  _{', '.join(self.tags)}_"
        return (
            f"📚 *{self.name}* ({self.lesson_type}){tags_str}\n"
            f"⏰ {self.time_start} — {self.time_end}\n"
            f"👨‍🏫 {self.teacher}\n"
            f"🏫 Ауд. {self.room}"
        )


DAYS_NORMALIZED = [
    "Понеділок", "Вівторок", "Середа", "Четвер",
    "П'ятниця", "Субота", "Неділя",
]


class NAUSession:
    BASE_URL = "https://cabinet.nau.edu.ua"
    LOGIN_URL = f"{BASE_URL}/site/login"
    SCHEDULE_URL = f"{BASE_URL}/student/schedule"

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def login(self) -> bool:
        resp = self.session.get(self.LOGIN_URL, timeout=15)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        csrf_meta = soup.find("meta", {"name": "csrf-token"})
        if not csrf_meta:
            raise RuntimeError("Could not find CSRF token on login page")

        payload = {
            "_csrf-frontend": csrf_meta["content"],
            "LoginForm[username]": self.username,
            "LoginForm[password]": self.password,
            "LoginForm[rememberMe]": "1",
        }

        resp = self.session.post(self.LOGIN_URL, data=payload, allow_redirects=True, timeout=15)
        resp.raise_for_status()
        return "login" not in resp.url.lower()

    def get_schedule_html(self) -> str:
        """Fetch schedule page in table view."""
        resp = self.session.get(self.SCHEDULE_URL, params={"type": "table"}, timeout=15)
        resp.raise_for_status()
        return resp.text


def _parse_week_pane(pane, week_num: int) -> list[Lesson]:
    """Parse a single week pane div into lessons."""
    lessons = []

    for row in pane.find_all("div", class_="grid-row"):
        time_cell = row.find("div", class_="flex-column-center")
        if not time_cell:
            continue

        bold_spans = time_cell.find_all("span", class_="text-md")
        minute_spans = time_cell.find_all("span", class_="text-xs")
        if len(bold_spans) < 2 or len(minute_spans) < 2:
            continue

        time_start = f"{bold_spans[0].text.strip()}:{minute_spans[0].text.strip()}"
        time_end = f"{bold_spans[1].text.strip()}:{minute_spans[1].text.strip()}"

        day_cells = row.find_all("div", class_="grid-cell", recursive=False)
        day_cells = day_cells[1:]  # skip time column

        for day_idx, cell in enumerate(day_cells):
            if day_idx >= len(DAYS_NORMALIZED):
                break

            for card in cell.find_all("div", class_="pair-card"):
                tags = []
                badge_container = card.find("div", class_="card-top-badge")
                if badge_container:
                    for badge_div in badge_container.find_all("div"):
                        t = badge_div.get_text(strip=True)
                        if t:
                            tags.append(t)

                name_div = card.find("div", class_="font-weight-bold")
                name = name_div.get_text(strip=True) if name_div else "?"

                type_badge = card.find("span", class_=re.compile(r"badge-pill"))
                lesson_type = type_badge.get_text(strip=True) if type_badge else "?"

                groups = ""
                hashtag_icon = card.find("i", class_="fa-hashtag")
                if hashtag_icon:
                    span = hashtag_icon.find_parent("div").find("span")
                    if span:
                        groups = span.get_text(strip=True)

                teacher = ""
                person_icon = card.find("i", class_="fa-person")
                if person_icon:
                    span = person_icon.find_parent("div").find("span")
                    if span:
                        teacher = span.get_text(strip=True)

                room = ""
                building_icon = card.find("i", class_="fa-building")
                if building_icon:
                    span = building_icon.find_parent("div").find("span")
                    if span:
                        room = span.get_text(strip=True)

                lessons.append(Lesson(
                    day=DAYS_NORMALIZED[day_idx],
                    time_start=time_start, time_end=time_end,
                    name=name, lesson_type=lesson_type,
                    teacher=teacher, room=room,
                    groups=groups, tags=tags, week=week_num,
                ))

    return lessons


def parse_schedule(html: str) -> tuple[list[Lesson], int]:
    """
    Parse all week panes. Returns (lessons, active_week_number).
    """
    soup = BeautifulSoup(html, "html.parser")
    lessons = []

    for pane in soup.find_all("div", class_="schedule-week-pane"):
        pane_id = pane.get("id", "")
        match = re.search(r"week-pane-(\d+)", pane_id)
        if not match:
            continue
        week_num = int(match.group(1))
        lessons.extend(_parse_week_pane(pane, week_num))

    # Find active (current) week
    active_week = 1
    active_pane = soup.find("div", class_=re.compile(r"schedule-week-pane.*active"))
    if active_pane:
        match = re.search(r"week-pane-(\d+)", active_pane.get("id", ""))
        if match:
            active_week = int(match.group(1))

    return lessons, active_week


def fetch_schedule(username: str, password: str) -> tuple[list[Lesson], int]:
    """Full pipeline: login → fetch → parse. Returns (lessons, active_week)."""
    session = NAUSession(username, password)
    if not session.login():
        raise RuntimeError("LOGIN_FAILED")
    html = session.get_schedule_html()
    return parse_schedule(html)