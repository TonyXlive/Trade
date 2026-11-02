"""Calcul de la taille de position (critère de Kelly) pour un contrat binaire.

Un contrat acheté au prix c paie 1 si on a raison, 0 sinon.
Cote nette b = (1 - c) / c.  Kelly : f* = (p*b - q) / b = (p - c) / (1 - c).

Utilisation en ligne de commande :
    python scripts/kelly_size.py --proba 0.62 --prix 0.50 --capital 10000
"""
import argparse
import math


def kelly_complet(proba: float, prix: float) -> float:
    """Fraction du capital donnée par Kelly complet (0 si pas d'avantage)."""
    if not (0 < prix < 1) or not (0 <= proba <= 1):
        raise ValueError("proba doit être entre 0 et 1, prix strictement entre 0 et 1")
    b = (1 - prix) / prix
    q = 1 - proba
    f = (proba * b - q) / b
    return max(0.0, f)


def taille_position(proba: float, prix: float, capital: float,
                    fraction_kelly: float = 0.25, max_par_position: float = 0.05) -> dict:
    """Montant à miser : Kelly fractionné, plafonné au max par position."""
    f_complet = kelly_complet(proba, prix)
    f_retenu = min(f_complet * fraction_kelly, max_par_position)
    montant = math.floor(capital * f_retenu * 100) / 100  # arrondi vers le bas : jamais au-dessus du plafond
    return {
        "kelly_complet": round(f_complet, 4),
        "fraction_retenue": round(f_retenu, 4),
        "montant": montant,
        "nb_contrats": int(montant // prix) if prix > 0 else 0,
    }


def valeur_attendue(proba: float, prix: float) -> float:
    """Gain moyen attendu par euro misé : EV = p*b - (1-p)."""
    b = (1 - prix) / prix
    return proba * b - (1 - proba)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Calculateur de position Kelly")
    ap.add_argument("--proba", type=float, required=True, help="probabilité estimée de gain")
    ap.add_argument("--prix", type=float, required=True, help="prix du contrat (0-1)")
    ap.add_argument("--capital", type=float, required=True)
    ap.add_argument("--fraction", type=float, default=0.25, help="fraction de Kelly (défaut 0.25)")
    ap.add_argument("--max", type=float, default=0.05, help="plafond par position (défaut 5 %)")
    a = ap.parse_args()
    r = taille_position(a.proba, a.prix, a.capital, a.fraction, a.max)
    print(f"Kelly complet     : {r['kelly_complet']:.2%}")
    print(f"Fraction retenue  : {r['fraction_retenue']:.2%}")
    print(f"Montant à miser   : {r['montant']:.2f}")
    print(f"Contrats          : {r['nb_contrats']}")
    print(f"Valeur attendue   : {valeur_attendue(a.proba, a.prix):+.3f} par unité misée")
