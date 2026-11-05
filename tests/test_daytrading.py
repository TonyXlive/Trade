"""Tests du day trading, sans réseau."""
import gzip
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from bot import daytrading as dt  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    NY = timezone.utc

HEURES = [f"{9 + (30 + 5 * i) // 60:02d}:{(30 + 5 * i) % 60:02d}" for i in range(78)]  # 09:30 … 15:55
FIXTURE_TSLA = os.path.join(os.path.dirname(RACINE), "jakeschincariol", "day-trader-skill", "tests", "fixtures",
                            "trader-timemachine", "TSLA-60d5m.json.gz")


def journee(prix=100.0, changements=None):
    """Séance plate à `prix` (barres de 0,2 $ d'amplitude) ; changements = {heure: (o, h, l, c)}."""
    bs = []
    for h in HEURES:
        o, hi, lo, c = prix, prix + 0.1, prix - 0.1, prix
        if changements and h in changements:
            o, hi, lo, c = changements[h]
        bs.append({"heure": h, "open": o, "high": hi, "low": lo, "close": c})
    return bs


def range_ouverture(bs, haut=101.0, bas=99.0):
    """Range d'ouverture 99–101 (2 %) sur les 3 premières barres."""
    bs[0].update(open=100, high=haut, low=100, close=100.5)
    bs[1].update(open=100.5, high=100.8, low=bas, close=99.5)
    bs[2].update(open=99.5, high=100.2, low=99.6, close=100)
    return bs


def palier(bs, apres, prix):
    """Barres plates à `prix` à partir de l'heure donnée (exclue)."""
    for b in bs:
        if b["heure"] > apres:
            b.update(open=prix, high=prix + 0.1, low=prix - 0.1, close=prix)
    return bs


def barre(bs, heure, o, h, l, c):
    for b in bs:
        if b["heure"] == heure:
            b.update(open=o, high=h, low=l, close=c)
    return bs


class TestSeance(unittest.TestCase):
    def test_achat_sur_cassure_puis_objectif(self):
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)           # clôture au-dessus du haut (101)
        palier(bs, "09:45", 101.4)
        barre(bs, "09:50", 101.3, 101.5, 101.2, 101.4)         # entrée à l'ouverture : 101,3
        barre(bs, "10:30", 101.4, 104.0, 101.4, 103.5)         # objectif touché
        ops = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)
        self.assertEqual(len(ops), 1)
        o = ops[0]
        self.assertEqual((o["cote"], o["heure_entree"], o["motif"], o["heure_sortie"]), ("hausse", "09:50", "objectif", "10:30"))
        entree = 101.3 * 1.0002
        self.assertAlmostEqual(o["prix_entree"], round(entree, 4))
        self.assertEqual(o["stop"], 100.0)                         # milieu du range
        self.assertAlmostEqual(o["objectif"], round(entree + 2 * (entree - 100), 4))
        # taille : 0,5 % de risque (50 $) / 1,32 $ de risque par action = 37, plafond 25 % = 24 actions
        self.assertEqual(o["actions"], min(int(50 / (entree - 100)), int(2500 / entree)))
        self.assertGreater(o["pnl"], 0)
        self.assertEqual(o["frais"], 2.0)

    def test_vente_a_decouvert_puis_stop(self):
        bs = range_ouverture(journee())
        barre(bs, "10:00", 99.5, 99.6, 98.6, 98.7)              # clôture sous le bas (99)
        palier(bs, "10:00", 98.6)
        barre(bs, "10:05", 98.7, 98.8, 98.5, 98.6)              # entrée à découvert à 98,7
        barre(bs, "10:20", 98.6, 100.3, 98.6, 100.1)            # remonte au-dessus du stop (100)
        o = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)[0]
        self.assertEqual((o["cote"], o["motif"]), ("baisse", "stop"))
        self.assertAlmostEqual(o["prix_sortie"], round(100 * 1.0002, 4))
        self.assertLess(o["pnl"], 0)
        self.assertAlmostEqual(o["pnl"], round((o["prix_entree"] - o["prix_sortie"]) * o["actions"] - 2, 2), places=2)

    def test_stop_et_objectif_meme_barre_compte_le_stop(self):
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
        barre(bs, "09:55", 101.3, 110, 95, 101)
        o = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)[0]
        self.assertEqual(o["motif"], "stop")

    def test_ouverture_sous_le_stop(self):
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
        palier(bs, "09:45", 101.4)
        barre(bs, "09:50", 101.3, 101.5, 101.2, 101.4)
        barre(bs, "09:55", 98.0, 98.5, 97.5, 98.2)              # ouvre directement sous le stop
        o = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)[0]
        self.assertTrue(o["motif"].startswith("stop (ouverture"))
        self.assertAlmostEqual(o["prix_sortie"], round(98.0 * 0.9998, 4))

    def test_fermeture_en_fin_de_journee(self):
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
        for b in bs[4:]:
            b.update(open=101.5, high=101.6, low=101.4, close=101.5)
        o = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)[0]
        self.assertEqual((o["motif"], o["heure_sortie"]), ("fermeture de fin de journée", "15:55"))

    def test_pas_de_cassure_pas_d_operation(self):
        self.assertEqual(dt.jouer_seance("2026-11-05", {"AAA": range_ouverture(journee())}, 10000), [])

    def test_pas_d_entree_apres_11h30(self):
        bs = range_ouverture(journee())
        barre(bs, "11:30", 100, 101.4, 99.9, 101.3)
        self.assertEqual(dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000), [])

    def test_pas_de_regard_vers_le_futur(self):
        """La barre de cassure ne sert pas de prix d'entrée : on entre à la barre suivante."""
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
        barre(bs, "09:50", 102.0, 102.1, 101.9, 102.0)
        o = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)[0]
        self.assertAlmostEqual(o["prix_entree"], round(102.0 * 1.0002, 4))

    def test_range_trop_large_ignore(self):
        bs = range_ouverture(journee(), haut=104, bas=99)         # 5 %
        barre(bs, "09:45", 100, 104.5, 99.9, 104.4)
        self.assertEqual(dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000), [])

    def test_quatre_positions_maximum(self):
        barres = {}
        for i in range(6):
            bs = range_ouverture(journee())
            barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
            palier(bs, "09:45", 101.4)
            barres[f"S{i}"] = bs
        ops = dt.jouer_seance("2026-11-05", barres, 10000)
        self.assertEqual(len(ops), 4)
        self.assertLessEqual(sum(o["prix_entree"] * o["actions"] for o in ops), 10000)

    def test_arret_apres_2_pourcent_de_perte(self):
        barres = {}
        for i in range(6):
            bs = range_ouverture(journee())
            h_cass = HEURES[3 + 3 * i]
            barre(bs, h_cass, 100, 101.4, 99.9, 101.3)
            barre(bs, HEURES[4 + 3 * i], 101.3, 101.4, 90, 90.5)  # gros stop à chaque fois
            barres[f"S{i}"] = bs
        R = dict(dt.REGLES)
        try:
            dt.REGLES["risque_par_trade"] = 0.01               # 1 % par opération pour atteindre −2 % vite
            dt.REGLES["max_par_position"] = 1.0
            ops = dt.jouer_seance("2026-11-05", barres, 10000)
        finally:
            dt.REGLES.clear()
            dt.REGLES.update(R)
        # chaque perte ≈ 1 % : après 2 pertes (−2 %), plus aucune entrée
        ops.sort(key=lambda o: o["heure_entree"])
        cumul = 0.0
        for o in ops:
            self.assertGreater(cumul, -200, "entrée refusée une fois −2 % atteint")
            cumul += o["pnl"]
        self.assertEqual(len(ops), 2)

    def test_rien_ne_reste_ouvert(self):
        bs = range_ouverture(journee())
        barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
        palier(bs, "09:45", 101.4)
        bs = bs[:40]                                              # données coupées en cours de journée
        ops = dt.jouer_seance("2026-11-05", {"AAA": bs}, 10000)
        self.assertEqual(len(ops), 1)
        self.assertIn("dernière barre", ops[0]["motif"])


def en_yahoo_5min(jours):
    ts, q = [], {k: [] for k in ("open", "high", "low", "close", "volume")}
    for d, bs in jours.items():
        y, m, j = map(int, d.split("-"))
        for b in bs:
            hh, mm = map(int, b["heure"].split(":"))
            ts.append(int(datetime(y, m, j, hh, mm, tzinfo=NY).timestamp()))
            for k in ("open", "high", "low", "close"):
                q[k].append(b[k])
            q["volume"].append(100)
    return json.dumps({"chart": {"result": [{"meta": {}, "timestamp": ts, "indicators": {"quote": [q]}}],
                                 "error": None}}).encode()


def maintenant(d, h=18):
    y, m, j = map(int, d.split("-"))
    return datetime(y, m, j, h, 0, tzinfo=NY)


class TestSuivi(unittest.TestCase):
    def cours(self, dates):
        c = {}
        for s in ["SPY", "AAA"]:
            c[s] = {}
            for i, d in enumerate(dates):
                bs = range_ouverture(journee())
                if s == "AAA":
                    barre(bs, "09:45", 100, 101.4, 99.9, 101.3)
                    palier(bs, "09:45", 101.4)
                c[s][d] = bs
        return c

    def test_lecture_yahoo_heure_de_new_york(self):
        jours = {"2026-11-04": journee(), "2026-11-05": journee()[:20]}
        lu = dt.lire_yahoo_5min(en_yahoo_5min(jours))
        self.assertEqual(sorted(lu), ["2026-11-04", "2026-11-05"])
        self.assertEqual((lu["2026-11-04"][0]["heure"], lu["2026-11-04"][-1]["heure"], len(lu["2026-11-04"])),
                         ("09:30", "15:55", 78))

    def test_seance_en_cours_ignoree(self):
        c = self.cours(["2026-11-04", "2026-11-05"])
        c["SPY"]["2026-11-05"] = c["SPY"]["2026-11-05"][:20]
        self.assertEqual(dt.seances_terminees(c, maintenant("2026-11-05", 12)), ["2026-11-04"])

    def test_premier_lancement_puis_rattrapage_sans_doublon(self):
        dates = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
        c = self.cours(dates)
        e = dt.etat_vide()
        part = {s: {d: v for d, v in j.items() if d <= "2026-11-02"} for s, j in c.items()}
        self.assertEqual(dt.mettre_a_jour(e, part, maintenant("2026-11-02")), ["2026-11-02"])
        self.assertEqual(dt.mettre_a_jour(e, part, maintenant("2026-11-02")), [], "relancé : rien")
        self.assertEqual(dt.mettre_a_jour(e, c, maintenant("2026-11-05")), dates[1:], "rattrapage")
        self.assertEqual([h["date"] for h in e["historique"]], dates)
        self.assertAlmostEqual(e["capital"], 10000 + sum(o["pnl"] for o in e["operations"]), places=2)
        self.assertEqual(len(e["operations"]), 4)
        self.assertIsNotNone(e["historique"][-1]["indice"])

    def test_stop_aucune_operation(self):
        c = self.cours(["2026-11-05"])
        e = dt.etat_vide()
        dt.mettre_a_jour(e, c, maintenant("2026-11-05"), stop_actif=True)
        self.assertEqual(e["operations"], [])
        self.assertEqual(e["capital"], 10000)

    def test_bout_en_bout_avec_faux_reseau(self):
        d = tempfile.mkdtemp()
        try:
            c = self.cours(["2026-11-04", "2026-11-05"])

            def faux(url):
                for s in dt.SYMBOLES:
                    if f"/chart/{s}?" in url and s in c:
                        return en_yahoo_5min(c[s])
                    if f"/chart/{s}?" in url and s == "QQQ":
                        return en_yahoo_5min(c["AAA"])
                raise OSError("indisponible")
            for _ in range(2):
                e, joues, err = dt.executer_daytrading(os.path.join(d, "etat", "dt.json"), d, d, telecharger=faux,
                                                       maintenant=maintenant("2026-11-05"), bavard=False)
            self.assertEqual(len(e["historique"]), 1, "premier lancement : dernière séance seulement, sans doublon")
            self.assertTrue(err, "les actions indisponibles sont signalées")
            with open(os.path.join(d, "daytrading.html"), encoding="utf-8") as f:
                page = f.read()
            for texte in ["Day trading", "Verdict.", "Opérations de la dernière séance", "Nasdaq 100"]:
                self.assertIn(texte, page)
        finally:
            shutil.rmtree(d)

    def test_sans_reseau(self):
        d = tempfile.mkdtemp()
        try:
            def faux(url):
                raise OSError("pas de réseau")
            e, joues, err = dt.executer_daytrading(os.path.join(d, "etat", "dt.json"), d, d, telecharger=faux,
                                                   bavard=False)
            self.assertEqual(joues, [])
            with open(os.path.join(d, "daytrading.html"), encoding="utf-8") as f:
                self.assertIn("indisponibles", f.read())
        finally:
            shutil.rmtree(d)


@unittest.skipUnless(os.path.exists(FIXTURE_TSLA), "données réelles Tesla absentes")
class TestDonneesReelles(unittest.TestCase):
    def test_60_seances_tesla(self):
        with gzip.open(FIXTURE_TSLA) as f:
            jours = dt.lire_yahoo_5min(f.read())
        cap, ops = 10000.0, []
        for d, bs in sorted(jours.items()):
            if bs[-1]["heure"] != "15:55":
                continue
            o = dt.jouer_seance(d, {"TSLA": bs}, cap)
            self.assertLessEqual(len(o), 1, "une opération par action et par jour")
            for x in o:
                self.assertLessEqual(x["heure_entree"], "11:30")
                self.assertLessEqual(x["actions"] * x["prix_entree"], cap * 0.25 + 1)
                self.assertIn(x["heure_sortie"] >= x["heure_entree"], [True])
            cap += sum(x["pnl"] for x in o)
            ops += o
        self.assertGreater(len(ops), 20)
        self.assertAlmostEqual(cap, 10000 + sum(x["pnl"] for x in ops), places=2)


if __name__ == "__main__":
    unittest.main()
