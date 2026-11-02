"""Tests du portefeuille sur actions réelles, sans réseau (données fabriquées au format réel)."""
import json
import math
import os
import random
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from bot import actions_reelles as ar  # noqa: E402
from bot.actions_donnees import lire_yahoo, lire_stooq, cours_journaliers  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    NY = timezone.utc


def jours_bourse(fin: date, n: int):
    out, d = [], fin
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


def serie(n=260, depart=100.0, derive=0.002, vol=0.01, graine=1, fin=date(2026, 10, 30)):
    rng = random.Random(graine)
    p, barres = depart, []
    for d in jours_bourse(fin, n):
        o = p * (1 + rng.gauss(0, vol / 3))
        c = o * (1 + derive + rng.gauss(0, vol))
        h, l = max(o, c) * (1 + abs(rng.gauss(0, vol / 2))), min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        barres.append({"date": d.isoformat(), "open": round(o, 4), "high": round(h, 4), "low": round(l, 4),
                       "close": round(c, 4)})
        p = c
    return barres


def serie_cassure(n=260, fin=date(2026, 10, 30)):
    """Série haussière dont la dernière séance clôture au plus haut des 20 précédentes."""
    b = serie(n, derive=0.004, vol=0.003, fin=fin)
    haut = max(x["close"] for x in b[-21:-1])
    b[-1].update(close=round(haut * 1.01, 4), high=round(haut * 1.015, 4))
    return b


def en_yahoo(barres, nul_a=None):
    """Fabrique une réponse au format exact de l'API Yahoo « chart »."""
    ts, q = [], {"open": [], "high": [], "low": [], "close": [], "volume": []}
    for i, b in enumerate(barres):
        d = date.fromisoformat(b["date"])
        ts.append(int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp()))
        for k in ("open", "high", "low", "close"):
            q[k].append(None if i == nul_a else b[k])
        q["volume"].append(1000)
    return json.dumps({"chart": {"result": [{"meta": {"symbol": "X", "exchangeTimezoneName": "America/New_York"},
                                              "timestamp": ts, "indicators": {"quote": [q], "adjclose": [{}]}}],
                                 "error": None}}).encode()


class TestDonnees(unittest.TestCase):
    def test_lire_yahoo(self):
        b = serie(5)
        lu = lire_yahoo(en_yahoo(b))
        self.assertEqual([x["date"] for x in lu], [x["date"] for x in b])
        self.assertAlmostEqual(lu[-1]["close"], b[-1]["close"])

    def test_barre_incomplete_ignoree(self):
        self.assertEqual(len(lire_yahoo(en_yahoo(serie(5), nul_a=4))), 4)

    def test_erreur_yahoo(self):
        with self.assertRaises(ValueError):
            lire_yahoo(b'{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found"}}}')

    def test_lire_stooq(self):
        csv = b"Date,Open,High,Low,Close,Volume\n2026-10-29,1,2,0.5,1.5,10\n2026-10-30,1.5,2,1,1.8,10\n"
        lu = lire_stooq(csv)
        self.assertEqual(lu[-1], {"date": "2026-10-30", "open": 1.5, "high": 2.0, "low": 1.0, "close": 1.8})

    def test_secours_stooq(self):
        appels = []

        def faux(url):
            appels.append(url)
            if "yahoo" in url:
                raise OSError("bloqué")
            return b"Date,Open,High,Low,Close,Volume\n2026-10-30,1,2,0.5,1.5,10\n"
        bs, src = cours_journaliers("BRK.B", faux)
        self.assertEqual(src, "Stooq")
        self.assertEqual(len(appels), 3)
        self.assertIn("brk-b.us", appels[-1])

    def test_tout_echoue(self):
        def faux(url):
            raise OSError("pas de réseau")
        with self.assertRaises(RuntimeError):
            cours_journaliers("AAPL", faux)


def maintenant_apres(date_iso, heure=18):
    d = date.fromisoformat(date_iso)
    return datetime(d.year, d.month, d.day, heure, 0, tzinfo=NY)


class TestStrategie(unittest.TestCase):
    def test_signal_tendance(self):
        self.assertIsNotNone(ar.signal_entree(serie_cassure()))
        self.assertIsNone(ar.signal_entree(serie(260, derive=-0.003, vol=0.003)))
        self.assertIsNone(ar.signal_entree(serie(150, derive=0.004)), "pas assez d'historique")

    def test_taille_position(self):
        etat = ar.etat_vide()
        hist = serie_cassure()
        d = hist[-1]["date"]
        ar.jouer_jour(etat, d, {"SPY": serie(260), "AAA": hist})
        self.assertEqual(len(etat["positions"]), 1)
        p = etat["positions"][0]
        self.assertLessEqual(p["perte_max"], 10000 * 0.01 + 1e-6)
        self.assertLessEqual(p["cout"], 10000 * 0.20 + 1e-6)
        self.assertLess(p["stop"], p["prix_entree"])
        self.assertAlmostEqual(p["objectif"] - p["prix_entree"], 2 * (p["prix_entree"] - p["stop"]), places=3)

    def _position(self, **kw):
        etat = ar.etat_vide()
        p = {"symbole": "AAA", "date_entree": "2026-11-02", "prix_entree": 100.0, "actions": 10, "cout": 1000.0,
             "stop": 95.0, "objectif": 110.0, "jours": 0, "dernier_cours": 100.0, "perte_max": 50.0}
        p.update(kw)
        etat["cash"] -= p["cout"]
        etat["positions"].append(p)
        return etat

    def _jour(self, etat, o, h, l, c, d="2026-11-03", stop_actif=False):
        b = {"date": d, "open": o, "high": h, "low": l, "close": c}
        spy = [{"date": d, "open": 1, "high": 1, "low": 1, "close": 1}]
        return ar.jouer_jour(etat, d, {"AAA": [b], "SPY": spy}, stop_actif)

    def test_sortie_stop(self):
        e = self._position()
        self._jour(e, 99, 100, 94, 96)
        t = e["transactions"][0]
        self.assertEqual(t["motif"], "stop")
        self.assertAlmostEqual(t["prix_sortie"], 95 * (1 - 0.0005), places=3)
        self.assertAlmostEqual(t["r"], round((10 * 95 * 0.9995 - 1000) / 50, 2))

    def test_sortie_gap_sous_le_stop(self):
        e = self._position()
        self._jour(e, 90, 92, 89, 91)
        self.assertTrue(e["transactions"][0]["motif"].startswith("stop (ouverture"))
        self.assertAlmostEqual(e["transactions"][0]["prix_sortie"], 90 * 0.9995, places=3)

    def test_sortie_objectif(self):
        e = self._position()
        self._jour(e, 101, 111, 100, 109)
        self.assertEqual(e["transactions"][0]["motif"], "objectif")
        self.assertGreater(e["transactions"][0]["pnl"], 0)

    def test_stop_et_objectif_meme_jour_compte_le_stop(self):
        e = self._position()
        self._jour(e, 100, 112, 94, 105)
        self.assertEqual(e["transactions"][0]["motif"], "stop")

    def test_sortie_duree(self):
        e = self._position(jours=19)
        self._jour(e, 101, 102, 100, 101.5)
        self.assertEqual(e["transactions"][0]["motif"], "20 jours écoulés")

    def test_pas_de_sortie_le_jour_de_l_achat(self):
        e = self._position(date_entree="2026-11-03")
        self._jour(e, 90, 92, 89, 91)
        self.assertEqual(len(e["transactions"]), 0)

    def test_stop_bloque_les_entrees_pas_les_sorties(self):
        e = self._position()
        hist = serie(260, derive=0.004, vol=0.003, fin=date(2026, 11, 3))
        hist_spy = serie(260, fin=date(2026, 11, 3))
        b = hist[-1]
        b.update(open=90, high=92, low=89, close=91)  # le jour fait sortir AAA
        ar.jouer_jour(e, "2026-11-03", {"AAA": hist, "BBB": serie_cassure(fin=date(2026, 11, 3)),
                                        "SPY": hist_spy}, stop_actif=True)
        self.assertEqual(len(e["transactions"]), 1)
        self.assertEqual(len(e["positions"]), 0)

    def test_drawdown_bloque_les_entrees(self):
        e = ar.etat_vide()
        e["pic"] = 12000  # valeur 10 000 : −16,7 %
        hist = serie_cassure()
        ar.jouer_jour(e, hist[-1]["date"], {"SPY": serie(260), "AAA": hist})
        self.assertEqual(len(e["positions"]), 0)
        self.assertTrue(e["historique"][-1]["bloque"])


class TestMiseAJour(unittest.TestCase):
    def setUp(self):
        self.cours = {"SPY": serie(300, graine=0, derive=0.0005)}
        for i, s in enumerate(ar.LISTE[:8]):
            self.cours[s] = serie(300, graine=i + 10, derive=0.003, vol=0.012)

    def tranche(self, jusqu_a):
        return {s: [b for b in bs if b["date"] <= jusqu_a] for s, bs in self.cours.items()}

    def test_premier_lancement_puis_quotidien(self):
        dates = [b["date"] for b in self.cours["SPY"]]
        e = ar.etat_vide()
        self.assertEqual(ar.mettre_a_jour(e, self.tranche(dates[250]), maintenant_apres(dates[250])), 1)
        self.assertEqual(e["date_debut"], dates[250])
        self.assertEqual(ar.mettre_a_jour(e, self.tranche(dates[250]), maintenant_apres(dates[250])), 0,
                         "relancé le même jour : rien")
        self.assertEqual(ar.mettre_a_jour(e, self.tranche(dates[251]), maintenant_apres(dates[251])), 1)
        self.assertEqual(ar.mettre_a_jour(e, self.tranche(dates[256]), maintenant_apres(dates[256])), 5, "rattrapage")
        self.assertEqual([h["date"] for h in e["historique"]], dates[250:257])

    def test_seance_en_cours_ignoree(self):
        dates = [b["date"] for b in self.cours["SPY"]]
        e = ar.etat_vide()
        ar.mettre_a_jour(e, self.tranche(dates[250]), maintenant_apres(dates[250]))
        n = ar.mettre_a_jour(e, self.tranche(dates[251]), maintenant_apres(dates[251], heure=11))
        self.assertEqual(n, 0, "séance pas terminée à 11 h à New York")

    def test_comptabilite_et_regles_sur_toute_la_periode(self):
        dates = [b["date"] for b in self.cours["SPY"]]
        e = ar.etat_vide()
        for i in range(210, 300):
            ar.mettre_a_jour(e, self.tranche(dates[i]), maintenant_apres(dates[i]))
            self.assertGreaterEqual(e["cash"], -1e-6)
            self.assertLessEqual(len(e["positions"]), ar.REGLES["max_positions"])
        self.assertGreater(len(e["transactions"]), 0, "la stratégie doit trader sur une série haussière")
        latent = sum(p["actions"] * p["dernier_cours"] - p["cout"] for p in e["positions"])
        realise = sum(t["pnl"] for t in e["transactions"])
        self.assertAlmostEqual(e["historique"][-1]["valeur"], 10000 + realise + latent, delta=0.05)
        for h in e["historique"]:
            self.assertLessEqual(len(h["entrees"]), ar.REGLES["max_entrees_jour"])
        r = ar.resume(e)
        self.assertIn("indice S&P 500", r["verdict"])

    def test_indice_manquant(self):
        e = ar.etat_vide()
        with self.assertRaises(RuntimeError):
            ar.mettre_a_jour(e, {"AAPL": serie(260)})


class TestExecution(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d)

    def test_bout_en_bout_avec_faux_reseau(self):
        series = {s: serie(260, graine=i, derive=0.003, vol=0.01) for i, s in enumerate(["SPY"] + ar.LISTE)}

        def faux(url):
            for s, b in series.items():
                if f"/chart/{s}?" in url:
                    return en_yahoo(b)
            raise OSError("inconnu")
        fin = series["SPY"][-1]["date"]
        etat, joues, err = ar.executer_actions(os.path.join(self.d, "etat", "actions.json"), self.d, self.d,
                                               telecharger=faux, maintenant=maintenant_apres(fin), bavard=False)
        self.assertEqual((joues, err), (1, []))
        with open(os.path.join(self.d, "actions.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Actions réelles", page)
        self.assertIn("Verdict.", page)
        # deuxième lancement : reprend l'état sauvegardé, ne rejoue rien
        etat2, joues2, _ = ar.executer_actions(os.path.join(self.d, "etat", "actions.json"), self.d, self.d,
                                               telecharger=faux, maintenant=maintenant_apres(fin), bavard=False)
        self.assertEqual(joues2, 0)
        self.assertEqual(etat2["historique"], etat["historique"])

    def test_sans_reseau_la_page_existe_quand_meme(self):
        def faux(url):
            raise OSError("pas de réseau")
        etat, joues, err = ar.executer_actions(os.path.join(self.d, "etat", "actions.json"), self.d, self.d,
                                               telecharger=faux, bavard=False)
        self.assertEqual(joues, 0)
        self.assertTrue(err)
        with open(os.path.join(self.d, "actions.html"), encoding="utf-8") as f:
            self.assertIn("Données incomplètes", f.read())


if __name__ == "__main__":
    unittest.main()


class TestJournal(unittest.TestCase):
    def test_journal_liste_chaque_achat_et_vente(self):
        d = tempfile.mkdtemp()
        try:
            e = ar.etat_vide()
            e["date_debut"] = e["derniere_date"] = "2026-11-03"
            e["positions"].append({"symbole": "LLY", "date_entree": "2026-11-03", "prix_entree": 1418.25, "actions": 1,
                                   "cout": 1418.25, "stop": 1321.06, "objectif": 1612.63, "jours": 0,
                                   "dernier_cours": 1418.0, "perte_max": 97.19})
            e["transactions"].append({"symbole": "XOM", "date_entree": "2026-10-20", "prix_entree": 180.0, "actions": 10,
                                      "cout": 1800.0, "stop": 172.0, "objectif": 196.0, "jours": 5,
                                      "dernier_cours": 196.0, "perte_max": 80.0, "date_sortie": "2026-10-27",
                                      "prix_sortie": 195.9, "motif": "objectif", "pnl": 159.0, "r": 1.99})
            e["historique"].append({"date": "2026-11-03", "valeur": 10100, "indice": 10050, "entrees": ["LLY"],
                                    "sorties": [], "bloque": False})
            from bot.suivi_actions import generer_page_actions
            generer_page_actions(e, ar.resume(e), d, [])
            with open(os.path.join(d, "actions.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn("Tous les achats et ventes", page)
            self.assertIn("Eli Lilly (LLY)", page)
            self.assertIn("ExxonMobil (XOM)", page)
            self.assertIn("vendu le 27 oct.", page)
            self.assertIn("en cours", page)
            self.assertLess(page.index("Eli Lilly (LLY) <span"), page.index("ExxonMobil (XOM)</div>") if "ExxonMobil (XOM)</div>" in page else len(page))
        finally:
            shutil.rmtree(d)

    def test_tous_les_symboles_ont_un_nom(self):
        for s in [ar.INDICE] + ar.LISTE:
            self.assertIn(s, ar.NOMS)


class TestApprentissage(unittest.TestCase):
    def _cours(self, n=420):
        c = {"SPY": serie(n, graine=0, derive=0.0005)}
        for i, s in enumerate(ar.LISTE[:12]):
            c[s] = serie(n, graine=i + 30, derive=0.002, vol=0.015)
        return c

    def test_variantes_creees_et_distinctes(self):
        e = ar.etat_vide()
        v = ar.assurer_variantes(e)
        self.assertEqual(set(v), set(ar.CANDIDATS) - {"Règle de départ"})
        for n, x in v.items():
            self.assertEqual(x["reglages"], ar.CANDIDATS[n])

    def test_regles_variante_appliquees(self):
        e = ar.etat_vide()
        e["reglages"] = {"atr_stop": 1.5}
        self.assertEqual(ar.regles_de(e)["atr_stop"], 1.5)
        self.assertEqual(ar.regles_de(ar.etat_vide())["atr_stop"], 2.0)

    def test_pas_d_adoption_trop_tot(self):
        cours = self._cours(280)
        dates = [b["date"] for b in cours["SPY"]]
        e = ar.etat_vide()
        for i in range(250, 280):
            t = {s: [b for b in bs if b["date"] <= dates[i]] for s, bs in cours.items()}
            ar.mettre_a_jour(e, t, maintenant_apres(dates[i]))
            for v in ar.assurer_variantes(e).values():
                ar.mettre_a_jour(v, t, maintenant_apres(dates[i]))
            self.assertIsNone(ar.evaluer_adoption(e))
        self.assertEqual(ar.nom_regle(e), "Règle de départ")

    def test_adoption_quand_nettement_meilleure(self):
        e = ar.etat_vide()
        ar.assurer_variantes(e)
        # Faux historiques : la variante « Stop plus large » fait +10 points sur 130 séances
        jours = [d.isoformat() for d in jours_bourse(date(2026, 10, 30), 130)]
        e["historique"] = [{"date": d, "valeur": 10000 + i, "indice": 10000, "entrees": [], "sorties": [], "bloque": False}
                           for i, d in enumerate(jours)]
        e["derniere_date"] = jours[-1]
        tx = {"date_entree": jours[5], "pnl": 1, "r": 0.1}
        e["transactions"] = [dict(tx) for _ in range(70)]
        v = e["variantes"]["Stop plus large"]
        v["historique"] = [{"date": d, "valeur": 10000 + i * 9, "indice": 10000, "entrees": [], "sorties": [],
                            "bloque": False} for i, d in enumerate(jours)]
        v["transactions"] = [dict(tx) for _ in range(70)]
        chg = ar.evaluer_adoption(e)
        self.assertIsNotNone(chg)
        self.assertEqual(chg["nouvelle"], "Stop plus large")
        self.assertEqual(ar.regles_de(e)["atr_stop"], 3.0)
        self.assertIn("Règle de départ", e["variantes"], "l'ancienne règle redevient une variante")
        self.assertNotIn("Stop plus large", e["variantes"])
        self.assertTrue(all(not x["historique"] for x in e["variantes"].values()), "comparaison repart de zéro")

    def test_pas_d_adoption_si_baisse_plus_forte(self):
        e = ar.etat_vide()
        ar.assurer_variantes(e)
        jours = [d.isoformat() for d in jours_bourse(date(2026, 10, 30), 130)]
        e["historique"] = [{"date": d, "valeur": 10000 + i, "indice": 10000, "entrees": [], "sorties": [], "bloque": False}
                           for i, d in enumerate(jours)]
        e["derniere_date"] = jours[-1]
        tx = {"date_entree": jours[5], "pnl": 1, "r": 0.1}
        e["transactions"] = [dict(tx) for _ in range(70)]
        v = e["variantes"]["Stop plus large"]
        vals = [10000 + i * 9 for i in range(130)]
        vals[60] = 7000  # chute de 30 % en cours de route
        v["historique"] = [{"date": d, "valeur": x, "indice": 10000, "entrees": [], "sorties": [], "bloque": False}
                           for d, x in zip(jours, vals)]
        v["transactions"] = [dict(tx) for _ in range(70)]
        self.assertIsNone(ar.evaluer_adoption(e))

    def test_criteres_prod(self):
        e = ar.etat_vide()
        crit = ar.criteres_prod(e, ar.resume(e))
        self.assertEqual(len(crit), 5)
        self.assertFalse(any(ok for _, ok, _ in crit))

    def test_bout_en_bout_avec_variantes(self):
        d = tempfile.mkdtemp()
        try:
            series = {s: serie(260, graine=i, derive=0.003, vol=0.01) for i, s in enumerate(["SPY"] + ar.LISTE)}

            def faux(url):
                for s, b in series.items():
                    if f"/chart/{s}?" in url:
                        return en_yahoo(b)
                raise OSError("inconnu")
            etat, _, _ = ar.executer_actions(os.path.join(d, "etat", "actions.json"), d, d, telecharger=faux,
                                             maintenant=maintenant_apres(series["SPY"][-1]["date"]), bavard=False)
            self.assertEqual(len(etat["variantes"]), 4)
            for v in etat["variantes"].values():
                self.assertEqual(len(v["historique"]), 1)
            with open(os.path.join(d, "actions.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn("Ce que le bot apprend", page)
            self.assertIn("Prêt pour de l'argent réel ?", page)
        finally:
            shutil.rmtree(d)
