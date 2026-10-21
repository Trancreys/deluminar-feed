# deluminar-feed

Verbesserter Pinterest-Produktfeed für deluminar.com.

Jede Nacht holt GitHub den Produktfeed von Wix, setzt längere Titel ein und ergänzt die
Google-Produktkategorie (`google_product_category`). Die verbesserte Kopie wird hier veröffentlicht:

**https://trancreys.github.io/deluminar-feed/pinterest.xml**

Alles andere (Preise, Lagerstand, Bilder, Links, Varianten, IDs) wird unverändert aus Wix übernommen.
Änderungen in Wix kommen also weiter automatisch bei Pinterest an.

## Titel und Kategorien ändern

1. Datei [`einstellungen.ini`](einstellungen.ini) öffnen.
2. Oben rechts auf den Stift klicken.
3. Den Text hinter `titel =` oder `kategorie =` ändern. Die Hinweise oben in der Datei erklären alles.
4. **Commit changes** klicken. Der Feed wird danach automatisch neu gebaut.

## Lauf von Hand starten

1. Oben auf **Actions** klicken.
2. Links **Pinterest-Feed bauen** wählen.
3. Rechts **Run workflow**, dann noch einmal das grüne **Run workflow** klicken.

Optionen dabei:
- **erzwingen**: auch veröffentlichen, wenn deutlich weniger Produkte im Feed sind als beim letzten Mal
  (z. B. wenn du absichtlich viele Produkte entfernt hast).
- **test_fehler**: nur zum Testen der Fehler-Benachrichtigung.

## Zeitplan

Täglich um 23:07 UTC, das ist 00:07 Uhr im Winter und 01:07 Uhr im Sommer.
Pinterest holt um 03:00 Uhr ab.

GitHub schaltet Zeitpläne in öffentlichen Repos nach 60 Tagen ohne Aktivität ab. Dagegen aktiviert
jeder Lauf den Zeitplan am Ende selbst neu, dadurch beginnt die Frist jede Nacht von vorn.

## Wenn etwas schiefgeht

- **Wix nicht erreichbar, Feed kaputt, deutlich weniger Produkte als beim letzten Lauf (weniger als die
  Hälfte), oder Daten würden verändert:** Dann wird nichts veröffentlicht. Pinterest bekommt weiter den
  zuletzt funktionierenden Feed. Der Lauf schlägt fehl, und du bekommst eine Mail von GitHub sowie ein
  Issue „Feed-Lauf fehlgeschlagen“. Beim nächsten erfolgreichen Lauf wird das Issue automatisch geschlossen.
- **Neues Produkt in Wix, das noch nicht in den Einstellungen steht:** Es wird mit dem Wix-Titel
  veröffentlicht. Du bekommst ein Issue „Neues Produkt: bitte Titel und Kategorie eintragen“ mit einem
  fertigen Block zum Hineinkopieren.

## Technik

- `veredler.py`: das Programm (Python, nur Standardbibliothek)
- `einstellungen.ini`: Titel und Kategorien pro Produkt
- `.github/workflows/feed.yml`: Zeitplan und Veröffentlichung über GitHub Pages
- Geheimer Wert `WIX_FEED_URL` (Settings → Secrets and variables → Actions): die Wix-Feed-Adresse

Lokal testen: `python3 veredler.py --quelle wix-feed.xml --ausgabe test.xml`
