# sr-play

Kompletterande RSS-flöde för `P3 Historia`.

Projektet bygger ett eget `feed.xml` som utgår från Sveriges Radios vanliga podd-RSS och fyller på med publika avsnitt som finns på webben men saknas i originalflödet.

## Vad som finns här

- `scripts/build_feed.py` bygger `docs/feed.xml`
- `docs/feed.xml` är den genererade RSS-filen
- `docs/index.html` är en enkel landningssida för GitHub Pages
- `.github/workflows/build-feed.yml` uppdaterar feeden automatiskt varje torsdag kl. 12:00 i `Europe/Stockholm` samt vid manuell körning

## Lokal körning

```bash
python3 scripts/build_feed.py
```

Det skriver ut en uppdaterad feed till `docs/feed.xml`.

## Publicering

Aktivera GitHub Pages för repot med:

- branch: `main`
- folder: `/docs`

När Pages är aktiverat blir feeden tillgänglig på:

```text
https://gusost.github.io/sr-play/feed.xml
```

## Hur feeden byggs

1. Läs SR:s podd-RSS: `https://api.sr.se/api/rss/pod/23791`
2. Hämta alla publika avsnitt från `https://www.sverigesradio.se/p3historia`
3. Fortsätt via SR:s publika `show more`-endpoint tills inga fler avsnitt returneras
4. Lägg till avsnitt som saknas i original-RSS
5. Använd avsnittssidan som fallback när listningen saknar komplett metadata

## Uppdatering

GitHub Actions-workflowen kör:

- automatiskt på torsdagar runt kl. 12:00 Stockholmstid
- manuellt via `Actions`-fliken med `workflow_dispatch`

Om `docs/feed.xml` ändras committas och pushas den automatiskt tillbaka till `main`.
