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
