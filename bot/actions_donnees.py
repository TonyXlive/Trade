"""Récupération des cours journaliers de vraies actions américaines (données publiques).

Source principale : Yahoo Finance (point d'accès « chart », gratuit, non officiel).
Secours : Stooq (CSV gratuit). Aucune clé, aucun compte, aucun ordre.
"""
import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
    NEW_YORK = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    NEW_YORK = None

AGENT = "Mozilla/5.0 (compatible; bot-portefeuille-fictif/1.0)"


def _telecharger(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def date_new_york(ts: int) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    if NEW_YORK:
        dt = dt.astimezone(NEW_YORK)
    return dt.date().isoformat()


def lire_yahoo(contenu) -> list:
    """Transforme une réponse Yahoo « chart » en liste de barres journalières."""
    d = json.loads(contenu) if isinstance(contenu, (bytes, str)) else contenu
    res = (d.get("chart") or {}).get("result")
    if not res:
        err = (d.get("chart") or {}).get("error") or {}
        raise ValueError(err.get("description") or "réponse Yahoo vide")
    r = res[0]
    q = r["indicators"]["quote"][0]
    barres = []
    for i, ts in enumerate(r.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or c <= 0:
            continue  # barre incomplète
        barres.append({"date": date_new_york(ts), "open": round(o, 4), "high": round(h, 4),
                       "low": round(l, 4), "close": round(c, 4)})
    # une seule barre par date (la dernière l'emporte)
    uniques = {b["date"]: b for b in barres}
    return [uniques[k] for k in sorted(uniques)]


def lire_stooq(contenu) -> list:
    texte = contenu.decode("utf-8") if isinstance(contenu, bytes) else contenu
    lignes = list(csv.DictReader(io.StringIO(texte)))
    barres = []
    for ln in lignes:
        try:
            barres.append({"date": ln["Date"], "open": float(ln["Open"]), "high": float(ln["High"]),
                           "low": float(ln["Low"]), "close": float(ln["Close"])})
        except (KeyError, ValueError):
            continue
    if not barres:
        raise ValueError("réponse Stooq vide")
    return sorted(barres, key=lambda b: b["date"])


def cours_journaliers(symbole: str, telecharger=_telecharger) -> tuple:
    """Retourne (barres, source). Essaie Yahoo (2 serveurs) puis Stooq."""
    erreurs = []
    for hote in ("query2", "query1"):
        try:
            url = f"https://{hote}.finance.yahoo.com/v8/finance/chart/{symbole}?range=1y&interval=1d"
            return lire_yahoo(telecharger(url)), "Yahoo"
        except Exception as e:  # noqa: BLE001
            erreurs.append(f"Yahoo {hote} : {e}")
            time.sleep(0.5) if telecharger is _telecharger else None
    try:
        url = f"https://stooq.com/q/d/l/?s={symbole.lower().replace('.', '-')}.us&i=d"
        return lire_stooq(telecharger(url)), "Stooq"
    except Exception as e:  # noqa: BLE001
        erreurs.append(f"Stooq : {e}")
    raise RuntimeError(" ; ".join(erreurs))
