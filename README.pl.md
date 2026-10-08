# Instagram Watcher

[English](README.md) | [Polski]

Niezawodne narzędzie wiersza poleceń (CLI) w języku Python oparte na bibliotece `yt-dlp`, `curl-cffi` oraz `imageio-ffmpeg`, służące do monitorowania profili na Instagramie i pobierania postów (zdjęcia, karuzele, wideo, Reels) w najwyższej dostępnej rozdzielczości i jakości.

---

## Dwa tryby działania programu

Aplikacja wspiera dwa odrębne tryby pracy w zależności od tego, czy dostarczono plik ciasteczek uwierzytelniających:

```
┌────────────────────────────────────────────────────────────────────────┐
│  Tryb 1: Anonimowy / Bez logowania (Domyślny)                          │
│  • Brak konieczności posiadania konta na Instagramie                   │
│  • Maksymalnie 12 najnowszych postów na profil (limit siatki IG)       │
│  • Idealny do cyklicznego monitorowania (cron / Harmonogram zadań)     │
│  • Polecenie: python instagram_watcher.py -p <profil> --limit 5        │
├────────────────────────────────────────────────────────────────────────┤
│  Tryb 2: Uwierzytelniony / Z ciasteczkami (--cookies)                  │
│  • Całkowicie znosi limit 12 postów                                    │
│  • Pełne stronicowanie GraphQL (możliwość pobrania 50, 200+ postów)    │
│  • Idealny do archiwizacji głębokiej historii wpisów profilu           │
│  • Polecenie: python instagram_watcher.py -p <profil> -l 50 --cookies  │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. Tryb anonimowy (Domyślny — brak konta)
* **Zasada działania:** Skrypt odpytuje publiczny widok profilu z impersonacją odcisków palców TLS przeglądarki Chrome (`curl-cffi`).
* **Ograniczenie do 12 postów:** Architektura Instagrama serwuje w publicznym kodzie HTML wyłącznie **pierwszą stronę (12 postów)**. Wszystkie zapytania o starsze posty (strona 2 i kolejne) bez poświadczeń sesji są celowo odrzucane przez mechanizm Meta (`HTTP 401 / require_login`).
* **Dlaczego to idealne rozwiązanie dla Watchera:** Przy cyklicznym uruchamianiu (np. codziennie w Harmonogramie zadań Windows lub cronie) każdy nowy post pojawia się zawsze na samej górze siatki profilu. Watcher automatycznie pobierze nowe multimedia bez konieczności logowania, posiadania konta czy ryzyka jakiejkolwiek blokady.

### 2. Tryb uwierzytelniony (`--cookies`)
* **Zasada działania:** Wykorzystuje ciasteczka sesji do komunikacji z wewnętrznym punktem GraphQL Instagrama (`PolarisProfilePostsTabContentQuery_connection`).
* **Brak limitu postów:** Obsługuje kursory stronicowania (`end_cursor`, `has_next_page`), pobierając kolejne paczki postów aż do zadanego limitu `--limit` (dziesiątki, setki lub tysiące wpisów).
* **Ochrona przed rate-limit:** Pomiędzy kolejnymi stronami wprowadzane jest automatyczne, konfigurowalne opóźnienie (`--page-delay`, domyślnie 1.5 sekundy).
* **Obsługiwane formaty:** Standardowy plik Netscape `cookies.txt` (wyeksportowany z przeglądarki) lub bezpośredni ciąg sesyjny (`"sessionid=..."`).

---

## Struktura katalogów pobierania

Pobrane pliki są automatycznie segregowane do przejrzystych podkatalogów:

```text
downloads/<nazwa_profilu>/
├── images/
│   ├── <shortcode>.jpg          # Pojedyncze zdjęcia w pełnej rozdzielczości
│   ├── <shortcode>_1.jpg        # Slajdy karuzeli/galerii (bez duplikatów)
│   └── <shortcode>_2.jpg
├── videos/
│   ├── <shortcode>.mp4          # Filmy i Reels (wideo + scalone audio DASH)
│   └── <shortcode>_1.mp4        # Slajdy wideo wewnątrz karuzeli
└── archive.txt                  # Archiwum pobrań yt-dlp dla danego profilu
```

---

## Kluczowe możliwości i architektura

- **Omijanie blokad 429 i wymuszonego logowania:** Wykorzystanie `curl-cffi` z impersonacją TLS Chrome umożliwia pobieranie danych bez uruchamiania zabezpieczeń antyscrapingowych.
- **Maksymalna jakość wideo i audio:** Instagram serwuje strumienie wideo i audio oddzielnie (DASH). Dzięki wbudowanemu `imageio-ffmpeg`, `yt-dlp` bezstratnie scala je w pełnowymiarowy plik `.mp4`.
- **Maksymalna rozdzielczość grafik:** Skrypt odpytuje dedykowane metadane postów i pobiera oryginalne, nieprzeskalowane obrazy, logując ich rozdzielczość za pomocą `Pillow` (np. 3024x4032 px).
- **Deduplikacja karuzel:** Poszczególne slajdy galerii zapisywane są z unikalnymi numerami (`_1`, `_2`), bez powielania tych samych plików.
- **Trwała baza pobrań:** Zapis identyfikatorów w `downloaded_posts.json` oraz `archive.txt`. Gdy skrypt napotka post pobrany w poprzednim uruchomieniu, natychmiast zatrzymuje przeszukiwanie, oszczędzając łącze i zapytania do API.

---

## Instalacja

1. **Aktywacja środowiska wirtualnego:**
   - Windows PowerShell:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

2. **Instalacja zależności:**
   ```bash
   pip install -r requirements.txt
   ```

---

## Przykłady użycia

### 1. Monitorowanie anonimowe (do 12 najnowszych postów)

Pobranie 5 najnowszych postów z profilu:
```powershell
python instagram_watcher.py --profile nasa --limit 5
```

Pobranie przy użyciu pełnego adresu URL:
```powershell
python instagram_watcher.py --profile https://www.instagram.com/nasa/ --limit 12
```

### 2. Pobieranie dużych archiwów z plikiem cookies (powyżej 12 postów)

Przy użyciu wyeksportowanego pliku `cookies.txt`:
```powershell
python instagram_watcher.py --profile corinavitor --limit 50 --cookies cookies.txt
```

Przy użyciu tokenu sesji w wierszu poleceń:
```powershell
python instagram_watcher.py --profile corinavitor --limit 100 --cookies "sessionid=TWOJ_SESSION_ID"
```

Dostosowanie opóźnienia między stronami profilu (np. 2 sekundy):
```powershell
python instagram_watcher.py --profile corinavitor --limit 150 --cookies cookies.txt --page-delay 2.0
```

> [!TIP]
> **Jak wyeksportować `cookies.txt`:** Zainstaluj rozszerzenie do przeglądarki (np. *Get cookies.txt LOCALLY* dla Chrome/Firefox/Edge), zaloguj się na Instagram i wyeksportuj plik ciasteczek dla domeny `instagram.com` pod nazwą `cookies.txt` do głównego katalogu projektu. Plik ten jest automatycznie ignorowany przez `.gitignore`.

---

## Opcje wiersza poleceń

| Parametr | Skrót | Opis | Wartość domyślna |
| :--- | :--- | :--- | :--- |
| `--profile` | `-p` | Nazwa użytkownika lub pełny URL profilu (wymagany) | *Brak* |
| `--limit` | `-l` | Maksymalna liczba nowych postów do pobrania | `1` |
| `--download-dir` | | Folder docelowy dla pobieranych multimediów | `downloads` |
| `--db-file` | | Plik JSON z historią pobranych identyfikatorów | `downloaded_posts.json` |
| `--page-delay` | | Opóźnienie (w sekundach) między kolejnymi stronami | `1.5` |
| `--cookies` | | Opcjonalny token sesji lub ścieżka do pliku `cookies.txt` | *Brak* |

---

## Testy

Uruchomienie pełnego zestawu testów jednostkowych (18 testów):
```powershell
pytest -v
```
