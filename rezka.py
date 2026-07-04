import re
import json
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup

class RezkaAPI:
    def __init__(self, base_url="https://hdrezka-home.tv"):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive"
        }
        try:
            self.session.get(self.base_url, headers=self.headers, timeout=5)
        except Exception:
            pass

    def search(self, query):
        url = f"{self.base_url}/engine/ajax/search.php"
        payload = f"q={quote(query)}&t=0&f=0"
        headers = self.headers.copy()
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        headers["Referer"] = f"{self.base_url}/"
        try:
            response = self.session.post(url, data=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                return []
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            items = soup.select("li a")
            for item in items:
                href = item.get("href")
                title_elem = item.select_one(".title") or item.select_one(".b-search__live-title") or item
                if href and title_elem:
                    title = title_elem.text.strip()
                    if "найти все результаты" in title.lower():
                        continue
                    results.append({"title": title, "url": href})
            return results
        except Exception:
            return []

    def get_episodes(self, url):
        headers = self.headers.copy()
        headers["Referer"] = f"{self.base_url}/"
        try:
            response = self.session.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return {"translations": {}, "is_movie": True, "streams": None, "def_season": 1, "def_episode": 1, "html": ""}
            soup = BeautifulSoup(response.text, 'html.parser')
            
            post_id_element = soup.select_one("#post_id")
            if not post_id_element:
                return {"translations": {}, "is_movie": True, "streams": None, "def_season": 1, "def_episode": 1, "html": ""}
            post_id = post_id_element.get("value")
            
            translations = {}
            items = soup.select("#translator-list li") or soup.select(".b-translator__item")
            if items:
                for li in items:
                    name = li.text.strip()
                    trans_id = li.get("data-translator_id") or li.get("data-id")
                    if trans_id:
                        translations[name] = {"id": trans_id, "post_id": post_id}
                        
            if not translations:
                translations["Основной"] = {"id": "0", "post_id": post_id}
            
            js_text = response.text
            is_movie = True
            if "initCDNSeries" in js_text or soup.select_one("#simple-episodes-tabs") or soup.select_one(".b-simple_episodes__list") or soup.select_one("#simple-seasons-tabs"):
                is_movie = False

            def_season, def_episode = 1, 1
            series_init_match = re.search(r"initCDNSeriesEvents\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", js_text)
            if series_init_match:
                def_season = int(series_init_match.group(3))
                def_episode = int(series_init_match.group(4))

            streams = None
            match = re.search(r"initCDN(?:MoviesEvents|SeriesEvents|Movies|Series)\([^)]*?(\{.*?\"streams\".*?\})\)", js_text)
            if match:
                try:
                    config = json.loads(match.group(1))
                    streams = config.get("streams")
                except Exception:
                    pass

            return {
                "translations": translations, 
                "is_movie": is_movie, 
                "post_id": post_id, 
                "page_url": url,
                "streams": streams,
                "def_season": def_season,
                "def_episode": def_episode,
                "html": response.text
            }
        except Exception:
            return {"translations": {}, "is_movie": True, "streams": None, "def_season": 1, "def_episode": 1, "html": ""}

    def get_seasons_and_episodes(self, post_id, translator_id, referer_url, def_season=1, def_episode=1, raw_html=""):
        episodes_data = {}
        init_url = f"{self.base_url}/ajax/get_cdn_series/"
        headers = self.headers.copy()
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = referer_url
        
        for action in ["get_translator", "get_episodes"]:
            payload = {
                "id": post_id,
                "translator_id": translator_id,
                "action": action
            }
            try:
                response = self.session.post(init_url, data=payload, headers=headers, timeout=5)
                if response.status_code == 200:
                    res_json = response.json()
                    if res_json.get("success"):
                        html_data = res_json.get("html", "") + res_json.get("episodes", "") + res_json.get("seasons", "")
                        if html_data:
                            soup = BeautifulSoup(html_data, 'html.parser')
                            episode_tabs = soup.select(".b-simple_episode__item") or soup.select("#simple-episodes-tabs li")
                            
                            if episode_tabs:
                                for tab in episode_tabs:
                                    s_id = int(tab.get("data-season_id", def_season))
                                    e_id = int(tab.get("data-episode_id", def_episode))
                                    if s_id not in episodes_data:
                                        episodes_data[s_id] = []
                                    if e_id not in episodes_data[s_id]:
                                        episodes_data[s_id].append(e_id)
                                
                                if episodes_data:
                                    for s in episodes_data:
                                        episodes_data[s] = sorted(episodes_data[s])
                                    return episodes_data
            except Exception:
                continue

        # Способ 2: Извлечение JSON-карты напрямую из HTML
        if raw_html:
            js_match = re.search(r'initCDNSeriesEvents\([^)]*?(\{["\d\s:,\.\[\]\{\}]+?\})\s*[,\)]', raw_html)
            if not js_match:
                js_match = re.search(r'"seasons"\s*:\s*(\{.*?\}),', raw_html)
            
            if js_match:
                try:
                    parsed_map = json.loads(js_match.group(1))
                    for s_num, ep_data in parsed_map.items():
                        if isinstance(ep_data, list):
                            episodes_data[int(s_num)] = sorted([int(e) for e in ep_data])
                        elif isinstance(ep_data, dict):
                            episodes_data[int(s_num)] = sorted([int(e) for e in ep_data.keys()])
                    if episodes_data:
                        return episodes_data
                except Exception:
                    pass

            soup = BeautifulSoup(raw_html, 'html.parser')
            season_tabs = soup.select(".b-simple_season__item") or soup.select("#simple-seasons-tabs li")
            seasons = [int(tab.get("data-season_id")) for tab in season_tabs if tab.get("data-season_id") and tab.get("data-season_id").isdigit()]
            if not seasons:
                seasons = [def_season]
                
            episode_tabs = soup.select(".b-simple_episode__item") or soup.select("#simple-episodes-tabs li")
            episodes = [int(tab.get("data-episode_id")) for tab in episode_tabs if tab.get("data-episode_id") and tab.get("data-episode_id").isdigit()]
            if not episodes:
                episodes = [def_episode]
                
            for s in sorted(seasons):
                episodes_data[s] = episodes
                
            if len(episodes_data) > 0:
                return episodes_data

        return {def_season: [def_episode]}

    def get_stream_url(self, post_id, translator_id, referer_url, season=1, episode=1):
        url = f"{self.base_url}/ajax/get_cdn_series/"
        payload = {
            "action": "get_episodes",
            "id": post_id,
            "translator_id": translator_id,
            "season": season,
            "episode": episode,
            "fav": "0",
            "vip": "0",
            "is_native": "0"
        }
        headers = self.headers.copy()
        headers["X-Requested-With"] = "XMLHttpRequest"
        headers["Referer"] = referer_url
        try:
            response = self.session.post(url, data=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                return None
            res_json = response.json()
            if not res_json.get("success"):
                return None
            return res_json.get("url", "")
        except Exception:
            return None
