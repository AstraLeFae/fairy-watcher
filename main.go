package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"net/url"
	"os"
	"os/exec"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/n0madic/go-hdrezka"
)

const historyFile = "history.json"

type EpisodeRecord struct {
	Season   int       `json:"season"`
	Episode  int       `json:"episode"`
	TimePos  float64   `json:"time_pos"`
	LastSeen time.Time `json:"last_seen"`
}

type TranslationRecord struct {
	Name     string                    `json:"name"`
	LastSeen time.Time                 `json:"last_seen"`
	Episodes map[string]*EpisodeRecord `json:"episodes"`
}

type TitleRecord struct {
	TitleName    string                        `json:"title_name"`
	URL          string                        `json:"url"`
	LastSeen     time.Time                     `json:"last_seen"`
	Translations map[string]*TranslationRecord `json:"translations"`
}

type LastWatched struct {
	URL         string `json:"url"`
	Translation string `json:"translation"`
	Season      int    `json:"season"`
	Episode     int    `json:"episode"`
}

type History struct {
	LastWatched *LastWatched            `json:"last_watched"`
	Titles      map[string]*TitleRecord `json:"titles"`
}

var appHistory History
var reader = bufio.NewReader(os.Stdin)

// Функция для очистки экрана терминала
func clearScreen() {
	fmt.Print("\033[H\033[2J")
	cmd := exec.Command("clear")
	cmd.Stdout = os.Stdout
	cmd.Run()
}

func loadHistory() {
	appHistory = History{Titles: make(map[string]*TitleRecord)}
	data, err := os.ReadFile(historyFile)
	if err == nil {
		json.Unmarshal(data, &appHistory)
	}
	if appHistory.Titles == nil {
		appHistory.Titles = make(map[string]*TitleRecord)
	}
}

func saveHistory() {
	data, _ := json.MarshalIndent(appHistory, "", "  ")
	os.WriteFile(historyFile, data, 0644)
}

func updateHistory(url, title, transName string, season, episode int, timePos float64) {
	now := time.Now()

	if _, ok := appHistory.Titles[url]; !ok {
		appHistory.Titles[url] = &TitleRecord{
			TitleName:    title,
			URL:          url,
			Translations: make(map[string]*TranslationRecord),
		}
	}
	titleRec := appHistory.Titles[url]
	titleRec.LastSeen = now

	if _, ok := titleRec.Translations[transName]; !ok {
		titleRec.Translations[transName] = &TranslationRecord{
			Name:     transName,
			Episodes: make(map[string]*EpisodeRecord),
		}
	}
	transRec := titleRec.Translations[transName]
	transRec.LastSeen = now

	epKey := fmt.Sprintf("S%dE%d", season, episode)
	if _, ok := transRec.Episodes[epKey]; !ok {
		transRec.Episodes[epKey] = &EpisodeRecord{Season: season, Episode: episode}
	}
	epRec := transRec.Episodes[epKey]
	epRec.TimePos = timePos
	epRec.LastSeen = now

	appHistory.LastWatched = &LastWatched{
		URL:         url,
		Translation: transName,
		Season:      season,
		Episode:     episode,
	}
	saveHistory()
}

func getSavedTime(url, transName string, season, episode int) float64 {
	epKey := fmt.Sprintf("S%dE%d", season, episode)
	if t, ok := appHistory.Titles[url]; ok {
		if tr, ok := t.Translations[transName]; ok {
			if ep, ok := tr.Episodes[epKey]; ok {
				return ep.TimePos
			}
		}
	}
	return 0
}

type QualityStream struct {
	Quality string
	URL     string
}

func parseStreamURLs(raw string) []QualityStream {
	var streams []QualityStream
	re := regexp.MustCompile(`\[([^\]]+)\](https?://[^,]+)`)
	matches := re.FindAllStringSubmatch(raw, -1)
	htmlRe := regexp.MustCompile(`<[^>]*>`)

	for _, match := range matches {
		if len(match) < 3 {
			continue
		}
		q := strings.TrimSpace(htmlRe.ReplaceAllString(match[1], ""))
		urls := strings.Split(match[2], " or ")
		if len(urls) > 0 {
			streams = append(streams, QualityStream{Quality: q, URL: strings.TrimSpace(urls[0])})
		}
	}
	return streams
}

func playMPV(streamURL, title string, startTime float64) float64 {
	clearScreen()
	fmt.Printf("[►] Запускаю MPV... (Продолжаем с %.1f сек)\n", startTime)

	cmd := exec.Command("mpv", streamURL,
		"--title="+title,
		fmt.Sprintf("--start=%f", startTime),
		"--term-status-msg=MPV_EXIT_TIME=${=time-pos}",
	)

	var outBuf bytes.Buffer
	cmd.Stdout = &outBuf
	cmd.Stderr = os.Stderr

	cmd.Run()

	outStr := outBuf.String()
	re := regexp.MustCompile(`MPV_EXIT_TIME=([\d\.]+)`)
	matches := re.FindAllStringSubmatch(outStr, -1)
	
	if len(matches) > 0 {
		lastMatch := matches[len(matches)-1]
		if t, err := strconv.ParseFloat(lastMatch[1], 64); err == nil {
			return t
		}
	}
	return startTime
}

func readMenuInput(prompt string) (string, bool, bool) {
	fmt.Print(prompt)
	input, _ := reader.ReadString('\n')
	input = strings.TrimSpace(input)
	
	if strings.ToLower(input) == "b" {
		return "", true, false
	}
	if strings.ToLower(input) == "m" {
		return "", false, true
	}
	return input, false, false
}

func menuEpisodeControl(client *hdrezka.HDRezka, video *hdrezka.Video, targetURL, titleName, transName string, initialSeason, initialEpisode int) bool {
	season := initialSeason
	episode := initialEpisode

	for {
		clearScreen()
		fmt.Println("==========================================")
		fmt.Println("       УПРАВЛЕНИЕ ТЕКУЩИМ СЕАНСОМ         ")
		fmt.Println("==========================================")
		fmt.Printf("[Тайтл]:    %s\n", titleName)
		fmt.Printf("[Озвучка]:  %s\n", transName)
		
		var totalEps int
		var totalSeasons int
		var isMovie bool = true

		var activeTrans *hdrezka.Translation
		for _, t := range video.Translation {
			if t.Name == transName {
				activeTrans = t
				break
			}
		}
		if activeTrans == nil {
			activeTrans = video.Translation[0]
		}

		episodesMap, _ := activeTrans.GetEpisodes()
		if len(episodesMap) > 0 {
			isMovie = false
			totalSeasons = len(episodesMap)
			if season == 0 { 
				season = 1 
			}
			if seasonEps, ok := episodesMap[season]; ok {
				totalEps = len(seasonEps)
			}
		}

		if isMovie {
			fmt.Println("[Формат]:   Фильм / Аниме-фильм")
		} else {
			fmt.Printf("[Позиция]:  Сезон %d, Серия %d\n", season, episode)
			fmt.Printf("[Инфо]:     Всего сезонов: %d | Серий в текущем сезоне: %d\n", totalSeasons, totalEps)
		}
		fmt.Println("------------------------------------------")
		fmt.Println(" 1. Запустить просмотр (Воспроизведение)")
		
		if !isMovie {
			fmt.Println(" 2. Следующая серия (] )")
			fmt.Println(" 3. Предыдущая серия ([ )")
			fmt.Println(" 4. Выбрать другой эпизод (ввод номера)")
		}
		fmt.Println(" b. Назад (К выбору серий/озвучек)")
		fmt.Println(" m. Главное меню")
		fmt.Println("==========================================")

		choice, back, main := readMenuInput("[>] Выберите действие: ")
		if back { return false } 
		if main { return true }  

		switch choice {
		case "1":
			var rawStreamURL string
			if !isMovie {
				fmt.Printf("[!] Запрашиваю поток для %d сезона, %d серии...\n", season, episode)
				stream, err := activeTrans.GetStream(season, episode)
				if err != nil {
					fmt.Printf(" Ошибка запроса потока: %v\n", err)
					time.Sleep(2 * time.Second)
					continue
				}
				rawStreamURL = stream.URL
			} else {
				fmt.Println("[!] Запрашиваю поток для фильма...")
				stream, err := activeTrans.GetStream()
				if err != nil {
					fmt.Printf(" Ошибка запроса потока: %v\n", err)
					time.Sleep(2 * time.Second)
					continue
				}
				rawStreamURL = stream.URL
			}

			availableStreams := parseStreamURLs(rawStreamURL)
			if len(availableStreams) == 0 {
				fmt.Println("Потоки не найдены.")
				time.Sleep(2 * time.Second)
				continue
			}

			clearScreen()
			fmt.Println("\nДоступное качество:")
			defaultQ := len(availableStreams)
			for i, s := range availableStreams {
				fmt.Printf("  %d) %s\n", i+1, s.Quality)
				if s.Quality == "1080p" {
					defaultQ = i + 1
				}
			}

			qStr, qBack, qMain := readMenuInput(fmt.Sprintf("\n[?] Выбери качество (по умолчанию %s): ", availableStreams[defaultQ-1].Quality))
			if qBack { continue }
			if qMain { return true }

			if q, err := strconv.Atoi(qStr); err == nil && q > 0 && q <= len(availableStreams) {
				defaultQ = q
			}

			savedTime := getSavedTime(targetURL, activeTrans.Name, season, episode)
			finalTime := playMPV(availableStreams[defaultQ-1].URL, titleName, savedTime)

			updateHistory(targetURL, titleName, activeTrans.Name, season, episode, finalTime)
			clearScreen()
			fmt.Printf("\n[✓] Прогресс сохранен: %.1f сек\n", finalTime)
			time.Sleep(1500 * time.Millisecond)

		case "2":
			if isMovie { continue }
			if episode < totalEps {
				episode++
			} else if season < totalSeasons {
				season++
				episode = 1
			} else {
				fmt.Println("[!] Это была последняя серия последнего сезона!")
				time.Sleep(1 * time.Second)
			}

		case "3":
			if isMovie { continue }
			if episode > 1 {
				episode--
			} else if season > 1 {
				season--
				if prevSeasonEps, ok := episodesMap[season]; ok {
					episode = len(prevSeasonEps)
				} else {
					episode = 1
				}
			} else {
				fmt.Println("[!] Это самый первый эпизод!")
				time.Sleep(1 * time.Second)
			}

		case "4":
			if isMovie { continue }
			fmt.Printf("[?] Введите номер серии (1-%d): ", totalEps)
			epStr, epBack, epMain := readMenuInput("")
			if epBack { continue }
			if epMain { return true }

			if epNum, err := strconv.Atoi(epStr); err == nil && epNum > 0 && epNum <= totalEps {
				episode = epNum
			} else {
				fmt.Println("[!] Неверный номер серии.")
				time.Sleep(1 * time.Second)
			}
		}
	}
}

func menuSearch(client *hdrezka.HDRezka) {
	for {
		clearScreen()
		fmt.Println("--- ПОИСК ТАЙТЛА ---")
		fmt.Println("Введите 'b' для шага назад, 'm' для главного меню")
		query, back, main := readMenuInput("[?] Введи название: ")
		if back || main || query == "" { return }

		results, err := client.Search(query, 5)
		if err != nil || len(results) == 0 {
			fmt.Println("Ничего не найдено.")
			time.Sleep(1500 * time.Millisecond)
			continue
		}

		for {
			clearScreen()
			fmt.Println("Результаты поиска:")
			for i, res := range results {
				fmt.Printf("  %d) %s\n", i+1, res.Title)
			}
			cStr, cBack, cMain := readMenuInput("\n[?] Выбери тайтл (1): ")
			if cBack { break } 
			if cMain { return }

			c, _ := strconv.Atoi(cStr)
			if c < 1 || c > len(results) { c = 1 }

			targetURL := results[c-1].URL
			titleName := results[c-1].Title
			video, err := client.GetVideo(targetURL)
			if err != nil {
				fmt.Println("Ошибка загрузки видео.")
				time.Sleep(1500 * time.Millisecond)
				continue
			}

			for {
				clearScreen()
				fmt.Println("Доступные озвучки:")
				for i, trans := range video.Translation {
					fmt.Printf("  %d) %s\n", i+1, trans.Name)
				}
				tStr, tBack, tMain := readMenuInput("\n[?] Выбери озвучку (1): ")
				if tBack { break } 
				if tMain { return }

				tc, _ := strconv.Atoi(tStr)
				if tc < 1 || tc > len(video.Translation) { tc = 1 }
				transName := video.Translation[tc-1].Name

				episodes, _ := video.Translation[tc-1].GetEpisodes()
				season, episode := 0, 0
				
				if len(episodes) > 0 {
					var availableSeasons []int
					for s := range episodes {
						availableSeasons = append(availableSeasons, s)
					}
					sort.Ints(availableSeasons)

					var seasonsStr []string
					for _, s := range availableSeasons {
						seasonsStr = append(seasonsStr, strconv.Itoa(s))
					}

					for {
						clearScreen()
						fmt.Printf("[i] Доступные сезоны: %s (Всего: %d)\n", strings.Join(seasonsStr, ", "), len(episodes))
						sStr, sBack, sMain := readMenuInput("[?] Введи номер сезона: ")
						if sBack { break }
						if sMain { return }

						if sStr == "" && len(availableSeasons) > 0 { 
							season = availableSeasons[0] 
						} else {
							season, _ = strconv.Atoi(sStr)
						}

						seasonEps, ok := episodes[season]
						if !ok {
							fmt.Println("[!] Сезон не найден в списке доступных.")
							time.Sleep(1500 * time.Millisecond)
							continue
						}

						for {
							clearScreen()
							fmt.Printf("[i] В %d-м сезоне найдено серий: %d\n", season, len(seasonEps))
							eStr, eBack, eMain := readMenuInput("[?] Введи номер серии (1): ")
							if eBack { break }
							if eMain { return }

							if eStr == "" { eStr = "1" }
							episode, _ = strconv.Atoi(eStr)
							if episode < 1 || episode > len(seasonEps) {
								fmt.Println("[!] Неверный номер серии.")
								time.Sleep(1500 * time.Millisecond)
								continue
							}

							goToMain := menuEpisodeControl(client, video, targetURL, titleName, transName, season, episode)
							if goToMain { return }
						}
					}
				} else {
					goToMain := menuEpisodeControl(client, video, targetURL, titleName, transName, season, episode)
					if goToMain { return }
				}
			}
		}
	}
}

func menuHistory(client *hdrezka.HDRezka) {
	for {
		clearScreen()
		if len(appHistory.Titles) == 0 {
			fmt.Println("История пуста.")
			time.Sleep(1500 * time.Millisecond)
			return
		}

		var titles []*TitleRecord
		for _, t := range appHistory.Titles {
			titles = append(titles, t)
		}
		sort.Slice(titles, func(i, j int) bool { return titles[i].LastSeen.After(titles[j].LastSeen) })

		fmt.Println("--- ИСТОРИЯ ПРОСМОТРОВ ---")
		for i, t := range titles {
			fmt.Printf("  %d) %s (Посл. просмотр: %s)\n", i+1, t.TitleName, t.LastSeen.Format("02.01 15:04"))
		}
		cStr, cBack, cMain := readMenuInput("\n[?] Выбери тайтл (или b/m): ")
		if cBack || cMain || cStr == "" { return }

		c, _ := strconv.Atoi(cStr)
		if c < 1 || c > len(titles) { continue }
		selectedTitle := titles[c-1]

		video, err := client.GetVideo(selectedTitle.URL)
		if err != nil {
			fmt.Println("Ошибка получения данных с сервера Rezka.")
			time.Sleep(1500 * time.Millisecond)
			continue
		}

		for {
			clearScreen()
			var trans []*TranslationRecord
			for _, t := range selectedTitle.Translations {
				trans = append(trans, t)
			}
			sort.Slice(trans, func(i, j int) bool { return trans[i].LastSeen.After(trans[j].LastSeen) })

			fmt.Println("История озвучек для этого тайтла:")
			for i, t := range trans {
				fmt.Printf("  %d) %s\n", i+1, t.Name)
			}
			tcStr, tcBack, tcMain := readMenuInput("\n[?] Выбери озвучку (1): ")
			if tcBack { break }
			if tcMain { return }

			tc, _ := strconv.Atoi(tcStr)
			if tc < 1 || tc > len(trans) { tc = 1 }
			selectedTrans := trans[tc-1]

			for {
				clearScreen()
				var eps []*EpisodeRecord
				for _, e := range selectedTrans.Episodes {
					eps = append(eps, e)
				}
				sort.Slice(eps, func(i, j int) bool { return eps[i].LastSeen.After(eps[j].LastSeen) })

				fmt.Println("Просмотренные ранее серии:")
				for i, e := range eps {
					fmt.Printf("  %d) Сезон %d, Серия %d (Остановка: %.0f сек)\n", i+1, e.Season, e.Episode, e.TimePos)
				}
				ecStr, ecBack, ecMain := readMenuInput("\n[?] Выбери серию для перехода в хаб (1): ")
				if ecBack { break }
				if ecMain { return }

				ec, _ := strconv.Atoi(ecStr)
				if ec < 1 || ec > len(eps) { ec = 1 }
				selectedEp := eps[ec-1]

				goToMain := menuEpisodeControl(client, video, selectedTitle.URL, selectedTitle.TitleName, selectedTrans.Name, selectedEp.Season, selectedEp.Episode)
				if goToMain { return }
			}
		}
	}
}

func main() {
	loadHistory()

	client := hdrezka.New()
	parsedURL, _ := url.Parse("https://hdrezka.ag")
	client.URL = parsedURL
	clearScreen()
	fmt.Printf("[✓] Подключено к зеркалу: %s\n", client.URL.String())
	time.Sleep(1 * time.Second)

	for {
		clearScreen()
		fmt.Println("=== ГЛАВНОЕ МЕНЮ ===")
		fmt.Println("1. Поиск")
		fmt.Println("2. История")
		if appHistory.LastWatched != nil {
			fmt.Println("3. Продолжить последний просмотр")
		}
		fmt.Println("0. Выход")
		fmt.Print("[>] Выбор: ")

		choiceStr, _ := reader.ReadString('\n')
		switch strings.TrimSpace(choiceStr) {
		case "1":
			menuSearch(client)
		case "2":
			menuHistory(client)
		case "3":
			if appHistory.LastWatched != nil {
				lw := appHistory.LastWatched
				title := appHistory.Titles[lw.URL].TitleName
				video, err := client.GetVideo(lw.URL)
				if err == nil {
					menuEpisodeControl(client, video, lw.URL, title, lw.Translation, lw.Season, lw.Episode)
				} else {
					fmt.Println("Не удалось возобновить поток.")
					time.Sleep(1500 * time.Millisecond)
				}
			}
		case "0":
			clearScreen()
			fmt.Println("Пока!")
			return
		}
	}
}
