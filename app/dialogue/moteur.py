"""Moteur de dialogue : machine à états, indépendante du canal.

Il reçoit un Evenement et renvoie un Tour. Il ne lit ni la base ni le réseau :
les données arrivent par l'objet Services.
"""
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.dialogue import textes_fr as T

MAX_ERREURS = 3
MAX_CHIFFRES = 7
CHIFFRES = list("0123456789")


class Phrase(BaseModel):
    id: str
    texte: str
    audio: str | None = None


class Tour(BaseModel):
    etat: str
    phrases: list[Phrase]
    attente: str  # touche | voix | montant | fin
    touches_valides: list[str] = []
    delai_s: int = 6
    fin: bool = False


class Evenement(BaseModel):
    type: str  # DECROCHE | TOUCHE | VOIX | SILENCE | RACCROCHE
    valeur: str | None = None


@dataclass
class Services:
    prix: Callable[[str], list[dict]]
    # offre(produit, montant_sac_100kg, marche=None) : marche = nom FAO exact ou None.
    offre: Callable[..., dict | None]
    journal: Callable[[str, str, str], None] = lambda appel_id, etape, entree: None
    # Touche 3 : question(valeur_voix) -> dict (voir app/dialogue/question_voix.py).
    # None = pas d'IA branchée → « bientôt disponible ».
    question: Callable[[str], dict] | None = None


@dataclass
class Session:
    appel_id: str
    etat: str = "ACCUEIL"
    produit: str | None = None
    tour_courant: Tour | None = None
    repetition: list[Phrase] | None = None
    dernier_tour: Tour | None = None
    nb_erreurs: int = 0
    nb_silences: int = 0
    montant: str = ""
    avertissement_dit: bool = False
    # Touche 3 : demande comprise en attente d'une précision (couleur, sac).
    voix: dict | None = None
    marche_offre: str | None = None
    # Après le menu : "prix" ou "offre" en attente du choix produit (P00).
    apres_produit: str | None = None


class Moteur:
    def __init__(self, services: Services, voix_active: bool = False, delai_voix: int = 8):
        # Touche 3 active seulement si voix_active ET services.question est branché.
        self.services = services
        self.voix_active = voix_active
        self.delai_voix = delai_voix  # durée max d'enregistrement (= AUDIO_MAX_S)

    def nouvelle_session(self, appel_id: str) -> Session:
        return Session(appel_id=appel_id)

    # ---------- point d'entrée ----------
    def traiter(self, sess: Session, ev: Evenement) -> Tour:
        self.services.journal(sess.appel_id, sess.etat, f"{ev.type}:{ev.valeur or ''}")
        if sess.etat == "FIN" or ev.type == "RACCROCHE":
            return self._fin(sess)
        if ev.type == "DECROCHE" and sess.etat == "ACCUEIL":
            # Menu service d'abord (prix / offre / voix / réécouter) ; le produit
            # n'est demandé qu'au besoin (touche 1 ou 2 sans produit déjà choisi).
            return self._menu(sess, prefixe=[self._p("A01")])
        if ev.type == "SILENCE":
            return self._silence(sess)
        if ev.type == "TOUCHE":
            return self._touche(sess, ev.valeur or "")
        if ev.type == "VOIX" and sess.etat == "QUESTION_VOIX":
            return self._question_voix(sess, ev.valeur or "")
        return self._erreur(sess)

    @property
    def _voix_prete(self) -> bool:
        return self.voix_active and self.services.question is not None

    # ---------- touches ----------
    def _touche(self, sess, t):
        if sess.etat == "CHOIX_PRODUIT":
            if t in T.TOUCHE_PRODUIT:
                self._ok(sess)
                sess.produit = T.TOUCHE_PRODUIT[t]
                action = sess.apres_produit
                sess.apres_produit = None
                if action == "prix":
                    return self._prix(sess)
                if action == "offre":
                    sess.montant = ""
                    sess.marche_offre = None
                    return self._tour(sess, "OFFRE_MONTANT", [self._p("O01")],
                                      attente="montant", touches=CHIFFRES + ["#"])
                return self._menu(sess)
            return self._erreur(sess)

        if sess.etat == "MENU_PRINCIPAL":
            if t == "1":
                self._ok(sess)
                if not sess.produit:
                    return self._demander_produit(sess, "prix")
                return self._prix(sess)
            if t == "2":
                self._ok(sess)
                if not sess.produit:
                    return self._demander_produit(sess, "offre")
                sess.montant = ""
                sess.marche_offre = None
                return self._tour(sess, "OFFRE_MONTANT", [self._p("O01")],
                                  attente="montant", touches=CHIFFRES + ["#"])
            if t == "3":
                self._ok(sess)
                if not self._voix_prete:
                    return self._menu(sess, prefixe=[self._p("V05")])
                return self._tour(sess, "QUESTION_VOIX", [self._p("X01")],
                                  attente="voix", delai=self.delai_voix)
            if t == "4" and sess.dernier_tour is not None:
                self._ok(sess)
                rejoue = sess.dernier_tour
                sess.tour_courant = rejoue
                return rejoue
            return self._erreur(sess)

        if sess.etat == "OFFRE_MONTANT":
            return self._montant(sess, t)

        if sess.etat == "QUESTION_VOIX":
            return self._menu(sess)  # une touche pendant la question : retour au menu

        if sess.etat == "CHOIX_VARIETE":
            return self._variete(sess, t)

        if sess.etat == "CONFIRMER_SAC":
            return self._confirmer_sac(sess, t)

        if sess.etat == "CHOISIR_UNITE":
            return self._choisir_unite(sess, t)

        return self._erreur(sess)

    # ---------- touche 3 : question à voix haute ----------
    def _question_voix(self, sess, valeur):
        if not self._voix_prete:
            return self._menu(sess, prefixe=[self._p("V05")])
        try:
            res = self.services.question(valeur)
        except Exception:  # noqa: BLE001 — l'appel ne doit jamais planter
            res = {"erreur": "ia"}
        erreur = res.get("erreur")
        if erreur in ("trop_long", "vide"):
            sess.nb_erreurs += 1
            if sess.nb_erreurs >= MAX_ERREURS:
                return self._fin(sess, [self._p("N01"), self._p("F01")])
            msg = "X02" if erreur == "trop_long" else "N01"
            return self._tour(sess, "QUESTION_VOIX", [self._p(msg), self._p("X01")],
                              attente="voix", delai=self.delai_voix, repetition=[self._p("X01")])
        if erreur:
            # Transcription ou IA en panne : repli « bientôt disponible ».
            return self._menu(sess, prefixe=[self._p("V05")])

        intention = res.get("intention")
        if intention not in ("prix", "juger_offre"):
            self._ok(sess)
            return self._menu(sess, prefixe=[self._p("N01"), self._p("X03")])

        self._ok(sess)
        famille = res.get("famille") or (sess.produit or "").split(" ")[0] or None
        if famille not in T.TOUCHE_PRODUIT.values():
            return self._menu(sess, prefixe=[self._p("N01"), self._p("X03")])
        sess.voix = {
            "intention": intention,
            "famille": famille,
            "marche": res.get("marche"),
            "montant": res.get("montant"),
            "unite": res.get("unite"),
        }
        variete = res.get("variete")
        if famille in T.CHOIX_VARIETES and variete not in T.CHOIX_VARIETES[famille][1].values():
            phrase, choix = T.CHOIX_VARIETES[famille]
            return self._tour(sess, "CHOIX_VARIETE", [self._p(phrase)],
                              touches=sorted(choix))
        return self._suite_voix(sess, f"{famille} {variete}" if variete else famille)

    def _variete(self, sess, t):
        famille = (sess.voix or {}).get("famille")
        if famille not in T.CHOIX_VARIETES:
            return self._menu(sess)
        choix = T.CHOIX_VARIETES[famille][1]
        if t not in choix:
            return self._erreur(sess)
        self._ok(sess)
        return self._suite_voix(sess, f"{famille} {choix[t]}")

    def _suite_voix(self, sess, produit):
        demande = sess.voix or {}
        sess.produit = produit
        marche = demande.get("marche")
        if demande.get("intention") == "prix":
            sess.voix = None
            return self._prix(sess, marche=marche)

        sess.marche_offre = marche
        montant, unite = demande.get("montant"), demande.get("unite")
        if montant and unite == "kg":
            sess.voix = None
            return self._juger(sess, montant * 100)
        if montant and unite == "100kg":
            sess.voix = None
            return self._juger(sess, montant)
        if montant and unite == "sac":
            # Poids du sac non dit : on demande, on ne suppose pas 100 kilos.
            return self._tour(sess, "CONFIRMER_SAC",
                              [self._d(T.phrase_offre_sac(montant)), self._p("O04")],
                              touches=["1", "2"])
        if montant and unite is None:
            # Montant compris mais unité non dite : on la demande (jamais supposée).
            return self._tour(sess, "CHOISIR_UNITE",
                              [self._d(T.phrase_offre_montant(montant)), self._p("O05")],
                              touches=["1", "2", "3"])
        sess.voix = None
        sess.montant = ""
        return self._tour(sess, "OFFRE_MONTANT", [self._p("O03"), self._p("O01")],
                          attente="montant", touches=CHIFFRES + ["#"],
                          repetition=[self._p("O01")])

    def _choisir_unite(self, sess, t):
        montant = (sess.voix or {}).get("montant")
        if t in ("1", "2") and montant:
            self._ok(sess)
            sess.voix = None
            return self._juger(sess, montant * 100 if t == "1" else montant)
        if t == "3":
            self._ok(sess)
            sess.voix = None
            sess.montant = ""
            return self._tour(sess, "OFFRE_MONTANT", [self._p("O01")],
                              attente="montant", touches=CHIFFRES + ["#"])
        return self._erreur(sess)

    def _confirmer_sac(self, sess, t):
        demande = sess.voix or {}
        if t == "1" and demande.get("montant"):
            self._ok(sess)
            sess.voix = None
            return self._juger(sess, demande["montant"])
        if t == "2":
            self._ok(sess)
            sess.voix = None
            sess.montant = ""
            return self._tour(sess, "OFFRE_MONTANT", [self._p("O01")],
                              attente="montant", touches=CHIFFRES + ["#"])
        return self._erreur(sess)

    def _demander_produit(self, sess, action: str):
        """P00 après le menu : prix ou offre, dès qu'un produit est choisi."""
        sess.apres_produit = action
        return self._tour(sess, "CHOIX_PRODUIT", [self._p("P00")],
                          touches=["1", "2", "3"], repetition=[self._p("P00")])

    def _menu(self, sess, prefixe=None):
        menu = [self._p("M01"), self._p("M02"),
                self._p("M03" if self._voix_prete else "M03B"), self._p("M04")]
        tour = self._tour(sess, "MENU_PRINCIPAL", (prefixe or []) + menu,
                          touches=["1", "2", "3", "4"], repetition=menu)
        sess.dernier_tour = tour
        return tour

    def _prix(self, sess, marche=None):
        liste = self.services.prix(sess.produit)
        if not liste:
            return self._reponse(sess, [self._p("D01"), self._p("R01")])
        phrases = [self._d(T.phrase_entete_prix(sess.produit))]
        if marche is not None:
            # Touche 3 : marché précisé. Sans prix récent là-bas, on le dit
            # puis on donne les autres marchés (jamais un prix inventé).
            du_marche = [p for p in liste if p["marche"] == marche]
            if du_marche:
                liste = du_marche
            else:
                phrases.append(self._p("D02"))
        phrases += [self._d(T.phrase_marche(p)) for p in liste]
        phrases.append(self._d(T.phrase_cent_kilos(liste[0])))
        if not sess.avertissement_dit:
            phrases += [self._p("AV01"), self._p("AV02")]
            sess.avertissement_dit = True
        phrases.append(self._p("R01"))
        return self._reponse(sess, phrases)

    def _montant(self, sess, t):
        if len(t) == 1 and t.isdigit():
            if len(sess.montant) >= MAX_CHIFFRES:
                return self._montant_invalide(sess)
            self._ok(sess)
            sess.montant += t
            return self._tour(sess, "OFFRE_MONTANT", [], attente="montant",
                              touches=CHIFFRES + ["#"], repetition=[self._p("O01")])
        if t == "#":
            valeur = int(sess.montant) if sess.montant else 0
            sess.montant = ""
            if valeur <= 0:
                return self._montant_invalide(sess)
            self._ok(sess)
            return self._juger(sess, valeur)
        return self._erreur(sess)

    def _juger(self, sess, montant_sac):
        """Juge un montant pour 100 kg (touche 2 ou touche 3)."""
        if sess.marche_offre:
            offre = self.services.offre(sess.produit, montant_sac, marche=sess.marche_offre)
        else:
            offre = self.services.offre(sess.produit, montant_sac)
        sess.marche_offre = None
        if offre is None:
            return self._reponse(sess, [self._p("D01"), self._p("R01")])
        phrases = [self._d(x) for x in T.phrases_offre(offre)] + [self._p("R01")]
        return self._reponse(sess, phrases)

    def _montant_invalide(self, sess):
        sess.montant = ""
        sess.nb_erreurs += 1
        if sess.nb_erreurs >= MAX_ERREURS:
            return self._fin(sess, [self._p("O02"), self._p("F01")])
        return self._tour(sess, "OFFRE_MONTANT", [self._p("O02"), self._p("O01")],
                          attente="montant", touches=CHIFFRES + ["#"],
                          repetition=[self._p("O01")])

    # ---------- erreurs, silences, fin ----------
    def _erreur(self, sess):
        sess.nb_erreurs += 1
        if sess.nb_erreurs >= MAX_ERREURS:
            return self._fin(sess, [self._p("E01"), self._p("F01")])
        return self._repeter(sess, [self._p("E01")])

    def _silence(self, sess):
        sess.nb_silences += 1
        if sess.nb_silences >= 2:
            return self._fin(sess, [self._p("F01")])
        return self._repeter(sess, [self._p("S01")])

    def _repeter(self, sess, prefixe):
        if sess.tour_courant is None:
            return self._fin(sess)
        tour = sess.tour_courant.model_copy(
            update={"phrases": prefixe + (sess.repetition or [])})
        sess.tour_courant = tour
        return tour

    def _fin(self, sess, phrases=None):
        sess.etat = "FIN"
        return Tour(etat="FIN", phrases=phrases or [], attente="fin", fin=True)

    def _ok(self, sess):
        sess.nb_erreurs = 0
        sess.nb_silences = 0

    # ---------- outils ----------
    def _reponse(self, sess, phrases):
        tour = self._tour(sess, "MENU_PRINCIPAL", phrases, touches=["1", "2", "3", "4"],
                          repetition=[self._p("R01")])
        sess.dernier_tour = tour
        return tour

    def _tour(self, sess, etat, phrases, attente="touche", touches=None,
              delai=6, repetition=None):
        sess.etat = etat
        sess.repetition = repetition if repetition is not None else phrases
        tour = Tour(etat=etat, phrases=phrases, attente=attente,
                    touches_valides=touches or [], delai_s=delai)
        sess.tour_courant = tour
        return tour

    def _p(self, identifiant):
        return Phrase(id=identifiant, texte=T.TEXTES[identifiant],
                      audio=f"/audio/{identifiant}.wav")

    def _d(self, texte):
        return Phrase(id="DYN", texte=texte)
