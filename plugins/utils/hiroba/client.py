from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HIROBA_ORIGIN = "https://donderhiroba.jp"
BN_OAUTH_URL = (
    "https://www.bandainamcoid.com/v2/oauth2/auth?back=v3&client_id=nbgi_taiko"
    "&scope=JpGroupAll&redirect_uri=https%3A%2F%2Fdonderhiroba.jp%2Flogin_process.php"
    "%3Finvite_code%3D%26abs_back_url%3D%26location_code%3D&text="
)
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class HirobaError(Exception):
    pass


class HirobaSessionExpiredError(HirobaError):
    pass


class HirobaUpdateScoreError(HirobaError):
    def __init__(self, result: str, errmsg: str = ""):
        self.result = str(result or "").strip()
        self.errmsg = str(errmsg or "").strip()
        message = f"update_score failed with result={self.result}"
        if self.errmsg:
            message += f": {self.errmsg}"
        super().__init__(message)


@dataclass
class HirobaLoginCard:
    id_pos: Optional[int] = None
    taiko_no: str = ""
    display_name: str = ""
    access_code: str = ""
    has_play_data: bool = False


def _session_proxies() -> Optional[dict]:
    proxy = os.getenv("HIROBA_PROXY", "").strip()
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def _cookie_json_for_login(session: requests.Session) -> str:
    override = os.getenv("HIROBA_BN_COOKIE_JSON", "").strip()
    if override:
        return override

    cookie_obj: Dict[str, str] = {}
    for cookie in session.cookies:
        domain = cookie.domain or ""
        if "bandainamcoid" not in domain and domain not in ("", None):
            continue
        if cookie.value:
            cookie_obj[cookie.name] = cookie.value
    cookie_obj.setdefault("language", "zh-cn")
    cookie_obj.setdefault("retention", "1")
    cookie_obj.setdefault("retention_tmp", "1")
    return json.dumps(cookie_obj, ensure_ascii=False, separators=(",", ":"))


def _apply_login_response_cookies(
    session: requests.Session, cookie_payload: Dict[str, Any]
) -> None:
    for item in cookie_payload.values():
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        value = item.get("value")
        domain = item.get("domain") or ".bandainamcoid.com"
        path = item.get("path", "/")
        if value is None:
            session.cookies.set(name, "", domain=domain, path=path)
            continue
        session.cookies.set(name, value, domain=domain, path=path)


def _cookie_json_from_session(session: requests.Session) -> str:
    cookie_obj: Dict[str, str] = {}
    for cookie in session.cookies:
        if cookie.value:
            cookie_obj[cookie.name] = cookie.value
    cookie_obj.setdefault("language", "zh-cn")
    return json.dumps(cookie_obj, ensure_ascii=False, separators=(",", ":"))


def _resolve_passkey_oauth_url(session: requests.Session, page_url: str) -> str:
    query = parse_qs(urlparse(page_url).query)
    params = {
        "client_id": (query.get("client_id") or ["nbgi_taiko"])[0],
        "backto": (query.get("backto") or [""])[0],
        "redirect_uri": (query.get("redirect_uri") or [""])[0],
        "customize_id": (query.get("customize_id") or [""])[0],
        "code": (query.get("code") or [""])[0],
        "language": "zh-cn",
        "cookie": _cookie_json_from_session(session),
    }
    resp = session.get(
        "https://account-api.bandainamcoid.com/v3/passkey/info",
        params=params,
        headers={
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    if str(data.get("result") or "").upper() != "OK":
        raise HirobaError("passkey/info failed before OAuth redirect")

    _apply_login_response_cookies(session, data.get("cookie") or {})
    oauth_url = (
        data.get("redirect")
        or data.get("data", {}).get("btn", {}).get("btn-next", {}).get("url")
    )
    if not oauth_url:
        raise HirobaError("passkey/info returned no OAuth redirect URL")
    return oauth_url


def _resolve_oauth_start_url(session: requests.Session, redirect_url: str) -> str:
    if "passkeyInfo" in redirect_url:
        return _resolve_passkey_oauth_url(session, redirect_url)

    resp = session.get(
        redirect_url,
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=60,
        allow_redirects=True,
    )
    if "passkeyInfo" in resp.url:
        return _resolve_passkey_oauth_url(session, resp.url)
    return redirect_url


def _parse_login_select_cards(html: str) -> List[HirobaLoginCard]:
    soup = BeautifulSoup(html, "html.parser")
    cards: List[HirobaLoginCard] = []
    for box in soup.select(".contentBox.cardSelect"):
        card = HirobaLoginCard()

        form = box.select_one("form[action*='login_select']")
        if form is not None:
            node = form.select_one("input[name='id_pos']")
            if node is not None and node.get("value"):
                try:
                    card.id_pos = int(str(node["value"]))
                except ValueError:
                    card.id_pos = None

        number_node = box.select_one("p.no")
        if number_node is not None:
            match = re.search(r"(\d{10,14})", number_node.get_text(" ", strip=True))
            if match:
                card.taiko_no = match.group(1)

        mydon_area = box.select_one("div[id='mydon_area']")
        if mydon_area is not None:
            direct_divs = mydon_area.find_all("div", recursive=False)
            if len(direct_divs) > 1:
                card.display_name = direct_divs[1].get_text(" ", strip=True)

        access_match = re.search(
            r"アクセスコード：\s*([0-9\-]{10,30})",
            box.get_text(" ", strip=True),
        )
        if access_match:
            card.access_code = access_match.group(1).strip()

        # Playable cards expose login_select form + id_pos. Do not scan full box text for
        # "no play history" — malformed login_select HTML can nest the next card inside
        # the previous <li>, which falsely marks playable cards as empty.
        card.has_play_data = bool(form is not None and card.id_pos is not None)
        cards.append(card)
    return cards


def _format_login_card_options(cards: List[HirobaLoginCard]) -> str:
    parts: List[str] = []
    for card in cards:
        if not card.has_play_data or not card.taiko_no:
            continue
        label = card.taiko_no
        if card.display_name:
            label += f"({card.display_name})"
        parts.append(label)
    return " / ".join(parts)


def _choose_hiroba_card(
    cards: List[HirobaLoginCard],
    *,
    card_pos: Optional[int] = None,
    taiko_no: Optional[str] = None,
) -> HirobaLoginCard:
    playable = [card for card in cards if card.has_play_data and card.id_pos is not None]
    if not playable:
        raise HirobaError("No selectable Hiroba cards with playable data on login_select.php")

    expected_taiko_no = str(taiko_no or "").strip()
    if expected_taiko_no:
        matched = next((card for card in playable if card.taiko_no == expected_taiko_no), None)
        if matched is None:
            choices = _format_login_card_options(playable)
            raise HirobaError(
                f"该 Bandai Namco ID 下未找到太鼓番 {expected_taiko_no}。"
                + (f"可用太鼓番：{choices}" if choices else "")
            )
        return matched

    if card_pos is not None:
        matched = next((card for card in playable if card.id_pos == card_pos), None)
        if matched is not None:
            return matched

    if len(playable) == 1:
        return playable[0]

    choices = _format_login_card_options(playable)
    raise HirobaError(
        "该 Bandai Namco ID 下有多个可同步的太鼓番。"
        + (f"可用太鼓番：{choices}。" if choices else "")
        + "请发送“绑定hiroba 邮箱 密码 太鼓番”指定要绑定的账号。"
    )


def _select_hiroba_card(
    session: requests.Session,
    html: str,
    *,
    card_pos: Optional[int] = None,
    taiko_no: Optional[str] = None,
) -> HirobaLoginCard:
    cards = _parse_login_select_cards(html)
    selected_card = _choose_hiroba_card(cards, card_pos=card_pos, taiko_no=taiko_no)
    selected = selected_card.id_pos
    if selected is None:
        raise HirobaError("Selected Hiroba card has no id_pos")

    resp = session.post(
        f"{HIROBA_ORIGIN}/login_select.php",
        data={"id_pos": str(selected), "mode": "exec"},
        headers={
            "Referer": f"{HIROBA_ORIGIN}/login_select.php",
            "Origin": HIROBA_ORIGIN,
        },
        timeout=60,
        allow_redirects=True,
    )
    resp.raise_for_status()
    if "login.php" in resp.url or "login_select.php" in resp.url:
        raise HirobaError(
            f"Failed to select Hiroba card id_pos={selected} (stopped at {resp.url})"
        )
    return selected_card


def _complete_hiroba_oauth(
    session: requests.Session,
    start_url: str,
    *,
    card_pos: Optional[int] = None,
    taiko_no: Optional[str] = None,
) -> str:
    oauth_headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    location = start_url
    for _ in range(12):
        resp = session.get(
            location,
            headers=oauth_headers,
            timeout=60,
            allow_redirects=False,
        )
        if "login_select.php" in resp.url and resp.status_code == 200:
            _select_hiroba_card(
                session,
                resp.text,
                card_pos=card_pos,
                taiko_no=taiko_no,
            )
            token = _extract_token_from_session(session)
            if not token:
                raise HirobaError("Failed to obtain _token_v2 after card selection")
            return token

        if resp.status_code not in (301, 302, 303, 307, 308):
            break
        next_location = resp.headers.get("Location")
        if not next_location:
            break
        location = urljoin(location, next_location)

    final = session.get(location, headers=oauth_headers, timeout=60)
    final.raise_for_status()
    if "login_select.php" in final.url:
        _select_hiroba_card(
            session,
            final.text,
            card_pos=card_pos,
            taiko_no=taiko_no,
        )
    elif "login.php" in final.url:
        raise HirobaError("Hiroba OAuth ended at login.php without a valid session")

    token = _extract_token_from_session(session)
    if not token:
        match = re.search(r"_token_v2=([^;,\s]+)", final.headers.get("Set-Cookie", ""))
        token = match.group(1) if match else None
    if not token:
        raise HirobaError("Failed to obtain _token_v2 after login")
    return token


def _extract_token_from_session(session: requests.Session) -> Optional[str]:
    for cookie in session.cookies:
        if cookie.name == "_token_v2":
            return cookie.value
    return None


def _is_login_page_response(resp: requests.Response) -> bool:
    path = urlparse(resp.url).path or ""
    return path.endswith("/login.php")


class HirobaClient:
    def __init__(self, token: Optional[str] = None, *, timeout: int = 30):
        self.timeout = timeout
        self.session = requests.Session()
        # Only honor the explicit HIROBA_PROXY knob. Inherited shell proxies on
        # self-hosted machines are often unrelated and can break the BN/Hiroba
        # login flow.
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": DEFAULT_UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        proxies = _session_proxies()
        if proxies:
            self.session.proxies.update(proxies)
        if token:
            self.set_token(token)

    @property
    def token(self) -> Optional[str]:
        return _extract_token_from_session(self.session)

    def set_token(self, token: str) -> None:
        self.session.cookies.set("_token_v2", token, domain="donderhiroba.jp", path="/")

    def _warmup_bandainamco_session(self) -> None:
        headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        self.session.get(
            BN_OAUTH_URL,
            headers=headers,
            timeout=self.timeout,
            allow_redirects=True,
        )

    def _login_to_bandainamco(self, email: str, password: str) -> str:
        self._warmup_bandainamco_session()

        form = {
            "client_id": "nbgi_taiko",
            "redirect_uri": BN_OAUTH_URL,
            "backto": "",
            "customize_id": "",
            "login_id": email,
            "password": password,
            "retention": "1",
            "language": "zh-cn",
            "cookie": _cookie_json_for_login(self.session),
            "prompt": "login",
        }
        headers = {
            "User-Agent": DEFAULT_UA,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://www.bandainamcoid.com",
            "Referer": BN_OAUTH_URL,
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = self.session.post(
                "https://account-api.bandainamcoid.com/v3/login/idpw",
                data=form,
                headers=headers,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise HirobaError(f"Bandai Namco login failed: {exc}") from exc

        result = str(data.get("result") or "").upper()
        if result != "OK":
            detail = data.get("data")
            if isinstance(detail, dict):
                msg = detail.get("msg") or detail.get("message")
            else:
                msg = detail
            raise HirobaError(
                f"Bandai Namco login rejected (result={data.get('result')}): {msg or 'check email/password'}"
            )

        _apply_login_response_cookies(self.session, data.get("cookie") or {})

        redirect_url = data.get("redirect")
        if not redirect_url or "error.html" in redirect_url:
            raise HirobaError("Bandai Namco login returned no valid redirect URL")
        return _resolve_oauth_start_url(self.session, redirect_url)

    def list_login_cards(self, email: str, password: str) -> List[HirobaLoginCard]:
        oauth_start = self._login_to_bandainamco(email, password)
        oauth_headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        location = oauth_start
        for _ in range(12):
            resp = self.session.get(
                location,
                headers=oauth_headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
            if "login_select.php" in resp.url and resp.status_code == 200:
                return _parse_login_select_cards(resp.text)

            if resp.status_code not in (301, 302, 303, 307, 308):
                break
            next_location = resp.headers.get("Location")
            if not next_location:
                break
            location = urljoin(location, next_location)

        final = self.session.get(location, headers=oauth_headers, timeout=self.timeout)
        final.raise_for_status()
        if "login_select.php" in final.url:
            return _parse_login_select_cards(final.text)
        raise HirobaError("Failed to read login_select.php after Bandai Namco login")

    def login(
        self,
        email: str,
        password: str,
        *,
        card_pos: Optional[int] = None,
        taiko_no: Optional[str] = None,
    ) -> str:
        oauth_start = self._login_to_bandainamco(email, password)
        token = _complete_hiroba_oauth(
            self.session,
            oauth_start,
            card_pos=card_pos,
            taiko_no=taiko_no,
        )
        self.set_token(token)
        return token

    def _get_tckt(self) -> str:
        resp = self.session.get(f"{HIROBA_ORIGIN}/score_list.php", timeout=self.timeout)
        resp.raise_for_status()
        if _is_login_page_response(resp):
            raise HirobaSessionExpiredError(
                "Donder Hiroba session expired before reading score_list.php"
            )
        soup = BeautifulSoup(resp.text, "html.parser")
        node = soup.select_one("#_tckt")
        if node is None or not node.get("value"):
            raise HirobaError("Failed to read _tckt from score_list.php")
        return str(node["value"])

    def update_score(self, *, max_retries: int = 5) -> None:
        for attempt in range(max_retries):
            tckt = self._get_tckt()
            resp = self.session.post(
                f"{HIROBA_ORIGIN}/ajax/update_score.php",
                data={"_tckt": tckt},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{HIROBA_ORIGIN}/score_list.php",
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            try:
                payload = resp.json()
            except Exception as exc:
                raise HirobaError(f"update_score returned non-JSON: {exc}") from exc
            raw_result = payload.get("result")
            result = "" if raw_result is None else str(raw_result).strip()
            if result == "0":
                return
            if result == "705":
                time.sleep(min(2 ** attempt, 8))
                continue
            raise HirobaUpdateScoreError(result, str(payload.get("errmsg") or ""))
        raise HirobaError("update_score exceeded retry limit")

    def fetch_mypage(self) -> str:
        resp = self.session.get(f"{HIROBA_ORIGIN}/mypage_top.php", timeout=self.timeout)
        resp.raise_for_status()
        if _is_login_page_response(resp):
            raise HirobaSessionExpiredError(
                "Donder Hiroba session expired before reading mypage_top.php"
            )
        return resp.text

    def fetch_score_list(self, genre: int) -> str:
        resp = self.session.get(
            f"{HIROBA_ORIGIN}/score_list.php",
            params={"genre": genre},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        if _is_login_page_response(resp):
            raise HirobaSessionExpiredError("Not logged in to Donder Hiroba")
        return resp.text

    def fetch_score_detail(self, song_no: str, level: int) -> str:
        resp = self.session.get(
            f"{HIROBA_ORIGIN}/score_detail.php",
            params={"song_no": song_no, "level": level},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        if _is_login_page_response(resp):
            raise HirobaSessionExpiredError(
                "Donder Hiroba session expired before reading score_detail.php"
            )
        return resp.text
