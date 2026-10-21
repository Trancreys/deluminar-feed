#!/usr/bin/env python3
"""Feed-Veredler für deluminar.com

Holt den Pinterest-Feed von Wix, ersetzt die Titel, ergänzt
google_product_category und schreibt eine verbesserte Kopie.
Alles andere bleibt Zeichen für Zeichen so, wie Wix es liefert.
Nur Python-Standardbibliothek.
"""
import argparse
import configparser
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

G = "{http://base.google.com/ns/1.0}"
GEAENDERT = {G + "title", G + "google_product_category"}  # nur diese Felder fassen wir an
VARIANTEN_FELDER = ("color", "size", "material", "pattern")
MAX_TITEL = 120
MIN_ANTEIL = 0.5  # weniger als die Hälfte der Einträge vom letzten Lauf -> nicht veröffentlichen


class FeedFehler(Exception):
    pass


def laden(quelle, fehlt_ok=False):
    """Liest eine Datei oder lädt eine URL. None, wenn fehlt_ok und HTTP 404."""
    if not re.match(r"https?://", quelle):
        with open(quelle, "rb") as f:
            return f.read()
    req = urllib.request.Request(quelle, headers={"User-Agent": "deluminar-feed-veredler"})
    for versuch in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and fehlt_ok:
                return None
            grund = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            grund = str(getattr(e, "reason", e))
        print(f"Versuch {versuch}: Download fehlgeschlagen ({grund})")
        if versuch < 3:
            time.sleep(15 * versuch)
    raise FeedFehler(f"Download fehlgeschlagen ({grund})")


def eintraege(daten, name):
    try:
        root = ET.fromstring(daten)
    except ET.ParseError as e:
        raise FeedFehler(f"{name} ist kein gültiges XML ({e})")
    kanal = root.find("channel")
    if root.tag != "rss" or kanal is None:
        raise FeedFehler(f"{name} ist kein RSS-Feed")
    return kanal, kanal.findall("item")


def varianten(item):
    """Variantenmerkmale wie Farbe, Größe oder color."""
    werte = {}
    for feld in VARIANTEN_FELDER:
        wert = (item.findtext(G + feld) or "").strip()
        if wert:
            werte[feld] = wert
    for d in item.findall(G + "product_detail"):
        name = (d.findtext(G + "attribute_name") or "").strip()
        wert = (d.findtext(G + "attribute_value") or "").strip()
        if name and wert:
            werte[name] = wert
    return werte


def einstellungen_lesen(pfad):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # Groß-/Kleinschreibung erhalten
    try:
        with open(pfad, encoding="utf-8") as f:
            cp.read_file(f)
    except (configparser.Error, UnicodeDecodeError) as e:
        raise FeedFehler(f"Die Einstellungsdatei ist fehlerhaft: {e}")
    schreibweisen = dict(cp["Schreibweisen"]) if cp.has_section("Schreibweisen") else {}
    produkte = {}
    for abschnitt in cp.sections():
        if abschnitt != "Schreibweisen":
            produkte[abschnitt.strip().lower()] = {k.lower(): v.strip() for k, v in cp[abschnitt].items()}
    return produkte, schreibweisen


def titel_bauen(vorlage, werte, schreibweisen):
    fehlend = []

    def ersetzen(m):
        name = m.group(1).strip()
        if name not in werte:
            fehlend.append(name)
            return m.group(0)
        return schreibweisen.get(werte[name], werte[name])

    titel = re.sub(r"\{([^{}]+)\}", ersetzen, vorlage)
    return " ".join(titel.split()), fehlend


def titel_setzen(block, titel):
    neu, n = re.subn(r"(<g:title>).*?(</g:title>)",
                     lambda m: m.group(1) + escape(titel) + m.group(2), block, count=1, flags=re.S)
    if n != 1:
        raise FeedFehler("Ein Eintrag im Wix-Feed hat kein <g:title>")
    return neu


def kategorie_setzen(block, kategorie):
    tag = f"<g:google_product_category>{kategorie}</g:google_product_category>"
    alt = r"<g:google_product_category\s*/>|<g:google_product_category>.*?</g:google_product_category>"
    if re.search(alt, block, re.S):
        return re.sub(alt, lambda m: tag, block, count=1, flags=re.S)
    einzug = re.search(r"\n([ \t]*)<g:title>", block)
    ende = re.search(r"\n[ \t]*</item>$", block)
    if einzug and ende:
        return block[:ende.start()] + "\n" + einzug.group(1) + tag + block[ende.start():]
    return block[:-len("</item>")] + tag + "</item>"


def veredeln(quelle, produkte, schreibweisen):
    """Gibt (neuer Feed als Text, Zeilen für Bericht, neue Produkte, Hinweise) zurück."""
    try:
        text = quelle.decode("utf-8")
    except UnicodeDecodeError:
        raise FeedFehler("Der Wix-Feed ist nicht UTF-8-kodiert")
    _, items = eintraege(quelle, "Der Wix-Feed")
    if not items:
        raise FeedFehler("Der Wix-Feed enthält 0 Einträge")
    bloecke = list(re.finditer(r"<item\b[^>]*>.*?</item>", text, re.S))
    if len(bloecke) != len(items):
        raise FeedFehler("Der Aufbau des Wix-Feeds ist unerwartet (Einträge nicht eindeutig erkennbar)")

    teile, pos, zeilen, neue, hinweise = [], 0, [], {}, []
    for item, treffer in zip(items, bloecke):
        iid = (item.findtext(G + "id") or "").strip()
        gid = (item.findtext(G + "item_group_id") or "").strip()
        wix_titel = (item.findtext(G + "title") or "").strip()
        werte = varianten(item)
        titel, kategorie = wix_titel, ""
        produkt = produkte.get(iid.lower()) or produkte.get(gid.lower())
        if produkt is None:
            neue.setdefault(gid or iid, (wix_titel, []))[1].append(werte)
        else:
            name = produkt.get("name") or wix_titel
            if produkt.get("titel"):
                neu, fehlend = titel_bauen(produkt["titel"], werte, schreibweisen)
                if fehlend:
                    hinweise.append(f"**{name}** (ID `{iid}`): Platzhalter {', '.join('{' + f + '}' for f in fehlend)} "
                                    "gibt es bei dieser Variante nicht. Dafür wird der Wix-Titel verwendet.")
                else:
                    titel = neu
            kategorie = produkt.get("kategorie", "")
            if kategorie and not kategorie.isdigit():
                hinweise.append(f"**{name}**: Kategorie „{kategorie}“ ist keine Zahl und wird weggelassen.")
                kategorie = ""
            if len(titel) > MAX_TITEL:
                hinweise.append(f"**{name}**: Titel hat {len(titel)} Zeichen (empfohlen höchstens {MAX_TITEL}): {titel}")
        block = titel_setzen(treffer.group(0), titel)
        if kategorie:
            block = kategorie_setzen(block, kategorie)
        teile += [text[pos:treffer.start()], block]
        pos = treffer.end()
        zeilen.append((iid, wix_titel, werte, titel, kategorie))
    teile.append(text[pos:])
    return "".join(teile), zeilen, neue, hinweise


def inhalt(el):
    """Vergleichbare Form eines Elements, ohne Leerraum dahinter."""
    return el.tag, sorted(el.attrib.items()), el.text, [inhalt(k) for k in el]


def pruefen(quelle, ergebnis, zeilen):
    """Prüft vor dem Veröffentlichen, dass nur Titel und Kategorie anders sind."""
    q_kanal, q_items = eintraege(quelle, "Der Wix-Feed")
    a_kanal, a_items = eintraege(ergebnis.encode("utf-8"), "Der neue Feed")
    if len(a_items) != len(q_items):
        raise FeedFehler(f"Anzahl der Einträge stimmt nicht ({len(a_items)} statt {len(q_items)})")
    if [inhalt(k) for k in q_kanal if k.tag != "item"] != [inhalt(k) for k in a_kanal if k.tag != "item"]:
        raise FeedFehler("Die Kopfdaten des Feeds wurden verändert")
    for q, a, (iid, _, _, titel, kategorie) in zip(q_items, a_items, zeilen):
        if not iid or (a.findtext(G + "id") or "").strip() != iid:
            raise FeedFehler(f"ID fehlt oder stimmt nicht: „{iid}“")
        if [inhalt(k) for k in q if k.tag not in GEAENDERT] != [inhalt(k) for k in a if k.tag not in GEAENDERT]:
            raise FeedFehler(f"Eintrag {iid}: Preise, Links oder andere Daten wurden verändert")
        if (a.findtext(G + "title") or "").strip() != titel:
            raise FeedFehler(f"Eintrag {iid}: Titel wurde nicht richtig gesetzt")
        if kategorie and a.findtext(G + "google_product_category") != kategorie:
            raise FeedFehler(f"Eintrag {iid}: Kategorie wurde nicht richtig gesetzt")


def neue_produkte_text(neue):
    text = ["Diese Produkte sind im Wix-Feed, aber nicht in `einstellungen.ini`. "
            "Sie werden mit dem Wix-Titel und ohne Kategorie veröffentlicht.", "",
            "So trägst du sie ein: `einstellungen.ini` öffnen, auf den Stift klicken, "
            "den Block unten ans Ende kopieren, Titel und Kategorie ausfüllen und auf **Commit changes** klicken.", "",
            "```ini"]
    for gid, (wix_titel, alle) in neue.items():
        merkmale = {}
        for werte in alle:
            for k, v in werte.items():
                merkmale.setdefault(k, [])
                if v not in merkmale[k]:
                    merkmale[k].append(v)
        text += [f"[{gid}]", f"name = {wix_titel}"]
        if merkmale:
            text.append("# Varianten im Feed: " + "; ".join("{" + k + "} = " + " | ".join(v) for k, v in merkmale.items()))
        text += [f"titel = {wix_titel}", "kategorie = ", ""]
    return "\n".join(text).rstrip() + "\n```\n"


def bericht(zeilen):
    text = ["| ID | Wix-Titel | Variante | Neuer Titel | Kategorie |", "|---|---|---|---|---|"]
    for iid, wix_titel, werte, titel, kategorie in zeilen:
        variante = ", ".join(werte.values()) or "–"
        text.append(f"| `{iid[:8]}` | {wix_titel} | {variante} | {titel} | {kategorie or '–'} |")
    return "\n".join(text) + "\n"


def schreiben(pfad, text):
    os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
    with open(pfad, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quelle", default=os.environ.get("WIX_FEED_URL"), help="Wix-Feed (URL oder Datei)")
    p.add_argument("--einstellungen", default="einstellungen.ini")
    p.add_argument("--ausgabe", default="public/pinterest.xml")
    p.add_argument("--vorher", help="Bisher veröffentlichter Feed (URL oder Datei) für den Mengenvergleich")
    p.add_argument("--meldungen", default="meldungen", help="Ordner für Hinweise an Dean")
    p.add_argument("--erzwingen", action="store_true", help="Mengenvergleich mit dem letzten Lauf überspringen")
    args = p.parse_args()
    zusammenfassung = os.environ.get("GITHUB_STEP_SUMMARY")
    os.makedirs(args.meldungen, exist_ok=True)

    try:
        if not args.quelle:
            raise FeedFehler("Keine Wix-Feed-URL angegeben (Secret WIX_FEED_URL fehlt?)")
        produkte, schreibweisen = einstellungen_lesen(args.einstellungen)
        quelle = laden(args.quelle)
        ergebnis, zeilen, neue, hinweise = veredeln(quelle, produkte, schreibweisen)

        if args.vorher and not args.erzwingen:
            vorher = laden(args.vorher, fehlt_ok=True)
            if vorher is None:
                print("Noch kein veröffentlichter Feed vorhanden (erster Lauf).")
            else:
                anzahl_vorher = len(eintraege(vorher, "Der bisherige Feed")[1])
                if len(zeilen) < anzahl_vorher * MIN_ANTEIL:
                    raise FeedFehler(f"Der Wix-Feed hat nur {len(zeilen)} Einträge, beim letzten Lauf waren es "
                                     f"{anzahl_vorher}. Zur Sicherheit wird nichts veröffentlicht. Falls das so "
                                     "gewollt ist: Lauf von Hand mit „erzwingen“ starten.")

        pruefen(quelle, ergebnis, zeilen)
    except FeedFehler as e:
        print(f"::error::{e}")
        schreiben(os.path.join(args.meldungen, "fehler.md"), f"{e}\n")
        if zusammenfassung:
            schreiben(zusammenfassung, f"## Fehler\n\n{e}\n\nDer bisher veröffentlichte Feed bleibt unverändert.\n")
        return 1

    schreiben(args.ausgabe, ergebnis)
    if neue:
        schreiben(os.path.join(args.meldungen, "neues-produkt.md"), neue_produkte_text(neue))
    if hinweise:
        schreiben(os.path.join(args.meldungen, "hinweise.md"), "\n".join(f"- {h}" for h in hinweise) + "\n")
    for h in hinweise:
        print(f"::warning::{re.sub(r'[*`]', '', h)}")

    mit_kategorie = sum(1 for z in zeilen if z[4])
    kopf = (f"{len(zeilen)} Einträge geprüft, {mit_kategorie} mit Kategorie, "
            f"{len(neue)} neue Produkte ohne Einstellungen.\n")
    print(kopf + bericht(zeilen))
    if zusammenfassung:
        schreiben(zusammenfassung, "## Feed gebaut\n\n" + kopf + "\n" + bericht(zeilen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
