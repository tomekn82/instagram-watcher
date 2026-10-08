# Instagram Watcher

[English](README.md) | [Polski]

Narzędzie wiersza poleceń (CLI) w języku Python oparte na bibliotece `yt-dlp`, `curl-cffi` oraz `imageio-ffmpeg`, służące do monitorowania publicznego profilu na Instagramie i automatycznego pobierania nowych postów w maksymalnej dostępnej jakości bez konieczności posiadania konta.

## Struktura katalogów pobierania
Wszystkie pobierane multimedia są automatycznie kategoryzowane do podkatalogów:
```text
downloads/<nazwa_profilu>/
├── images/
│   ├── <shortcode>.jpg          # Pojedyncze zdjęcia w pełnej rozdzielczości
│   ├── <shortcode>_1.jpg        # Slajdy karuzeli/galerii (bez duplikatów)
│   └── <shortcode>_2.jpg
├── videos/
│   ├── <shortcode>.mp4          # Filmy, Reels (wideo + scalone audio DASH)
│   └── <shortcode>_1.mp4        # Slajdy wideo wewnątrz karuzeli
└── archive.txt                  # Archiwum pobrań dla profilu
```

## Dlaczego yt-dlp + curl-cffi + imageio-ffmpeg?
- **Omijanie blokad 429 i wymuszonego logowania:** Wykorzystanie `curl-cffi` z impersonacją TLS przeglądarki Chrome pozwala na pobieranie danych i metadanych z publicznych profili bez konta na Instagramie.
- **Maksymalna jakość wideo i audio:** Instagram serwuje najwyższej jakości strumienie wideo i audio oddzielnie (DASH). Dzięki wbudowanemu `imageio-ffmpeg`, `yt-dlp` bezbłędnie scala je w pełnowymiarowy plik `.mp4`.
- **Maksymalna rozdzielczość grafik:** Skrypt odpytuje dedykowane widoki postów (`/p/<shortcode>/`) i wybiera oryginalne, nieprzeskalowane pliki, weryfikując i logując ich wymiary w pikselach za pomocą biblioteki `Pillow`.
- **Brak duplikatów:** Slajdy galerii zapisywane są wyłącznie raz jako ponumerowane pliki (`_1`, `_2`...).

## Instalacja

1. Aktywacja środowiska wirtualnego:
   - Windows PowerShell:
     ```powershell
     .\venv\Scripts\Activate.ps1
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

2. Instalacja zależności:
   ```bash
   pip install -r requirements.txt
   ```

## Użycie

Wyświetlenie pomocy:
```powershell
python instagram_watcher.py --help
```

Pobieranie najnowszych materiałów z profilu (np. NASA):
```powershell
python instagram_watcher.py --profile nasa --limit 5
```

Użycie z pełnym adresem URL:
```powershell
python instagram_watcher.py --profile https://www.instagram.com/nasa/ --limit 5
```

## Ważne: Działanie bez logowania i limit 12 postów

Instagram stosuje tzw. **Login Wall** dla niezalogowanych użytkowników:
- **Domyślny tryb bez konta (brak logowania):** W kodzie źródłowym strony profilu Instagram serwuje wyłącznie **12 najnowszych postów**. Każda próba pobrania starszych wpisów (strony 2 i kolejnych) bez poświadczeń sesji jest celowo blokowana przez serwery Meta (`HTTP 401 / require_login`).
- **Dlaczego to w zupełności wystarcza dla Watchera:** Przy cyklicznym monitorowaniu profilu (np. uruchamianym codziennie lub co kilka dni) limit ten nie stanowi przeszkody. Każdy nowy post pojawia się zawsze na samej górze siatki (wśród pierwszych 12 kafelków) i zostanie automatycznie pobrany w pełnej rozdzielczości bez konieczności logowania czy posiadania konta.
- **Pobieranie głębokiego archiwum wstecz (opcjonalnie):** Jeśli w przyszłości zechcesz jednorazowo pobrać więcej niż 12 historycznych postów z danego profilu, możesz przekazać ciasteczka sesji (np. z dowolnego darmowego konta testowego / burner) za pomocą parametru `--cookies`:
  ```powershell
  python instagram_watcher.py --profile nasa --limit 50 --cookies "sessionid=TWOJ_SESSIONID"
  ```
  lub wskazując wyeksportowany plik Netscape cookies:
  ```powershell
  python instagram_watcher.py --profile nasa --limit 50 --cookies cookies.txt
  ```

## Opcje wiersza poleceń

| Parametr | Opis | Wartość domyślna |
| :--- | :--- | :--- |
| `--profile`, `-p` | Nazwa użytkownika lub pełny URL profilu (wymagany) | *Brak* |
| `--limit`, `-l` | Maksymalna liczba nowych postów do pobrania | `1` |
| `--download-dir` | Folder docelowy dla pobieranych multimediów | `downloads` |
| `--db-file` | Plik JSON z historią pobranych identyfikatorów | `downloaded_posts.json` |
| `--page-delay` | Opóźnienie (w sekundach) między kolejnymi stronami | `1.5` |
| `--cookies` | Opcjonalny token sesji lub ścieżka do pliku `cookies.txt` | *Brak* |

## Testy

Uruchomienie zestawu testów jednostkowych:
```powershell
pytest -v
```

