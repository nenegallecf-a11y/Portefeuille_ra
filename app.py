
# PORTFOLIO RISK ANALYZER 
# Tableau de bord interactif pour analyser des portefeuille d'actions: données Yahoo finace 
# Premier calcul : Calculer ou Entrée dans le formulaire.

import io
import re
import ssl
import unicodedata
import urllib.request

from datetime import date, timedelta
from decimal import Decimal

import certifi
import numpy as np
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go

from scipy.optimize import minimize



# CONFIGURATION

st.set_page_config(
    page_title="Portfolio Risk Analyzer",
    page_icon="📈",
    layout="wide",
)

# IMPORTANT :
# Aucune règle CSS ne force la couleur des champs ou des listes.
# Leurs couleurs sont définies dans le thème natif de Streamlit.

st.markdown("""
<style>
.block-container {
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* Cartes KPI : dégradé bleu nuit lumineux */

[data-testid="stMetric"] {
    min-height: 125px;
    padding: 20px;
    margin-bottom: 12px;
    border-radius: 17px;
    border: 1px solid rgba(99, 161, 245, 0.45);
    background:
        radial-gradient(
            ellipse at top right,
            rgba(64, 145, 255, 0.48),
            transparent 65%
        ),
        linear-gradient(
            125deg,
            #071426 0%,
            #112C52 58%,
            #174E91 100%
        );
    box-shadow:
        0 9px 24px rgba(16, 45, 88, 0.16),
        inset 0 1px 0 rgba(194, 221, 255, 0.22);
}

[data-testid="stMetricLabel"],
[data-testid="stMetricLabel"] p {
    color: #D8E8FD !important;
}

[data-testid="stMetricValue"],
[data-testid="stMetricValue"] > div {
    color: #FFFFFF !important;
    font-size: clamp(1.5rem, 2.5vw, 2.6rem) !important;
    font-weight: 700;
    letter-spacing: -0.035em;
}

[data-testid="stMetricLabel"] svg {
    color: #D8E8FD;
}

/* Graphiques */

[data-testid="stPlotlyChart"] {
    border-radius: 15px;
    overflow: hidden;
    border: 1px solid #29466D;
    background: #0B1930;
    margin-bottom: 18px;
    box-shadow: 0 8px 22px rgba(16, 45, 88, 0.10);
}

.graphique-vide {
    height: 250px;
    border: 1px dashed #3B5E86;
    border-radius: 15px;
    background: #0B1930;
    display: flex;
    align-items: center;
    justify-content: center;
    text-align: center;
    color: #C7D8EF;
    padding: 20px;
    margin-bottom: 20px;
}
</style>
""", unsafe_allow_html=True)

st.title("📈 Portfolio Risk Analyzer")
st.caption(
    "Construisez votre portefeuille, analysez son historique "
    "et comparez différentes allocations."
)

statut = st.empty()



# ÉTAT


valeurs_initiales = {
    "panier": {},
    "connues": {},
    "analyse": None,
    "calcul_demarre": False,
    "derniere_tentative": None,
    "erreur": "",
    "revision": 0,
    "mode": "Égale",
    "parametres": {
        "debut": date(2023, 1, 1),
        "fin": date.today(),
        "capital": 10000.0,
        "taux": 2.0,
    },
    "poids_memorises": {},
}

for cle, valeur in valeurs_initiales.items():
    if cle not in st.session_state:
        st.session_state[cle] = valeur

S = st.session_state


def changement_selection():
    S.revision += 1
    S.mode = "Égale"
    S.poids_memorises = {}
    S.derniere_tentative = None
    S.erreur = ""

    if not S.panier:
        S.analyse = None
        S.calcul_demarre = False


# ------------------------------------------------------------
# CATALOGUE
# ------------------------------------------------------------

def normaliser(texte):
    texte = unicodedata.normalize("NFKD", str(texte))
    return "".join(
        c for c in texte if not unicodedata.combining(c)
    ).casefold()


def etiquette(titre):
    return (
        f"{titre['nom']} · {titre['symbole']} "
        f"· {titre.get('place', '')}"
    )


@st.cache_data(ttl=86400, show_spinner=False)
def charger_catalogue():
    contexte_ssl = ssl.create_default_context(
        cafile=certifi.where()
    )

    sources = [
        (
            "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
            "Symbol",
            "Nasdaq",
        ),
        (
            "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
            "ACT Symbol",
            "Marché américain",
        ),
    ]

    catalogue = {}
    erreurs = []

    for url, colonne_symbole, place in sources:
        try:
            requete = urllib.request.Request(
                url,
                headers={"User-Agent": "PortfolioRiskAnalyzer/1.0"},
            )

            with urllib.request.urlopen(
                requete,
                context=contexte_ssl,
                timeout=15,
            ) as reponse:
                contenu = reponse.read().decode("utf-8-sig")

            table = pd.read_csv(
                io.StringIO(contenu),
                sep="|",
                dtype=str,
            )

            for _, ligne in table.iterrows():
                if ligne.get("Test Issue") != "N":
                    continue

                if ligne.get("ETF") == "Y":
                    continue

                symbole = str(
                    ligne.get(colonne_symbole, "")
                ).strip()

                nom = str(
                    ligne.get("Security Name", "")
                ).strip()

                if not re.fullmatch(
                    r"[A-Z]{1,6}(?:\.[A-Z])?", symbole
                ):
                    continue

                if not nom or nom == "nan":
                    continue

                symbole = symbole.replace(".", "-")

                catalogue[symbole] = {
                    "symbole": symbole,
                    "nom": nom,
                    "place": place,
                }

        except Exception as erreur:
            erreurs.append(str(erreur))

    return catalogue, erreurs


@st.cache_data(ttl=3600, show_spinner=False)
def verifier_action(symbole):
    info = yf.Ticker(symbole).get_info()

    if info.get("quoteType") != "EQUITY":
        raise ValueError(
            "Ce symbole n'a pas pu être confirmé comme action sur Yahoo."
        )

    return {
        "symbole": info.get("symbol") or symbole,
        "nom": (
            info.get("shortName")
            or info.get("longName")
            or symbole
        ),
        "place": (
            info.get("fullExchangeName")
            or info.get("exchange")
            or ""
        ),
    }



# DONNÉES ET IMPUTATION


def nettoyer(serie):
    serie = serie.copy()

    serie.index = (
        pd.to_datetime(serie.index)
        .tz_localize(None)
        .normalize()
    )

    serie = serie[
        ~serie.index.duplicated(keep="last")
    ].sort_index()

    serie = pd.to_numeric(
        serie, errors="coerce"
    ).replace([np.inf, -np.inf], np.nan)

    # Conservation des NA.
    if not serie.notna().any():
        raise ValueError("Aucune observation exploitable.")

    if (serie <= 0).any():
        raise ValueError("Cours ou taux nul ou négatif.")

    return serie


def imputer(serie, calendrier, jours):
    index = serie.index.union(calendrier).sort_values()
    etendue = serie.reindex(index)

    date_derniere_observation = pd.Series(
        index, index=index
    ).where(etendue.notna()).ffill()

    age = (
        pd.Series(index, index=index)
        - date_derniere_observation
    )

    resultat = etendue.ffill().where(
        age <= pd.Timedelta(days=jours)
    ).reindex(calendrier)

    masque = (
        serie.reindex(calendrier).isna()
        & resultat.notna()
    )

    return resultat, masque


@st.cache_data(ttl=3600, show_spinner=False)
def telecharger_action(symbole, debut, fin_exclusive):
    titre = yf.Ticker(symbole)

    historique = titre.history(
        start=debut,
        end=fin_exclusive,
        interval="1d",
        auto_adjust=True,
        actions=False,
        timeout=20,
    )

    if historique.empty or "Close" not in historique:
        raise ValueError(
            f"{symbole} : historique indisponible."
        )

    devise = None

    try:
        devise = titre.get_history_metadata().get("currency")
    except Exception:
        pass

    if not devise:
        try:
            devise = titre.fast_info["currency"]
        except Exception:
            pass

    if not devise:
        raise ValueError(f"{symbole} : devise inconnue.")

    return nettoyer(historique["Close"]), devise


@st.cache_data(ttl=3600, show_spinner=False)
def telecharger_change(devise, debut, fin_exclusive):
    for symbole, inverser in [
        (f"{devise}EUR=X", False),
        (f"EUR{devise}=X", True),
    ]:
        try:
            historique = yf.Ticker(symbole).history(
                start=debut,
                end=fin_exclusive,
                interval="1d",
                auto_adjust=False,
                actions=False,
                timeout=20,
            )

            if historique.empty or "Close" not in historique:
                continue

            taux = nettoyer(historique["Close"])
            return 1 / taux if inverser else taux

        except Exception:
            continue

    raise ValueError(
        f"Taux de change {devise}/EUR indisponible."
    )


# INDICATEURS ET PORTEFEUILLE


def poids_egaux(nombre):
    if nombre == 0:
        return []

    centiemes = [10000 // nombre] * nombre
    centiemes[-1] += 10000 - sum(centiemes)

    return [v / 100 for v in centiemes]


def calculer_indicateurs(valeur, rf):
    rendements = valeur.pct_change(
        fill_method=None
    ).iloc[1:]

    if rendements.isna().any():
        raise ValueError("Rendements incomplets.")

    sigma = rendements.std(ddof=1)

    annees = (
        valeur.index[-1] - valeur.index[0]
    ).days / 365.25

    ratio = valeur.iloc[-1] / valeur.iloc[0]
    taux_jour = (1 + rf) ** (1 / 252) - 1

    return {
        "finale": float(valeur.iloc[-1]),
        "performance": float(ratio - 1),
        "cagr": float(ratio ** (1 / annees) - 1),
        "volatilite": float(sigma * np.sqrt(252)),
        "sharpe": (
            float(
                (rendements.mean() - taux_jour)
                / sigma
                * np.sqrt(252)
            )
            if sigma > 1e-12 else np.nan
        ),
        "var": float(rendements.quantile(.05)),
        "drawdown": float(
            (valeur / valeur.cummax() - 1).min()
        ),
    }


def analyser(panier, allocations, debut, fin, capital, rf):
    dernier_jour = min(
        fin,
        date.today() - timedelta(days=1),
    )

    if dernier_jour <= debut:
        raise ValueError(
            "La période doit contenir plusieurs séances terminées."
        )

    fin_exclusive = dernier_jour + timedelta(days=1)

    sous_unites = {
        "GBp": ("GBP", .01),
        "GBX": ("GBP", .01),
        "ZAc": ("ZAR", .01),
        "ILA": ("ILS", .01),
    }

    sources = {}
    devises = {}

    for symbole in panier:
        cours, devise_source = telecharger_action(
            symbole, debut, fin_exclusive
        )

        devise, facteur = sous_unites.get(
            devise_source,
            (devise_source, 1.0),
        )

        if len(devise) != 3 or not devise.isupper():
            raise ValueError(
                f"{symbole} : unité non prise en charge "
                f"({devise_source})."
            )

        sources[symbole] = cours * facteur
        devises[symbole] = devise

    premiere = max(
        s.first_valid_index() for s in sources.values()
    )
    derniere = min(
        s.last_valid_index() for s in sources.values()
    )

    dates = set()

    for serie in sources.values():
        dates.update(serie.index)

    calendrier = pd.DatetimeIndex(sorted(dates))

    calendrier = calendrier[
        (calendrier >= premiere)
        & (calendrier <= derniere)
    ]

    if len(calendrier) < 60:
        raise ValueError(
            "Au moins 60 observations communes sont nécessaires. "
            "Élargissez la période ou changez les titres."
        )

    convertis = {}
    taux_charges = {}
    audit_interne = {}

    for symbole, source in sources.items():
        cours_local, masque_cours = imputer(
            source, calendrier, 4
        )

        if cours_local.isna().any():
            raise ValueError(
                f"{symbole} : historique insuffisamment complet."
            )

        devise = devises[symbole]
        nb_taux_imputes = 0

        if devise != "EUR":
            if devise not in taux_charges:
                taux_charges[devise] = telecharger_change(
                    devise,
                    debut - timedelta(days=10),
                    fin_exclusive,
                )

            taux, masque_taux = imputer(
                taux_charges[devise], calendrier, 5
            )

            if taux.isna().any():
                raise ValueError(
                    f"{symbole} : historique de change incomplet."
                )

            cours_local = cours_local * taux
            nb_taux_imputes = int(masque_taux.sum())

        convertis[symbole] = cours_local

        audit_interne[symbole] = {
            "cours_imputes": int(masque_cours.sum()),
            "taux_imputes": nb_taux_imputes,
        }

    cours = pd.DataFrame(
        convertis,
        index=calendrier,
    )
    cours.index.name = "Date"

    if (
        cours.isna().any().any()
        or not np.isfinite(cours.to_numpy()).all()
        or (cours <= 0).any().any()
    ):
        raise ValueError("Données invalides après traitement.")

    poids = pd.Series(
        allocations,
        index=list(panier),
        dtype=float,
    ) / 100

    positions = (
        cours.div(cours.iloc[0])
        .mul(poids * capital)
    )

    valeur = positions.sum(axis=1)

    return {
        "cours": cours,
        "poids": poids,
        "positions": positions,
        "valeur": valeur,
        "kpi": calculer_indicateurs(valeur, rf),
        "panier": dict(panier),
        "rf": rf,
        "audit_interne": audit_interne,
    }


# ------------------------------------------------------------
# OPTIMISATION
# ------------------------------------------------------------

@st.cache_data(show_spinner=False)
def optimiser(rendements, poids_tuple, rf):
    n = len(poids_tuple)

    mu = rendements.mean().to_numpy() * 252
    covariance = rendements.cov().to_numpy() * 252
    rf_annuel = ((1 + rf) ** (1 / 252) - 1) * 252

    def volatilite(x):
        variance = float(x @ covariance @ x)
        return float(np.sqrt(max(variance, 0)))

    def oppose_sharpe(x):
        vol = volatilite(x)

        if vol <= 1e-12:
            return 1e10

        return -(
            float(x @ mu) - rf_annuel
        ) / vol

    solutions = {
        "Allocation choisie": np.array(poids_tuple)
    }
    echecs = []

    for nom, objectif in [
        ("Minimum volatilité", volatilite),
        ("Maximum Sharpe", oppose_sharpe),
    ]:
        candidats = []

        for depart in [
            np.ones(n) / n,
            np.array(poids_tuple),
            *np.eye(n),
        ]:
            resultat = minimize(
                objectif,
                depart,
                method="SLSQP",
                bounds=[(0.0, 1.0)] * n,
                constraints={
                    "type": "eq",
                    "fun": lambda x: x.sum() - 1,
                },
                options={
                    "maxiter": 1000,
                    "ftol": 1e-10,
                },
            )

            if (
                resultat.success
                and abs(resultat.x.sum() - 1) < 1e-7
                and resultat.x.min() >= -1e-8
                and resultat.x.max() <= 1 + 1e-8
            ):
                candidats.append(resultat.x)

        if candidats:
            solutions[nom] = min(
                candidats, key=objectif
            )
        else:
            echecs.append(nom)

    lignes = []

    for nom, allocation in solutions.items():
        vol = volatilite(allocation)
        rendement = float(allocation @ mu)

        lignes.append({
            "Allocation": nom,
            "Rendement annuel moyen": rendement,
            "Volatilité annuelle": vol,
            "Sharpe": (
                (rendement - rf_annuel) / vol
                if vol > 1e-12 else np.nan
            ),
        })

    generateur = np.random.default_rng(42)

    simulations = generateur.dirichlet(
        np.ones(n), size=3000
    )

    vols = np.sqrt(np.maximum(
        np.einsum(
            "ij,jk,ik->i",
            simulations,
            covariance,
            simulations,
        ),
        0,
    ))

    moyennes = simulations @ mu

    sharpes = np.divide(
        moyennes - rf_annuel,
        vols,
        out=np.full_like(vols, np.nan),
        where=vols > 1e-12,
    )

    return (
        solutions,
        pd.DataFrame(lignes),
        vols,
        moyennes,
        sharpes,
        echecs,
    )



# FORMAT DES VALEURS ET GRAPHIQUES


def montant_compact(nombre):
    for diviseur, suffixe in [
        (1e9, "Md"),
        (1e6, "M"),
        (1e3, "K"),
    ]:
        if abs(nombre) >= diviseur:
            arrondi = round(nombre / diviseur, 1)

            if abs(arrondi) >= 1000 and diviseur < 1e9:
                return montant_compact(arrondi * diviseur)

            texte = (
                f"{arrondi:.1f}"
                .rstrip("0")
                .rstrip(".")
                .replace(".", ",")
            )

            return f"{texte} {suffixe}"

    return (
        f"{nombre:,.2f}"
        .replace(",", " ")
        .replace(".", ",")
    )


def kpi(colonne, titre, valeur, format_valeur="pct"):
    if not np.isfinite(valeur):
        texte = "—"
        aide = "Indicateur non défini."

    elif format_valeur == "eur":
        texte = montant_compact(valeur) + " €"

        exacte = (
            f"{valeur:,.2f}"
            .replace(",", " ")
            .replace(".", ",")
        )

        aide = f"Valeur non abrégée : {exacte} €"

    elif format_valeur == "nombre":
        texte = f"{valeur:.2f}".replace(".", ",")
        aide = f"Valeur : {valeur:.4f}".replace(".", ",")

    else:
        texte = f"{valeur:.2%}".replace(".", ",")
        aide = f"Valeur : {valeur:.4%}".replace(".", ",")

    colonne.metric(titre, texte, help=aide)


def graphique_vide(titre):
    st.subheader(titre)

    st.markdown(
        '<div class="graphique-vide">'
        'Les résultats apparaîtront après le premier calcul.'
        '</div>',
        unsafe_allow_html=True,
    )


def graphique(figure):
    figure.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0B1930",
        plot_bgcolor="#0B1930",

        font=dict(
            color="#DCE8F8",
            family="Arial, sans-serif",
            size=12,
        ),

        title=dict(
            font=dict(
                color="#F5F8FF",
                size=19,
            )
        ),

        colorway=[
            "#62B5FF",
            "#44DFC5",
            "#B69BFF",
            "#FFD27B",
            "#FF879F",
        ],

        margin=dict(t=70, b=80, l=45, r=35),

        legend=dict(
            orientation="h",
            y=-0.22,
            x=0,
            title_text="",
            font=dict(color="#DCE8F8"),
        ),

        hoverlabel=dict(
            bgcolor="#193956",
            bordercolor="#649DE4",
            font_color="#FFFFFF",
        ),

        separators=", ",
    )

    figure.update_xaxes(
        gridcolor="rgba(175,200,235,0.10)",
        tickfont=dict(color="#C8D9EE"),
        title_font=dict(color="#E0EAF8"),
        automargin=True,
    )

    figure.update_yaxes(
        gridcolor="rgba(175,200,235,0.13)",
        tickfont=dict(color="#C8D9EE"),
        title_font=dict(color="#E0EAF8"),
        automargin=True,
    )

    titre_y = (
        figure.layout.yaxis.title.text or ""
    ).lower()

    if "euro" in titre_y or "€" in titre_y:
        figure.update_yaxes(tickformat=".3s")

        for trace in figure.data:
            if trace.type in {"scatter", "scattergl"}:
                trace.hovertemplate = (
                    "%{x|%d/%m/%Y}<br>"
                    "Valeur : %{y:,.2f} €"
                    "<extra></extra>"
                )

    st.plotly_chart(
        figure,
        use_container_width=True,
        theme=None,
    )



# PARAMÈTRES


def champs_parametres(mode):
    valeurs = S.parametres

    debut = st.date_input(
        "Date de début",
        value=valeurs["debut"],
        max_value=date.today(),
        key="date_debut",
    )

    fin = st.date_input(
        "Date de fin",
        value=valeurs["fin"],
        max_value=date.today(),
        key="date_fin",
    )

    capital = st.number_input(
        "Capital initial (€)",
        min_value=1.0,
        value=float(valeurs["capital"]),
        step=100.0,
        key="capital",
    )

    rf_pct = st.number_input(
        "Taux sans risque annuel (%)",
        min_value=0.0,
        max_value=50.0,
        value=float(valeurs["taux"]),
        step=0.25,
        key="taux",
    )

    st.subheader("💶 Poids des entreprises")

    defauts = poids_egaux(len(S.panier))
    allocations = []

    for i, (symbole, titre) in enumerate(S.panier.items()):
        if mode == "Égale":
            allocations.append(defauts[i])

            st.caption(
                f"{titre['nom']} ({symbole}) : {defauts[i]:.2f} %"
            )

        else:
            valeur_poids = S.poids_memorises.get(
                symbole, defauts[i]
            )

            allocations.append(st.number_input(
                f"{titre['nom']} ({symbole}) — %",
                min_value=0.0,
                max_value=100.0,
                value=float(valeur_poids),
                step=0.01,
                format="%.2f",
                disabled=len(S.panier) == 1,
                key=f"poids_{S.revision}_{symbole}",
            ))

    return debut, fin, capital, rf_pct, allocations



# BARRE LATÉRALE


catalogue, erreurs_catalogue = charger_catalogue()

for symbole, titre in catalogue.items():
    if symbole not in S.connues:
        S.connues[symbole] = titre

with st.sidebar:
    st.header("📁 Vos entreprises")

    disponibles = sorted(
        [
            titre
            for symbole, titre in S.connues.items()
            if symbole not in S.panier
        ],
        key=lambda titre: (
            normaliser(titre["nom"]),
            titre["symbole"],
        ),
    )

    choix = st.selectbox(
        "Entreprises — ordre alphabétique",
        options=[
            titre["symbole"]
            for titre in disponibles
        ],
        format_func=lambda symbole: etiquette(S.connues[symbole]),
        index=None,
        placeholder="Choisissez une entreprise",
        key=f"selection_{S.revision}",
        disabled=not disponibles or len(S.panier) >= 5,
    )

    if choix is not None and len(S.panier) < 5:
        try:
            with st.spinner("Vérification de l'entreprise…"):
                titre = verifier_action(choix)

            symbole = titre["symbole"]

            if symbole not in S.panier:
                S.panier[symbole] = titre
                S.connues[symbole] = titre

                changement_selection()
                st.rerun()

        except Exception as erreur:
            st.error(f"Ajout impossible : {erreur}")

    st.caption(
        "Vous pouvez écrire directement dans la liste pour filtrer "
        "les noms. Catalogue initial : marchés américains, "
        "non exhaustif mondialement."
    )

    if erreurs_catalogue:
        if not catalogue:
            st.caption("Le catalogue est momentanément indisponible.")

        if st.button("Recharger le catalogue"):
            charger_catalogue.clear()
            st.rerun()

    st.subheader(
        f"Portefeuille : {len(S.panier)}/5"
    )

    for symbole, titre in list(S.panier.items()):
        if st.button(
            f"✕ {titre['nom']} ({symbole})",
            key=f"retirer_{symbole}",
            use_container_width=True,
        ):
            del S.panier[symbole]

            changement_selection()
            st.rerun()

    st.caption(
        "Un ajout ou un retrait remet les poids à une répartition égale."
    )

    # En dehors du formulaire pour afficher immédiatement les champs
    # personnalisés lorsqu'on change de mode.
    mode = st.radio(
        "Répartition",
        ["Égale", "Personnalisée"],
        key="mode",
        horizontal=True,
    )

    st.subheader("⚙️ Paramètres")

    if not S.calcul_demarre:
        with st.form(
            "premier_calcul",
            clear_on_submit=False,
            enter_to_submit=True,
        ):
            debut, fin, capital, rf_pct, allocations = (
                champs_parametres(mode)
            )

            demander_calcul = st.form_submit_button(
                "📊 Calculer",
                type="primary",
                disabled=not S.panier,
                use_container_width=True,
            )

    else:
        debut, fin, capital, rf_pct, allocations = (
            champs_parametres(mode)
        )

        demander_calcul = st.button(
            "Actualiser / réessayer",
            disabled=not S.panier,
            use_container_width=True,
        )

        st.caption(
            "Les modifications sont appliquées après validation du champ "
            "avec Entrée ou en cliquant ailleurs."
        )



# PREMIER CALCUL MANUEL, PUIS AUTOMATIQUE


signature = (
    tuple(S.panier.keys()),
    tuple(float(v) for v in allocations),
    debut.isoformat(),
    fin.isoformat(),
    float(capital),
    float(rf_pct),
)

# Mémoriser les valeurs réellement transmises par les widgets.
S.parametres = {
    "debut": debut,
    "fin": fin,
    "capital": capital,
    "taux": rf_pct,
}

S.poids_memorises = dict(
    zip(S.panier.keys(), allocations)
)

doit_calculer = bool(S.panier) and (
    demander_calcul
    or (
        S.calcul_demarre
        and signature != S.derniere_tentative
    )
)

if doit_calculer:
    S.derniere_tentative = signature
    S.erreur = ""

    total = sum(
        Decimal(str(v)) for v in allocations
    )

    if total != Decimal("100"):
        S.analyse = None
        S.erreur = (
            f"Total des poids : {total} %. "
            "La somme doit être exactement égale à 100 %."
        )

    elif fin <= debut:
        S.analyse = None
        S.erreur = (
            "La date de fin doit être postérieure à la date de début."
        )

    else:
        try:
            deja_demarre = S.calcul_demarre

            with st.spinner("Calcul du portefeuille…"):
                resultat = analyser(
                    S.panier,
                    allocations,
                    debut,
                    fin,
                    capital,
                    rf_pct / 100,
                )

            S.analyse = resultat
            S.calcul_demarre = True

            if not deja_demarre:
                st.rerun()

        except Exception as erreur:
            S.analyse = None
            S.erreur = f"Calcul impossible : {erreur}"


# MESSAGE UNIQUE


A = S.analyse

if S.erreur:
    statut.error(S.erreur)

elif A is None:
    statut.info(
        "Sélectionnez vos entreprises et vos paramètres, puis cliquez "
        "sur Calculer ou appuyez sur Entrée dans le formulaire. "
        "Les zéros affichés sont des valeurs d'attente."
    )

else:
    statut.caption(
        f"Analyse du {A['cours'].index[0]:%d/%m/%Y} "
        f"au {A['cours'].index[-1]:%d/%m/%Y} "
        "• Actualisation automatique activée"
    )

K = A["kpi"] if A else {
    "finale": 0.0,
    "performance": 0.0,
    "cagr": 0.0,
    "volatilite": 0.0,
    "sharpe": 0.0,
    "var": 0.0,
    "drawdown": 0.0,
}

if A:
    cours = A["cours"]
    valeur = A["valeur"]
    poids = A["poids"]

    noms = {
        symbole: f"{titre['nom']} ({symbole})"
        for symbole, titre in A["panier"].items()
    }

    rendements = cours.pct_change(
        fill_method=None
    ).iloc[1:]


# ONGLETS

vue, risques, comparaison = st.tabs([
    "📊 Mon portefeuille",
    "🛡️ Risques",
    "⚖️ Comparer les allocations",
])


with vue:
    colonnes = st.columns(4)

    kpi(
        colonnes[0],
        "Valeur finale",
        K["finale"],
        "eur",
    )
    kpi(
        colonnes[1],
        "Performance totale",
        K["performance"],
    )
    kpi(
        colonnes[2],
        "Rendement annualisé",
        K["cagr"],
    )

    colonnes[3].metric(
        "Entreprises analysées",
        f"{len(A['panier']) if A else 0} / 5",
    )

    if A is None:
        graphique_vide("Évolution du portefeuille")
        graphique_vide("Comparaison des actions — Base 100")
        graphique_vide("Répartition du portefeuille")

    else:
        figure = px.line(
            x=valeur.index,
            y=valeur,
            title="Évolution du portefeuille — Buy & Hold",
            labels={
                "x": "Date",
                "y": "Valeur en euros",
            },
        )
        figure.update_traces(
            line_color="#62B5FF",
            line_width=2.5,
        )
        figure.update_layout(
            hovermode="x unified"
        )
        graphique(figure)

        base100 = (
            cours.div(cours.iloc[0])
            .mul(100)
            .rename(columns=noms)
        )

        figure = px.line(
            base100,
            title="Performance comparée en euros — Base 100",
            labels={
                "value": "Base 100",
                "variable": "Entreprise",
            },
        )
        figure.update_layout(
            hovermode="x unified"
        )
        graphique(figure)

        gauche, droite = st.columns(2)

        with gauche:
            graphique(px.pie(
                values=poids.to_numpy(),
                names=[
                    noms[symbole]
                    for symbole in poids.index
                ],
                hole=0.6,
                title="Allocation initiale",
            ))

        with droite:
            st.subheader("Évolution des poids")

            table = pd.DataFrame({
                "Poids initial": poids,
                "Poids final": (
                    A["positions"].iloc[-1]
                    / valeur.iloc[-1]
                ),
                "Valeur finale (€)": A["positions"].iloc[-1],
            }).rename(index=noms)

            st.dataframe(
                table.style.format({
                    "Poids initial": "{:.2%}",
                    "Poids final": "{:.2%}",
                    "Valeur finale (€)": "{:,.2f}",
                }),
                use_container_width=True,
            )


with risques:
    colonnes = st.columns(2)

    kpi(
        colonnes[0],
        "Volatilité annuelle",
        K["volatilite"],
    )
    kpi(
        colonnes[1],
        "Plus forte baisse historique",
        K["drawdown"],
    )

    if A is None:
        graphique_vide(
            "Baisses depuis les précédents sommets"
        )

    else:
        drawdown = (
            valeur / valeur.cummax() - 1
        )

        figure = px.area(
            x=drawdown.index,
            y=drawdown,
            title="Baisses depuis les précédents sommets",
            labels={
                "x": "Date",
                "y": "Baisse",
            },
        )
        figure.update_yaxes(
            tickformat=".0%"
        )
        figure.update_traces(
            line_color="#FF879F"
        )
        graphique(figure)

    with st.expander("Approfondir l'analyse"):
        colonnes = st.columns(2)

        kpi(
            colonnes[0],
            "Ratio de Sharpe",
            K["sharpe"],
            "nombre",
        )
        kpi(
            colonnes[1],
            "Seuil historique 5 % — 1 jour",
            K["var"],
        )

        st.caption(
            "Le seuil 5 % est une VaR historique exprimée "
            "en rendement signé, pas une perte maximale garantie."
        )

        if A is None:
            graphique_vide("Corrélations")
            graphique_vide("Distribution des rendements")

        else:
            graphique(px.imshow(
                rendements.rename(columns=noms).corr(),
                zmin=-1,
                zmax=1,
                text_auto=".2f",
                color_continuous_scale="RdBu_r",
                title="Corrélations des rendements en euros",
                aspect="auto",
            ))

            figure = px.histogram(
                x=valeur.pct_change(
                    fill_method=None
                ).iloc[1:],
                nbins=60,
                title="Distribution des rendements quotidiens",
                labels={
                    "x": "Rendement quotidien",
                },
            )
            figure.update_xaxes(
                tickformat=".1%"
            )
            figure.update_layout(
                yaxis_title="Nombre de séances"
            )
            figure.update_traces(
                marker_color="#62B5FF"
            )
            graphique(figure)


with comparaison:
    if A is None:
        graphique_vide(
            "Comparaison des allocations"
        )

    elif len(poids) == 1:
        st.caption(
            "Un seul titre : allocation de 100 %. "
            "Ajoutez un deuxième titre pour comparer les allocations."
        )

        graphique(px.bar(
            x=[noms[poids.index[0]]],
            y=[100],
            title="Allocation actuelle",
            labels={
                "x": "Entreprise",
                "y": "Poids (%)",
            },
        ))

    else:
        st.caption(
            "Modèle à poids constants estimé sur le même historique, "
            "distinct du Buy & Hold. Il ne prédit pas les performances futures."
        )

        (
            solutions,
            table,
            vols,
            moyennes,
            sharpes,
            echecs,
        ) = optimiser(
            rendements,
            tuple(poids.to_numpy()),
            A["rf"],
        )

        if echecs:
            st.caption(
                "Solutions non obtenues : "
                + ", ".join(echecs)
            )

        repartition = pd.DataFrame(
            solutions,
            index=[
                noms[symbole]
                for symbole in poids.index
            ],
        )
        repartition.index.name = "Entreprise"

        longue = repartition.reset_index().melt(
            id_vars="Entreprise",
            var_name="Allocation",
            value_name="Poids",
        )

        figure = px.bar(
            longue,
            x="Entreprise",
            y="Poids",
            color="Allocation",
            barmode="group",
            title="Comparaison des poids",
        )
        figure.update_yaxes(
            tickformat=".0%"
        )
        graphique(figure)

        st.dataframe(
            table.set_index("Allocation").style.format({
                "Rendement annuel moyen": "{:.2%}",
                "Volatilité annuelle": "{:.2%}",
                "Sharpe": "{:.2f}",
            }),
            use_container_width=True,
        )

        st.caption(
            "Rendement annuel moyen arithmétique, différent du CAGR. "
            "Poids positifs ou nuls, somme de 100 %."
        )

        with st.expander("Poids détaillés et simulations"):
            st.dataframe(
                repartition.style.format("{:.2%}"),
                use_container_width=True,
            )

            figure = go.Figure(
                go.Scattergl(
                    x=vols,
                    y=moyennes,
                    mode="markers",
                    name="Allocations simulées",
                    marker=dict(
                        color=sharpes,
                        colorscale="Viridis",
                        size=4,
                        showscale=True,
                        colorbar=dict(title="Sharpe"),
                    ),
                )
            )

            for _, ligne in table.iterrows():
                figure.add_trace(
                    go.Scatter(
                        x=[ligne["Volatilité annuelle"]],
                        y=[ligne["Rendement annuel moyen"]],
                        name=ligne["Allocation"],
                        mode="markers",
                        marker=dict(
                            size=14,
                            symbol="star",
                        ),
                    )
                )

            figure.update_layout(
                title="Simulations et solutions numériques",
                xaxis_title="Volatilité annuelle",
                yaxis_title="Rendement annuel moyen",
            )
            figure.update_xaxes(
                tickformat=".0%"
            )
            figure.update_yaxes(
                tickformat=".0%"
            )
            graphique(figure)



# EXPORTS ET MÉTHODE

with st.expander("Télécharger les résultats"):
    if A is None:
        st.caption(
            "Les exports seront disponibles après un calcul réussi."
        )

    else:
        st.download_button(
            "Cours en euros",
            A["cours"].to_csv().encode("utf-8-sig"),
            "cours_eur.csv",
            "text/csv",
        )

        export = A["positions"].add_prefix(
            "Position EUR — "
        )
        export["Portefeuille EUR"] = A["valeur"]

        st.download_button(
            "Historique du portefeuille",
            export.to_csv().encode("utf-8-sig"),
            "portefeuille.csv",
            "text/csv",
        )

        st.download_button(
            "Indicateurs",
            pd.DataFrame([A["kpi"]]).to_csv(
                index=False
            ).encode("utf-8-sig"),
            "indicateurs.csv",
            "text/csv",
        )

with st.expander("Méthode et hypothèses"):
    st.markdown("""
- Cours ajustés Yahoo selon les données du fournisseur.
- Conversion historique en euros avant les calculs.
- Simulation fractionnaire Buy & Hold, sans frais, fiscalité ni spread.
- Période commune aux titres ; séance en cours exclue.
- Alignement des calendriers au dernier cours connu, avec limites de durée.
- CAGR calculé sur la durée calendaire.
- Volatilité et Sharpe annualisés avec 252 séances.
- Optimisation historique sans validation hors échantillon.
- Catalogue initial américain ; vérification des titres auprès de Yahoo.
""")

st.caption(
    "Analyse historique uniquement. Les performances passées "
    "ne garantissent pas les performances futures. "
    "Aucun conseil d'investissement personnalisé."
)

