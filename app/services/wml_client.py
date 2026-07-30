"""Scraper client for the WML CRM (wml.pp.ua) — read-only, own-account use.

The site has no JSON API: it's a server-rendered Yii2 (Kartik GridView) app.
Login form fields/URL are auto-detected (whatever page is returned when an
unauthenticated request hits a protected URL), so nothing here is hardcoded
against a specific login route.
"""
import logging
import re
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://wml.pp.ua"
STATS_URL = f"{BASE_URL}/profile/statistics"

# "ДАХ ИИ_1035" -> name="ДАХ", excluded=True ; "ТАНГО 47_1134" -> name="ТАНГО 47", excluded=False
_SUFFIX_RE = re.compile(r"^(?P<name>.*?)(?P<ii>\s+ИИ)?_(?P<num>\d+)\s*$")

# WML has a second, older numbering convention: a leading "(NNNN) " id prefix
# instead of a trailing "_NNNN" suffix, e.g. "(2119) СУКУНА" -> "СУКУНА".
_LEADING_ID_RE = re.compile(r"^\(\d+\)\s*")


_PROFILE_ID_RE = re.compile(r"/profile/(\d+)")


@dataclass
class WmlProfile:
    """One row from the /profile/statistics grid."""
    wml_id: str | None  # numeric WML profile id, e.g. "1134"
    wml_name: str  # raw WML display name, e.g. "ТАНГО 47_1134"
    name: str  # stripped of the "_NNNN" suffix (and " ИИ" token), e.g. "ТАНГО 47"
    profile_url: str | None
    register_date: str
    office: str
    scout: str
    fansly_date: str | None
    tango_date: str | None


@dataclass
class WmlProfileDetail:
    """Everything needed to create the Notion model page, fetched fresh
    from a single profile page (so a button pressed long after the initial
    notify still gets current data, not a stale snapshot)."""
    wml_name: str | None  # raw name, e.g. "TAXO_1135"
    office: str | None
    scout: str | None
    location: str | None  # country only
    language: str | None  # raw, e.g. "eng, esp"
    comment: str | None
    tg_content_manager: str | None
    model_telegram: str | None


def strip_wml_suffix(wml_name: str) -> str | None:
    """Strip WML's id decoration — either a trailing "_NNNN" suffix or a
    leading "(NNNN) " prefix (two different numbering conventions used by
    different cohorts of profiles). Returns None if the profile carries the
    " ИИ" token (excluded from sync entirely)."""
    name = _LEADING_ID_RE.sub("", wml_name.strip())
    match = _SUFFIX_RE.match(name)
    if not match:
        return name.strip()
    if match.group("ii"):
        return None
    return match.group("name").strip()


def _has_login_form(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("input", {"type": "password"}) is not None


def _login(session: requests.Session, resp: requests.Response, username: str, password: str) -> None:
    soup = BeautifulSoup(resp.text, "html.parser")
    form = None
    for f in soup.find_all("form"):
        if f.find("input", {"type": "password"}):
            form = f
            break
    if form is None:
        raise RuntimeError("WML login form not found on page")

    action = form.get("action") or resp.url
    post_url = requests.compat.urljoin(resp.url, action)

    data: dict[str, str] = {}
    user_field = None
    pass_field = None
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text")
        if itype == "password":
            pass_field = name
        elif itype == "hidden":
            data[name] = inp.get("value", "")
        elif itype in ("text", "email") and "csrf" not in name.lower():
            user_field = user_field or name

    if not user_field or not pass_field:
        raise RuntimeError(f"could not detect WML login fields (user={user_field}, pass={pass_field})")

    data[user_field] = username
    data[pass_field] = password

    login_resp = session.post(post_url, data=data, headers={"Referer": resp.url})
    if _has_login_form(login_resp.text):
        raise RuntimeError("WML login failed — still showing login form (bad credentials?)")


def fetch_statistics_html(session: requests.Session, username: str, password: str,
                           per_page: int = 1000, sort: str = "-register_date") -> str:
    """Login (if needed) and return the raw HTML of the statistics grid page."""
    params = {"perPage": per_page, "sort": sort}
    resp = session.get(STATS_URL, params=params)
    if _has_login_form(resp.text):
        _login(session, resp, username, password)
        resp = session.get(STATS_URL, params=params)
    return resp.text


def fetch_profile_detail_html(session: requests.Session, profile_url: str) -> str:
    resp = session.get(profile_url)
    return resp.text


def fetch_profile_by_id(session: requests.Session, username: str, password: str, wml_id: str) -> WmlProfileDetail:
    """Login (if needed) and fetch+parse a single profile page fresh by its numeric id.

    Used when the "Add to Notion" button is pressed — re-fetches current data
    rather than relying on a snapshot from whenever the notify was generated.
    """
    profile_url = f"{BASE_URL}/profile/{wml_id}"
    resp = session.get(profile_url)
    if _has_login_form(resp.text):
        _login(session, resp, username, password)
        resp = session.get(profile_url)
    return parse_profile_detail(resp.text)


def parse_statistics(html: str) -> list[WmlProfile]:
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find("div", id="w0")
    if grid is None:
        raise RuntimeError("WML grid container not found — not logged in or page structure changed")

    profiles: list[WmlProfile] = []
    for tr in grid.find_all("tr", attrs={"data-key": True}):
        tds = tr.find_all("td", attrs={"data-col-seq": True})
        if len(tds) < 17:
            continue

        name_link = tds[0].find("a")
        wml_name = tds[0].get_text(" ", strip=True).replace("→", "").strip()
        profile_url = requests.compat.urljoin(BASE_URL, name_link["href"]) if name_link else None
        id_match = _PROFILE_ID_RE.search(name_link["href"]) if name_link else None
        wml_id = id_match.group(1) if id_match else None

        register_date = tds[1].get_text(" ", strip=True)
        scout = tds[3].get_text(strip=True)
        office = tds[4].get_text(strip=True)
        fansly_date = tds[8].get_text(strip=True) or None
        tango_date = tds[9].get_text(strip=True) or None

        name = strip_wml_suffix(wml_name)
        if name is None:
            continue  # "ИИ" excluded profile

        profiles.append(WmlProfile(
            wml_id=wml_id,
            wml_name=wml_name,
            name=name,
            profile_url=profile_url,
            register_date=register_date,
            office=office,
            scout=scout,
            fansly_date=fansly_date,
            tango_date=tango_date,
        ))

    return profiles


def parse_profile_detail(html: str) -> WmlProfileDetail:
    soup = BeautifulSoup(html, "html.parser")

    def _field(label: str) -> str | None:
        label_tag = soup.find(string=re.compile(rf"^\s*{re.escape(label)}\s*:?\s*$"))
        if not label_tag:
            return None
        parent = label_tag.find_parent()
        if not parent:
            return None
        value = parent.find_next_sibling()
        text = value.get_text(" ", strip=True) if value else None
        return text or None

    wml_name = _field("Name")
    office = _field("Offices")
    scout = _field("Scout")
    location_raw = _field("Location")
    location = location_raw.split(",")[0].strip() if location_raw else None
    language = _field("Language")
    comment = _field("Comments")
    tg_content_manager = _field("TG Content Manager")

    model_telegram = None
    tg_link = soup.find("a", href=re.compile(r"^https?://t\.me/"))
    if tg_link:
        username = tg_link.get_text(strip=True)
        if username:
            model_telegram = username if username.startswith("@") else f"@{username}"
        else:
            model_telegram = tg_link["href"]

    return WmlProfileDetail(
        wml_name=wml_name,
        office=office,
        scout=scout,
        location=location,
        language=language,
        comment=comment,
        tg_content_manager=tg_content_manager,
        model_telegram=model_telegram,
    )
