"""Tests de l'onglet « Mes 50 €/mois », sans réseau."""
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "tests"))

from bot import mensuel as m  # noqa: E402
from bot import actions_reelles as ar  # noqa: E402
from test_actions import serie, serie_cassure, en_yahoo, maintenant_apres, jours_bourse  # noqa: E402


def devise(n=300, taux=1.10, fin=date(2026, 12, 31)):
    return [{"date": d.isoformat(), "open": taux, "high": taux, "low": taux, "close": taux}
            for d in jours_bourse(fin, n)]


def cours_test(fin=date(2026, 12, 31), n=300):
    c = {"SPY": serie(n, graine=0, derive=0.0005, fin=fin), m.DEVISE: devise(n, fin=fin)}
    for i, s in enumerate(ar.LISTE[:8]):
        c[s] = serie(n, graine=i + 50, derive=0.003, vol=0.012, fin=fin)
    return c


def tranche(cours, d):
    return {s: [b for b in bs if b["date"] <= d] for s, bs in cours.items()}


class TestVersements(unittest.TestCase):
    def test_un_versement_par_mois(self):
        cours = cours_test()
        dates = [b["date"] for b in cours["SPY"] if b["date"] >= "2026-10-01"]
        e = m.etat_vide()
        for d in dates:
            m.mettre_a_jour(e, tranche(cours, d), maintenant_apres(d))
        mois = [v["mois"] for v in e["versements"]]
        self.assertEqual(mois, ["2026-10", "2026-11", "2026-12"])
        self.assertEqual(e["verse_eur"], 150)
        # chaque versement tombe sur la première séance du mois
        for v in e["versements"]:
            self.assertEqual(v["date"], min(d for d in dates if d.startswith(v["mois"])))
            self.assertAlmostEqual(v["usd"], 55.0)

    def test_indice_achete_a_chaque_versement(self):
        cours = cours_test()
        dates = [b["date"] for b in cours["SPY"] if b["date"] >= "2026-11-01"]
        e = m.etat_vide()
        for d in dates:
            m.mettre_a_jour(e, tranche(cours, d), maintenant_apres(d))
        ind = e["indice"]
        self.assertEqual(ind["ordres"], 2)
        self.assertAlmostEqual(ind["frais"], 2.0)
        self.assertAlmostEqual(sum(a["montant"] for a in ind["achats"]), 2 * (55 - 1), places=2)
        self.assertAlmostEqual(ind["cash"], 0.0)

    def test_sans_taux_pas_de_versement_puis_rattrapage(self):
        cours = cours_test()
        del cours[m.DEVISE]
        dates = [b["date"] for b in cours["SPY"] if b["date"] >= "2026-12-01"]
        e = m.etat_vide()
        m.mettre_a_jour(e, tranche(cours, dates[0]), maintenant_apres(dates[0]))
        self.assertEqual(e["versements"], [])
        cours[m.DEVISE] = devise()
        m.mettre_a_jour(e, tranche(cours, dates[1]), maintenant_apres(dates[1]))
        self.assertEqual([v["date"] for v in e["versements"]], [dates[1]], "versement fait à la séance suivante")


class TestBot(unittest.TestCase):
    def _etat_avec_cash(self, cash=1000.0):
        e = m.etat_vide()
        e["bot"]["cash"] = cash
        e["versements"].append({"mois": "2026-10", "date": "2026-10-01", "eur": 50, "taux": 1.1, "usd": 55})
        return e

    def test_achat_fractionne_et_frais(self):
        e = self._etat_avec_cash(1000.0)
        hist = serie_cassure(fin=date(2026, 10, 30))
        d = hist[-1]["date"]
        m.jouer_seance(e, d, {"SPY": serie(260, fin=date(2026, 10, 30)), "AAA": hist}, 1.1)
        b = e["bot"]
        self.assertEqual(len(b["positions"]), 1)
        p = b["positions"][0]
        self.assertNotEqual(p["actions"], int(p["actions"]), "morceau d'action")
        self.assertLessEqual(p["cout"], 1000 * 0.20 + 1 + 1e-6)
        self.assertLessEqual(p["actions"] * (p["prix_entree"] - p["stop"]), 1000 * 0.01 + 1e-6)
        self.assertEqual((b["ordres"], b["frais"]), (1, 1.0))
        self.assertAlmostEqual(b["cash"], 1000 - p["cout"], places=2)

    def test_pas_d_ordre_trop_petit(self):
        e = self._etat_avec_cash(20.0)   # 20 % de 20 $ = 4 $ < 5 $ minimum
        hist = serie_cassure(fin=date(2026, 10, 30))
        m.jouer_seance(e, hist[-1]["date"], {"SPY": serie(260, fin=date(2026, 10, 30)), "AAA": hist}, 1.1)
        self.assertEqual(e["bot"]["positions"], [])
        self.assertEqual(e["bot"]["frais"], 0)

    def test_vente_au_stop_avec_frais(self):
        e = self._etat_avec_cash(0.0)
        e["versements"][0]["mois"] = "2026-11"  # versement du mois déjà fait
        e["bot"]["positions"].append({"symbole": "AAA", "date_entree": "2026-11-02", "prix_entree": 100.0,
                                      "actions": 0.5, "cout": 51.0, "stop": 95.0, "objectif": 110.0, "jours": 0,
                                      "dernier_cours": 100.0})
        d = "2026-11-03"
        jour = {"date": d, "open": 99, "high": 100, "low": 94, "close": 96}
        spy = [{"date": d, "open": 1, "high": 1, "low": 1, "close": 1}]
        m.jouer_seance(e, d, {"AAA": [jour], "SPY": spy}, 1.1)
        t = e["bot"]["transactions"][0]
        self.assertEqual(t["motif"], "stop")
        self.assertAlmostEqual(e["bot"]["cash"], 0.5 * 95 - 1)
        self.assertAlmostEqual(t["pnl"], 0.5 * 95 - 1 - 51.0)

    def test_comptabilite_sur_plusieurs_mois(self):
        cours = cours_test()
        dates = [b["date"] for b in cours["SPY"] if b["date"] >= "2026-07-01"]
        e = m.etat_vide()
        for d in dates:
            m.mettre_a_jour(e, tranche(cours, d), maintenant_apres(d))
            self.assertGreaterEqual(e["bot"]["cash"], -1e-6)
        b = e["bot"]
        latent = sum(p["actions"] * p["dernier_cours"] - p["cout"] for p in b["positions"])
        realise = sum(t["pnl"] for t in b["transactions"])
        verse_usd = sum(v["usd"] for v in e["versements"])
        self.assertAlmostEqual(e["historique"][-1]["bot_usd"], verse_usd + realise + latent, delta=0.05)
        self.assertGreater(b["ordres"], 0)
        r = m.resume(e)
        self.assertEqual(r["verse"], 50 * 6)
        self.assertIn("€ versés", r["verdict"])

    def test_relance_meme_jour_ne_rejoue_rien(self):
        cours = cours_test()
        d = [b["date"] for b in cours["SPY"]][-1]
        e = m.etat_vide()
        self.assertEqual(m.mettre_a_jour(e, cours, maintenant_apres(d)), 1)
        self.assertEqual(m.mettre_a_jour(e, cours, maintenant_apres(d)), 0)
        self.assertEqual(len(e["versements"]), 1)


class TestBoutEnBout(unittest.TestCase):
    def test_lancement_complet_trois_onglets(self):
        from bot.portefeuille import executer_reels
        d = tempfile.mkdtemp()
        try:
            fin = date(2026, 10, 30)
            series = {s: serie(260, graine=i, derive=0.003, vol=0.01, fin=fin) for i, s in enumerate(["SPY"] + ar.LISTE)}
            series[m.DEVISE] = devise(260, fin=fin)

            def faux(url):
                for s, b in series.items():
                    if f"/chart/{s}?" in url:
                        return en_yahoo(b)
                raise OSError("inconnu")
            for _ in range(2):  # deux lancements : le second ne doit rien rejouer
                executer_reels(telecharger=faux, maintenant=maintenant_apres(fin.isoformat()),
                               dossier_etat=os.path.join(d, "etat"), dossier_page=d, dossier_stop=d, bavard=False)
            e = m.charger_etat(os.path.join(d, "etat", "mensuel.json"))
            self.assertEqual(len(e["historique"]), 1)
            self.assertEqual(e["verse_eur"], 50)
            for f in ["actions.html", "mensuel.html"]:
                with open(os.path.join(d, f), encoding="utf-8") as fh:
                    page = fh.read()
                self.assertIn("50 €/mois", page, "onglet présent dans la navigation")
                self.assertIn("Day trading", page)
            with open(os.path.join(d, "mensuel.html"), encoding="utf-8") as fh:
                page = fh.read()
            self.assertIn("Total versé", page)
            self.assertIn("Verdict.", page)
        finally:
            shutil.rmtree(d)

    def test_devise_indisponible_ne_bloque_rien(self):
        from bot.portefeuille import executer_reels
        d = tempfile.mkdtemp()
        try:
            fin = date(2026, 10, 30)
            series = {s: serie(260, graine=i, fin=fin) for i, s in enumerate(["SPY"] + ar.LISTE)}

            def faux(url):
                for s, b in series.items():
                    if f"/chart/{s}?" in url:
                        return en_yahoo(b)
                raise OSError("bloqué")
            executer_reels(telecharger=faux, maintenant=maintenant_apres(fin.isoformat()),
                           dossier_etat=os.path.join(d, "etat"), dossier_page=d, dossier_stop=d, bavard=False)
            self.assertTrue(os.path.exists(os.path.join(d, "actions.html")))
            with open(os.path.join(d, "mensuel.html"), encoding="utf-8") as fh:
                self.assertIn("taux euro/dollar indisponible", fh.read())
        finally:
            shutil.rmtree(d)

    def test_stooq_devise(self):
        from bot.actions_donnees import cours_journaliers
        urls = []

        def faux(url):
            urls.append(url)
            if "yahoo" in url:
                raise OSError("x")
            return b"Date,Open,High,Low,Close,Volume\n2026-10-30,1.1,1.1,1.1,1.1,0\n"
        cours_journaliers("EURUSD=X", faux)
        self.assertIn("s=eurusd&", urls[-1])


if __name__ == "__main__":
    unittest.main()
