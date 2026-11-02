"""Tests automatiques. Lancer : python -m unittest discover -s tests -v"""
import json
import os
import shutil
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from scripts.kelly_size import kelly_complet, taille_position, valeur_attendue  # noqa: E402
from scripts.validate_risk import valider, var95  # noqa: E402
from bot.simulation import Simulation  # noqa: E402
from bot.capitalisation import indicateurs, classer_perte, BaseConnaissances  # noqa: E402
from bot.main import main  # noqa: E402


def charger_config():
    with open(os.path.join(RACINE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


REGLES = dict(charger_config()["risque"], avantage_min=0.04)


def etat_vide(capital=10000):
    return {"capital": capital, "capital_pic": capital, "perte_jour": 0, "capital_debut_jour": capital,
            "positions": [], "cout_ia_jour": 0}


def ordre(avantage=0.08, mise=200, prix=0.5, proba=0.58):
    return {"avantage": avantage, "mise": mise, "mise_kelly": mise, "prix": prix, "proba": proba}


class TestKelly(unittest.TestCase):
    def test_exemple_guide(self):
        # 70 % de chances, gain 2 pour 1 -> prix 1/3 ; Kelly = 0.55 (formule binaire)
        self.assertAlmostEqual(kelly_complet(0.70, 1 / 3), 0.55, places=4)

    def test_sans_avantage(self):
        self.assertEqual(kelly_complet(0.40, 0.50), 0.0)
        self.assertEqual(kelly_complet(0.50, 0.50), 0.0)

    def test_fraction_et_plafond(self):
        r = taille_position(0.70, 0.50, 10000, fraction_kelly=0.25, max_par_position=0.05)
        self.assertAlmostEqual(r["kelly_complet"], 0.40)
        self.assertEqual(r["montant"], 500.0)  # 0.25*0.40 = 10 % plafonné à 5 %
        r = taille_position(0.55, 0.50, 10000, 0.25, 0.05)
        self.assertEqual(r["montant"], 250.0)  # 0.25*0.10 = 2.5 %

    def test_jamais_au_dessus_du_plafond(self):
        for cap in [9999.997, 10133.33, 777.777]:
            r = taille_position(0.9, 0.3, cap, 1.0, 0.05)
            self.assertLessEqual(r["montant"], cap * 0.05)

    def test_valeur_attendue(self):
        self.assertAlmostEqual(valeur_attendue(0.6, 0.5), 0.2)
        self.assertAlmostEqual(valeur_attendue(0.5, 0.5), 0.0)

    def test_entrees_invalides(self):
        with self.assertRaises(ValueError):
            kelly_complet(0.5, 0)
        with self.assertRaises(ValueError):
            kelly_complet(1.2, 0.5)


class TestRisque(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dossier)

    def test_ordre_correct_accepte(self):
        ok, motifs = valider(ordre(), etat_vide(), REGLES, self.dossier)
        self.assertTrue(ok, motifs)

    def test_avantage_insuffisant(self):
        ok, motifs = valider(ordre(avantage=0.03), etat_vide(), REGLES, self.dossier)
        self.assertFalse(ok)
        self.assertTrue(any("avantage" in m for m in motifs))

    def test_avantage_pile_au_seuil_refuse(self):
        ok, _ = valider(ordre(avantage=0.04), etat_vide(), REGLES, self.dossier)
        self.assertFalse(ok)

    def test_plafond_position(self):
        ok, motifs = valider(ordre(mise=600), etat_vide(), REGLES, self.dossier)
        self.assertFalse(ok)
        self.assertIn("mise > plafond par position", motifs)

    def test_mise_superieure_a_kelly(self):
        o = ordre(mise=300)
        o["mise_kelly"] = 200
        ok, motifs = valider(o, etat_vide(), REGLES, self.dossier)
        self.assertIn("mise supérieure au calcul de Kelly", motifs)

    def test_exposition(self):
        e = etat_vide()
        e["positions"] = [{"mise": 480, "prix": 0.5, "proba": 0.55}] * 5  # 2 400 déjà exposés
        ok, motifs = valider(ordre(mise=200), e, REGLES, self.dossier)
        self.assertIn("exposition totale dépassée", motifs)

    def test_nombre_positions(self):
        e = etat_vide(1_000_000)
        e["positions"] = [{"mise": 1, "prix": 0.5, "proba": 0.55}] * 15
        ok, motifs = valider(ordre(), e, REGLES, self.dossier)
        self.assertIn("nombre max de positions atteint", motifs)

    def test_drawdown(self):
        e = etat_vide(9100)
        e["capital_pic"] = 10000  # -9 %
        ok, motifs = valider(ordre(mise=100), e, REGLES, self.dossier)
        self.assertTrue(any("drawdown" in m for m in motifs))

    def test_perte_jour(self):
        e = etat_vide(8400)
        e["capital_debut_jour"], e["perte_jour"], e["capital_pic"] = 10000, 1600, 8400
        ok, motifs = valider(ordre(mise=100), e, REGLES, self.dossier)
        self.assertTrue(any("perte du jour" in m for m in motifs))

    def test_budget_ia(self):
        e = etat_vide()
        e["cout_ia_jour"] = 51
        ok, motifs = valider(ordre(), e, REGLES, self.dossier)
        self.assertIn("budget IA du jour épuisé", motifs)

    def test_kill_switch(self):
        open(os.path.join(self.dossier, "STOP"), "w").close()
        ok, motifs = valider(ordre(), etat_vide(), REGLES, self.dossier)
        self.assertFalse(ok)
        self.assertTrue(any("STOP" in m for m in motifs))

    def test_var(self):
        self.assertEqual(var95([]), 0.0)
        v1 = var95([{"mise": 100, "prix": 0.5, "proba": 0.5}])
        v2 = var95([{"mise": 100, "prix": 0.5, "proba": 0.5}] * 4)
        self.assertGreater(v2, v1)
        self.assertLess(v2, 4 * v1)  # diversification


class TestCapitalisation(unittest.TestCase):
    def test_indicateurs(self):
        tx = [{"pnl": 100}, {"pnl": -50}, {"pnl": 50}, {"pnl": -50}]
        courbe = [1000, 1100, 1050, 1100, 1050]
        preds = [{"p_modele": 0.8, "p_marche": 0.6, "resultat": 1}, {"p_modele": 0.2, "p_marche": 0.4, "resultat": 0}]
        r = indicateurs(tx, courbe, preds)
        self.assertEqual(r["taux_reussite"], 0.5)
        self.assertAlmostEqual(r["facteur_profit"], 1.5)
        self.assertAlmostEqual(r["drawdown_max"], 50 / 1100)
        self.assertAlmostEqual(r["brier_modele"], 0.04)
        self.assertAlmostEqual(r["brier_marche"], 0.16)
        self.assertAlmostEqual(r["rendement"], 0.05)

    def test_classement_pertes(self):
        base = {"slippage": 0.0, "proba_reelle_cote": 0.7, "prix_effectif": 0.5}
        self.assertTrue(classer_perte(base).startswith("variance"))
        self.assertEqual(classer_perte(dict(base, proba_reelle_cote=0.4)), "mauvaise prédiction")
        self.assertEqual(classer_perte(dict(base, slippage=0.015)), "mauvaise exécution")

    def test_base_exclut_categorie_mauvaise(self):
        b = BaseConnaissances(min_echantillon=10)
        for i in range(20):
            res = i % 2
            b.enregistrer_prediction("crypto", 0.9 if res == 0 else 0.1, 0.5, res)  # toujours faux
            b.enregistrer_prediction("sport", 0.9 if res == 1 else 0.1, 0.5, res)   # toujours juste
        b.consolider(5)
        self.assertTrue(b.categorie_exclue("crypto"))
        self.assertFalse(b.categorie_exclue("sport"))
        self.assertEqual(len(b.lecons), 1)


class TestSimulation(unittest.TestCase):
    def test_reproductible(self):
        cfg = charger_config()
        a = Simulation(cfg, graine=5).lancer(30)
        b = Simulation(cfg, graine=5).lancer(30)
        self.assertEqual(a["valeur_finale"], b["valeur_finale"])

    def test_regles_respectees_pendant_la_simulation(self):
        cfg = charger_config()
        r = cfg["risque"]
        for graine in range(15):
            sim = Simulation(cfg, graine=graine)
            for j in range(1, 91):
                sim.jour(j)
                self.assertLessEqual(len(sim.positions), r["max_positions"])
                for p in sim.positions:
                    if p["jour_entree"] == j:
                        self.assertGreater(p["avantage"], cfg["prediction"]["avantage_min"])
                        self.assertLessEqual(p["slippage"], r["slippage_max"])
                        self.assertGreaterEqual(p["contrats"], 1)
                self.assertGreaterEqual(sim.cash, -1e-6, "jamais de solde négatif")

    def test_comptabilite(self):
        """Valeur finale = capital de départ + gains/pertes réalisés + latent des positions ouvertes."""
        cfg = charger_config()
        for graine in range(10):
            sim = Simulation(cfg, graine=graine)
            res = sim.lancer()
            realise = sum(t["pnl"] for t in sim.transactions if t["pnl"] is not None)
            latent = sim.valeur_portefeuille() - sim.cash - sum(p["mise"] for p in sim.positions)
            self.assertAlmostEqual(res["valeur_finale"], cfg["capital_depart"] + realise + latent, delta=0.05)

    def test_kill_switch_bloque_tout(self):
        d = tempfile.mkdtemp()
        try:
            open(os.path.join(d, "STOP"), "w").close()
            res = Simulation(charger_config(), graine=1, dossier_stop=d).lancer(20)
            self.assertEqual(res["nb_transactions"], 0)
            self.assertTrue(res["arret_stop"])
            self.assertEqual(res["valeur_finale"], 10000)
        finally:
            shutil.rmtree(d)

    def test_biais_crypto_detecte(self):
        """Le bot doit apprendre à éviter la catégorie où ses modèles sont biaisés."""
        cfg = charger_config()
        crypto, autres = 0, 0
        for g in range(20):
            for l in Simulation(cfg, graine=g).lancer()["lecons"]:
                if l["categorie"] == "crypto":
                    crypto += 1
                else:
                    autres += 1
        self.assertGreaterEqual(crypto, 12)
        self.assertGreater(crypto / 20, autres / (20 * 5))

    def test_sorties_generees(self):
        d = tempfile.mkdtemp()
        try:
            main(["--jours", "20", "--monte-carlo", "3", "--sortie", d])
            for f in ["rapport.html", "transactions.csv", "failure_log.md"]:
                self.assertTrue(os.path.getsize(os.path.join(d, f)) > 0, f)
            with open(os.path.join(d, "rapport.html"), encoding="utf-8") as f:
                html = f.read()
            self.assertIn("Rapport de simulation", html)
            self.assertIn("rejoué 3 fois", html)
        finally:
            shutil.rmtree(d)

    def test_config_optimiste_valide(self):
        with open(os.path.join(RACINE, "config_optimiste.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        self.assertEqual(cfg["prediction"]["correlation_avec_marche"], 0.0)
        Simulation(cfg, graine=1).lancer(10)


if __name__ == "__main__":
    unittest.main()


class TestPortefeuille(unittest.TestCase):
    """Mode continu : sauvegarde, reprise, rattrapage, page de suivi."""

    def setUp(self):
        from datetime import date
        self.d = tempfile.mkdtemp()
        self.etat, self.page = os.path.join(self.d, "etat"), os.path.join(self.d, "docs")
        self.d0 = date(2026, 11, 3)

    def tearDown(self):
        shutil.rmtree(self.d)

    def lancer(self, decalage, **kw):
        from datetime import timedelta
        from bot.portefeuille import executer
        return executer(dossier_etat=self.etat, dossier_page=self.page, date_jour=self.d0 + timedelta(days=decalage),
                        dossier_stop=self.d, bavard=False, **kw)

    def test_un_jour_par_jour_reel(self):
        _, meta, joues = self.lancer(0, graine=3)
        self.assertEqual((meta["dernier_jour"], joues), (1, 1))
        _, meta, joues = self.lancer(0)
        self.assertEqual((meta["dernier_jour"], joues), (1, 0), "deux lancements le même jour = une seule journée")
        _, meta, joues = self.lancer(1)
        self.assertEqual((meta["dernier_jour"], joues), (2, 1))

    def test_rattrapage(self):
        self.lancer(0, graine=3)
        _, meta, joues = self.lancer(6)
        self.assertEqual((meta["dernier_jour"], joues), (7, 6))
        self.assertEqual(meta["dates"]["7"], "2026-11-09")

    def test_reprise_identique_a_une_traite(self):
        """Arrêter et reprendre chaque jour donne exactement le même résultat que tout jouer d'un coup."""
        for i in range(20):
            sim, _, _ = self.lancer(i, graine=8) if i == 0 else self.lancer(i)
        cfg = charger_config()
        directe = Simulation(cfg, graine=8, dossier_stop=self.d)
        for j in range(1, 21):
            directe.jour(j)
        self.assertAlmostEqual(sim.courbe[-1], directe.courbe[-1], places=6)
        self.assertEqual(len(sim.transactions), len(directe.transactions))

    def test_nouveau_repart_de_zero(self):
        self.lancer(0, graine=3)
        self.lancer(10)
        sim, meta, _ = self.lancer(12, nouveau=True, graine=4)
        self.assertEqual(meta["dernier_jour"], 1)
        self.assertEqual(meta["date_debut"], "2026-11-15")

    def test_stop_puis_reprise(self):
        self.lancer(0, graine=3)
        open(os.path.join(self.d, "STOP"), "w").close()
        sim, _, _ = self.lancer(5)
        nb = len(sim.transactions)
        self.assertTrue(sim.arret_stop)
        sim, _, _ = self.lancer(8)
        self.assertEqual(len(sim.transactions), nb, "aucun ordre tant que STOP est là")
        os.remove(os.path.join(self.d, "STOP"))
        sim, _, _ = self.lancer(30)
        self.assertFalse(sim.arret_stop)
        self.assertGreater(len(sim.transactions), nb, "le bot repart après suppression de STOP")

    def test_page_suivi(self):
        for i in range(15):
            self.lancer(i, graine=3) if i == 0 else self.lancer(i)
        for f in ["index.html", "manifest.json", "icone.svg", "historique.csv", ".nojekyll"]:
            self.assertTrue(os.path.exists(os.path.join(self.page, f)), f)
        with open(os.path.join(self.page, "index.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Journée 15", page)
        self.assertIn("Positions ouvertes", page)
        with open(os.path.join(self.page, "historique.csv"), encoding="utf-8-sig") as f:
            self.assertEqual(len(f.read().strip().splitlines()), 16)

    def test_sauvegarde_legere(self):
        self.lancer(0, graine=3)
        self.lancer(59)
        self.assertLess(os.path.getsize(os.path.join(self.etat, "simulation.pkl.gz")), 300_000)


class TestAjoutsDayTrader(unittest.TestCase):
    """Règles reprises de day-trader-skill."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dossier)

    def test_risque_engage_du_jour(self):
        e = etat_vide()
        e["mises_jour"] = 1400  # 14 % déjà engagés aujourd'hui, limite 15 %
        ok, motifs = valider(ordre(mise=200), e, REGLES, self.dossier)
        self.assertIn("risque engagé du jour au-delà de la limite", motifs)
        e["mises_jour"] = 1200
        ok, motifs = valider(ordre(mise=200), e, REGLES, self.dossier)
        self.assertTrue(ok, motifs)

    def test_ordres_du_jour(self):
        e = etat_vide()
        e["ordres_jour"] = 8
        ok, motifs = valider(ordre(), e, REGLES, self.dossier)
        self.assertIn("nombre max d'ordres du jour atteint", motifs)

    def test_limites_journalieres_en_simulation(self):
        cfg = charger_config()
        r = cfg["risque"]
        for g in range(10):
            sim = Simulation(cfg, graine=g)
            for j in range(1, 61):
                debut = sim.valeur_portefeuille()
                sim.jour(j)
                du_jour = [t for t in sim.transactions if t["jour_entree"] == j]
                self.assertLessEqual(len(du_jour), r["max_ordres_jour"])
                # le capital de début de journée est mesuré après les échéances : marge pour ce décalage
                self.assertLessEqual(sum(t["mise"] for t in du_jour), debut * r["max_risque_engage_jour"] * 1.1 + 1)

    def test_verdict(self):
        from bot.capitalisation import verdict_honnete
        self.assertIsNone(verdict_honnete([])["necessaire"])
        tx = [{"pnl": 50, "contrats": 100, "mise": 50}, {"pnl": -50, "contrats": 100, "mise": 50}]
        v = verdict_honnete(tx)
        self.assertAlmostEqual(v["necessaire"], 0.5)
        self.assertAlmostEqual(v["obtenu"], 0.5)
        self.assertTrue(v["texte"].startswith("Proche d'un pile ou face"))
        self.assertIn("trop peu pour conclure", v["texte"])
        tx = [{"pnl": 60, "contrats": 100, "mise": 40}] * 3 + [{"pnl": -40, "contrats": 100, "mise": 40}]
        self.assertTrue(verdict_honnete(tx)["texte"].startswith("Nettement gagnant"))

    def test_graine_affichee(self):
        r = Simulation(charger_config(), graine=77).lancer(5)
        self.assertEqual(r["graine"], 77)
