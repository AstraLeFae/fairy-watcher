import os
import sys
import re
import json
import subprocess
from datetime import datetime
from rezka import RezkaAPI

HISTORY_FILE = "history.json"

def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")

def load_history():
    if not os.path.exists(HISTORY_FILE):
        return {"last_watched": None, "titles": {}}
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "titles" not in data:
                data["titles"] = {}
            return data
    except Exception:
        return {"last_watched": None, "titles": {}}

def save_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4, ensure_ascii=False)
    except Exception:
        pass

def parse_streams(streams_str):
    if not streams_str:
        return []
    result = []
    html_cleaner = re.compile(r'<[^>]*>')
    parts = streams_str.split(",[")
    for part in parts:
        part = part.lstrip("[")
        if "]" not in part:
            continue
        quality, urls_block = part.split("]", 1)
        clean_quality = html_cleaner.sub('', quality).strip()
        urls = urls_block.split(" or ")
        if urls:
            clean_url = urls[0].split(",")[0].strip()
            result.append({"quality": clean_quality, "url": clean_url})
    return result

def get_saved_time(history, url, trans_name, season, episode):
    ep_key = f"S{season}E{episode}"
    if url in history.get("titles", {}):
        if trans_name in history["titles"][url].get("translations", {}):
            if ep_key in history["titles"][url]["translations"][trans_name].get("episodes", {}):
                return history["titles"][url]["translations"][trans_name]["episodes"][ep_key].get("time_pos", 0.0)
    return 0.0

def update_history(history, url, title, trans_name, season, episode, time_pos):
    now = datetime.now().isoformat()
    if "titles" not in history:
        history["titles"] = {}
    if url not in history["titles"]:
        history["titles"][url] = {
            "title_name": title,
            "url": url,
            "translations": {}
        }
    history["titles"][url]["last_seen"] = now
    
    t_records = history["titles"][url]["translations"]
    if trans_name not in t_records:
        t_records[trans_name] = {
            "name": trans_name,
            "episodes": {}
        }
    t_records[trans_name]["last_seen"] = now
    
    ep_key = f"S{season}E{episode}"
    t_records[trans_name]["episodes"][ep_key] = {
        "season": season,
        "episode": episode,
        "time_pos": time_pos,
        "last_seen": now
    }
    
    history["last_watched"] = {
        "url": url,
        "translation": trans_name,
        "season": season,
        "episode": episode
    }
    save_history(history)

def play_mpv(stream_url, title, start_time):
    clear_screen()
    print(f"[►] Запускаю MPV... (Продолжаем с {start_time:.1f} сек)")
    cmd = [
        "mpv", stream_url,
        f"--title={title}",
        f"--start={start_time}",
        "--term-status-msg=MPV_EXIT_TIME=${=time-pos}"
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        last_pos = start_time
        while True:
            line = process.stdout.readline()
            if not line:
                break
            if "MPV_EXIT_TIME=" in line:
                try:
                    val = line.split("MPV_EXIT_TIME=")[1].strip()
                    if val and val != "unknown":
                        last_pos = float(val)
                except Exception:
                    pass
        process.wait()
        return last_pos
    except FileNotFoundError:
        print("[!] Ошибка: mpv не найден.")
        input("\nНажмите Enter...")
        return start_time

def read_menu_input(prompt):
    inp = input(prompt).strip()
    if inp.lower() == 'b':
        return "", True, False
    if inp.lower() == 'm':
        return "", False, True
    return inp, False, False

def menu_episode_control(api, info, target_url, title_name, trans_name, initial_season, initial_episode, history):
    is_movie = info["is_movie"]
    season = 1 if is_movie else initial_season
    episode = 1 if is_movie else initial_episode
    trans_data = info["translations"].get(trans_name, list(info["translations"].values())[0])
    
    while True:
        total_seasons = 0
        total_eps = 0
        episodes_map = {}
        
        if not is_movie:
            episodes_map = api.get_seasons_and_episodes(
                trans_data["post_id"], 
                trans_data["id"], 
                info["page_url"],
                def_season=info.get("def_season", 1),
                def_episode=info.get("def_episode", 1),
                raw_html=info.get("html", "")
            )
            
            if episodes_map:
                total_seasons = len(episodes_map)
                if season not in episodes_map:
                    season = sorted(list(episodes_map.keys()))[0]
                total_eps = len(episodes_map[season])
                if episode not in episodes_map[season]:
                    episode = episodes_map[season][0]
            else:
                total_seasons = 1
                total_eps = 1

        clear_screen()
        print("==========================================")
        print("       УПРАВЛЕНИЕ ТЕКУЩИМ СЕАНСОМ         ")
        print("==========================================")
        print(f"[Тайтл]:    {title_name}")
        print(f"[Озвучка]:  {trans_name}")
        
        if is_movie:
            print("[Формат]:   Фильм / Аниме-фильм")
        else:
            print(f"[Позиция]:  Сезон {season}, Серия {episode}")
            print(f"[Инфо]:     Всего сезонов: {total_seasons} | Серий в сезоне: {total_eps}")
            
        print("------------------------------------------")
        print(" 1. Запустить просмотр (Воспроизведение)")
        if not is_movie:
            print(" 2. Следующая серия (] )")
            print(" 3. Предыдущая серия ([ )")
            print(" 4. Выбрать другой эпизод (ввод номера)")
        print(" b. Назад")
        print(" m. Главное меню")
        print("==========================================")
        
        choice, back, to_main = read_menu_input("[>] Выберите действие: ")
        if back:
            return False
        if to_main:
            return True
            
        if choice == "1":
            raw_stream = ""
            if is_movie and info["streams"]:
                raw_stream = info["streams"]
            else:
                raw_stream = api.get_stream_url(trans_data["post_id"], trans_data["id"], info["page_url"], season, episode)
                
            available = parse_streams(raw_stream)
            if not available:
                print("[!] Потоки не найдены. Возможно, серия недоступна в этой озвучке.")
                input("\nНажмите Enter...")
                continue
                
            clear_screen()
            print("\nДоступное качество:")
            default_q = len(available)
            for i, s in enumerate(available, 1):
                print(f"  {i}) {s['quality']}")
                if s['quality'] == "1080p":
                    default_q = i
                    
            q_str, q_back, q_main = read_menu_input(f"\n[?] Выбери качество (по умолчанию {available[default_q-1]['quality']}): ")
            if q_back:
                continue
            if q_main:
                return True
                
            if q_str.isdigit():
                q_idx = int(q_str) - 1
                if 0 <= q_idx < len(available):
                    default_q = q_idx + 1
                    
            saved = get_saved_time(history, target_url, trans_name, season, episode)
            display_title = title_name if is_movie else f"{title_name} (S{season}E{episode})"
            
            final_time = play_mpv(available[default_q-1]["url"], display_title, saved)
            update_history(history, target_url, title_name, trans_name, season, episode, final_time)
            
            clear_screen()
            print(f"\n[✓] Прогресс сохранен: {final_time:.1f} сек")
            subprocess.run(["sleep", "1.5"])
            
        elif choice == "2" and not is_movie:
            if episodes_map and season in episodes_map:
                current_eps_list = episodes_map[season]
                curr_idx = current_eps_list.index(episode) if episode in current_eps_list else -1
                if curr_idx != -1 and curr_idx < len(current_eps_list) - 1:
                    episode = current_eps_list[curr_idx + 1]
                else:
                    seasons_list = sorted(list(episodes_map.keys()))
                    s_idx = seasons_list.index(season) if season in seasons_list else -1
                    if s_idx != -1 and s_idx < len(seasons_list) - 1:
                        season = seasons_list[s_idx + 1]
                        episode = episodes_map[season][0]
                    else:
                        print("[!] Это последняя серия последнего сезона.")
                        subprocess.run(["sleep", "1.0"])
            else:
                episode += 1
                
        elif choice == "3" and not is_movie:
            if episodes_map and season in episodes_map:
                current_eps_list = episodes_map[season]
                curr_idx = current_eps_list.index(episode) if episode in current_eps_list else -1
                if curr_idx > 0:
                    episode = current_eps_list[curr_idx - 1]
                else:
                    seasons_list = sorted(list(episodes_map.keys()))
                    s_idx = seasons_list.index(season) if season in seasons_list else -1
                    if s_idx > 0:
                        season = seasons_list[s_idx - 1]
                        episode = episodes_map[season][-1]
                    else:
                        print("[!] Это самая первая серия.")
                        subprocess.run(["sleep", "1.0"])
            else:
                if episode > 1:
                    episode -= 1
                    
        elif choice == "4" and not is_movie:
            ep_str, ep_back, ep_main = read_menu_input(f"[?] Введите номер серии (доступно {episodes_map.get(season, [episode])}): ")
            if ep_back:
                continue
            if ep_main:
                return True
            if ep_str.isdigit():
                ep_num = int(ep_str)
                if episodes_map and season in episodes_map:
                    if ep_num in episodes_map[season]:
                        episode = ep_num
                    else:
                        print("[!] Такой серии нет в этом сезоне!")
                        subprocess.run(["sleep", "1.0"])
                else:
                    episode = ep_num

def menu_search(api, history):
    while True:
        clear_screen()
        print("--- ПОИСК ТАЙТЛА ---")
        print("Введите 'b' для шага назад, 'm' для главного меню")
        query, back, to_main = read_menu_input("[?] Введи название: ")
        if back or to_main or not query:
            return
            
        results = api.search(query)
        if not results:
            print("[!] Ничего не найдено.")
            subprocess.run(["sleep", "1.5"])
            continue
            
        while True:
            clear_screen()
            print("Результаты поиска:")
            for i, res in enumerate(results, 1):
                clean_display_title = re.sub(r'\d+\.\d+$', '', res['title']).strip()
                print(f"  {i}) {clean_display_title}")
                
            c_str, c_back, c_main = read_menu_input("\n[?] Выбери тайтл (1): ")
            if c_back:
                break
            if c_main:
                return
                
            c_idx = int(c_str) - 1 if c_str.isdigit() else 0
            if c_idx < 0 or c_idx >= len(results):
                c_idx = 0
                
            target_url = results[c_idx]["url"]
            title_name = re.sub(r'\d+\.\d+$', '', results[c_idx]["title"]).strip()
            info = api.get_episodes(target_url)
            if not info["translations"]:
                print("[!] Ошибка загрузки видео.")
                subprocess.run(["sleep", "1.5"])
                continue
                
            while True:
                clear_screen()
                print("Доступные озвучки:")
                trans_list = list(info["translations"].keys())
                for i, t_name in enumerate(trans_list, 1):
                    print(f"  {i}) {t_name}")
                t_str, t_back, t_main = read_menu_input("\n[?] Выбери озвучку (1): ")
                if t_back:
                    break
                if t_main:
                    return
                    
                t_idx = int(t_str) - 1 if t_str.isdigit() else 0
                if t_idx < 0 or t_idx >= len(trans_list):
                    t_idx = 0
                trans_name = trans_list[t_idx]
                
                is_movie = info["is_movie"]
                selected_season = 1
                selected_episode = 1
                
                if not is_movie:
                    trans_data = info["translations"][trans_name]
                    ep_map = api.get_seasons_and_episodes(
                        trans_data["post_id"], 
                        trans_data["id"], 
                        info["page_url"],
                        def_season=info.get("def_season", 1),
                        def_episode=info.get("def_episode", 1),
                        raw_html=info.get("html", "")
                    )
                    
                    if ep_map:
                        clear_screen()
                        clean_title = re.sub(r'\d+\.\d+$', '', title_name).strip()
                        print(f"Доступные сезоны для '{clean_title}':")
                        seasons_list = sorted(list(ep_map.keys()))
                        for s_num in seasons_list:
                            print(f"  Сезон {s_num} (всего серий: {len(ep_map[s_num])})")
                        
                        s_str, s_back, s_main = read_menu_input(f"\n[?] Введите номер сезона ({seasons_list[0]}): ")
                        if s_back: break
                        if s_main: return
                        
                        if s_str.isdigit() and int(s_str) in ep_map:
                            selected_season = int(s_str)
                        else:
                            selected_season = seasons_list[0]
                            
                        print(f"Доступные серии в сезоне {selected_season}: {ep_map[selected_season]}")
                        
                        e_str, e_back, e_main = read_menu_input(f"[?] Введите номер серии ({ep_map[selected_season][0]}): ")
                        if e_back: break
                        if e_main: return
                        
                        if e_str.isdigit() and int(e_str) in ep_map[selected_season]:
                            selected_episode = int(e_str)
                        else:
                            selected_episode = ep_map[selected_season][0]
                
                if menu_episode_control(api, info, target_url, title_name, trans_name, selected_season, selected_episode, history):
                    return

def menu_history(api, history):
    while True:
        clear_screen()
        if not history.get("titles"):
            print("История пуста.")
            subprocess.run(["sleep", "1.5"])
            return
            
        titles = list(history["titles"].values())
        titles.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
        
        print("--- ИСТОРИЯ ПРОСМОТРОВ ---")
        for i, t in enumerate(titles, 1):
            date_str = t.get("last_seen", "").split("T")[0]
            print(f"  {i}) {t['title_name']} (Посл. просмотр: {date_str})")
            
        c_str, c_back, c_main = read_menu_input("\n[?] Выбери тайтл (или b/m): ")
        if c_back or c_main or not c_str:
            return
            
        c_idx = int(c_str) - 1 if c_str.isdigit() else -1
        if 0 <= c_idx < len(titles):
            selected_title = titles[c_idx]
            info = api.get_episodes(selected_title["url"])
            is_movie = info["is_movie"]
            
            while True:
                clear_screen()
                translations = list(selected_title.get("translations", {}).values())
                translations.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
                
                print("История озвучек для этого тайтла:")
                for i, t in enumerate(translations, 1):
                    print(f"  {i}) {t['name']}")
                    
                tc_str, tc_back, tc_main = read_menu_input("\n[?] Выбери озвучку (1): ")
                if tc_back:
                    break
                if tc_main:
                    return
                    
                tc_idx = int(tc_str) - 1 if tc_str.isdigit() else 0
                if 0 <= tc_idx < len(translations):
                    selected_trans = translations[tc_idx]
                    
                    if is_movie:
                        if menu_episode_control(api, info, selected_title["url"], selected_title["title_name"], selected_trans["name"], 1, 1, history):
                            return
                    else:
                        while True:
                            clear_screen()
                            episodes = list(selected_trans.get("episodes", {}).values())
                            episodes.sort(key=lambda x: x.get("last_seen", ""), reverse=True)
                            
                            print("Просмотренные ранее серии:")
                            for i, e in enumerate(episodes, 1):
                                print(f"  {i}) Сезон {e['season']}, Серия {e['episode']} (Остановка: {e['time_pos']:.0f} сек)")
                                
                            ec_str, ec_back, ec_main = read_menu_input("\n[?] Выбери серию для перехода в хаб (1): ")
                            if ec_back:
                                break
                            if ec_main:
                                return
                                
                            ec_idx = int(ec_str) - 1 if ec_str.isdigit() else 0
                            if 0 <= ec_idx < len(episodes):
                                selected_ep = episodes[ec_idx]
                                if menu_episode_control(api, info, selected_title["url"], selected_title["title_name"], selected_trans["name"], selected_ep["season"], selected_ep["episode"], history):
                                    return

def main():
    history = load_history()
    api = RezkaAPI()
    
    while True:
        clear_screen()
        print("=== ГЛАВНОЕ МЕНЮ ===")
        print("1. Поиск")
        print("2. История")
        if history.get("last_watched"):
            print("3. Продолжить последний просмотр")
        print("0. Выход")
        
        choice = input("[>] Выбор: ").strip()
        if choice == "1":
            menu_search(api, history)
        elif choice == "2":
            menu_history(api, history)
        elif choice == "3" and history.get("last_watched"):
            lw = history["last_watched"]
            if lw["url"] in history.get("titles", {}):
                title = history["titles"][lw["url"]]["title_name"]
                info = api.get_episodes(lw["url"])
                menu_episode_control(api, info, lw["url"], title, lw["translation"], lw["season"], lw["episode"], history)
        elif choice == "0":
            clear_screen()
            print("Пока!")
            sys.exit(0)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        print("\nПриложение принудительно завершено. Пока!")
        sys.exit(0)
