/* Simulateur web : faux téléphone branché sur /api/sim (contrat 5.1).
   JavaScript sans framework ni CDN. Le texte vient toujours du serveur :
   la page n'invente aucune phrase du service. */
"use strict";

const API = "/api/sim";
const $ = (id) => document.getElementById(id);

const etat = {
  appelId: null,
  tour: null,
  son: true,
  jeton: 0,            // change à chaque nouvelle lecture : annule l'ancienne
  audioCourant: null,
  ctx: null,           // AudioContext (sonnerie, bip)
  sonnerie: null,
  rappel: null,
  enregistreur: null,
  flux: null,
  morceaux: [],
  finEnregistrement: null,
  compteurs: { clip: 0, navigateur: 0 },
};

/* ---------- affichage ---------- */
function montrer(vue) {
  for (const v of ["vue-bip", "vue-sonnerie", "vue-appel"]) $(v).classList.toggle("cache", v !== vue);
  $("commandes").classList.remove("cache");
  const tel = document.querySelector(".telephone");
  if (tel) tel.dataset.vue = vue;
  majSoftkeys(vue);
}

function majSoftkeys(vue) {
  const gauche = $("label-gauche");
  const droite = $("label-droite");
  const vert = $("decrocher");
  if (vue === "vue-bip") {
    gauche.textContent = "Biper";
    droite.textContent = "Effacer";
    vert.disabled = false;
  } else if (vue === "vue-sonnerie") {
    gauche.textContent = vert.disabled ? "" : "Décrocher";
    droite.textContent = "Refuser";
  } else if (vue === "vue-appel") {
    const voix = etat.tour && etat.tour.attente === "voix";
    gauche.textContent = voix ? (etat.enregistreur ? "Envoyer" : "Parler") : "";
    droite.textContent = "Raccro.";
    vert.disabled = !voix;
  }
}

function vueCourante() {
  const tel = document.querySelector(".telephone");
  return (tel && tel.dataset.vue) || "vue-bip";
}

function afficherNumero() {
  $("affichage-numero").textContent = $("numero").value;
}
function statut(texte) { $("statut").textContent = texte; }
function erreur(message) {
  const e = $("erreur");
  e.textContent = message || "";
  e.classList.toggle("cache", !message);
}
function bulle(classe, html) {
  const li = document.createElement("li");
  li.className = classe;
  li.innerHTML = html;
  $("fil").appendChild(li);
  $("fil").scrollTop = $("fil").scrollHeight;
  return li;
}
function echapper(t) {
  return String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/* ---------- appels au serveur ---------- */
async function appeler(chemin, options = {}) {
  let r;
  try {
    r = await fetch(API + chemin, { method: "POST", ...options });
  } catch {
    throw new Error("Le serveur ne répond pas. Vérifiez que « uvicorn app.main:app » tourne.");
  }
  let corps = null;
  try { corps = await r.json(); } catch { /* corps vide */ }
  if (!r.ok) {
    let detail = corps && corps.detail;
    if (Array.isArray(detail)) detail = "Donnée refusée : " + detail.map((d) => d.msg).join(", ");
    const err = new Error(detail || `Erreur du serveur (${r.status}).`);
    err.status = r.status;
    throw err;
  }
  return corps;
}
function json(corps) {
  return { headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) };
}

/* ---------- sons : sonnerie et bip (synthétisés, aucun fichier) ---------- */
function contexteAudio() {
  if (!etat.ctx) {
    const C = window.AudioContext || window.webkitAudioContext;
    if (C) etat.ctx = new C();
  }
  if (etat.ctx && etat.ctx.state === "suspended") etat.ctx.resume();
  return etat.ctx;
}
function ton(freq, debut, duree, volume = 0.15) {
  const ctx = contexteAudio();
  if (!ctx || !etat.son) return;
  const o = ctx.createOscillator();
  const g = ctx.createGain();
  o.frequency.value = freq;
  g.gain.value = volume;
  o.connect(g).connect(ctx.destination);
  o.start(ctx.currentTime + debut);
  o.stop(ctx.currentTime + debut + duree);
}
function demarrerSonnerie() {
  arreterSonnerie();
  const sonner = () => { ton(440, 0, 0.4); ton(480, 0, 0.4); ton(440, 0.6, 0.4); ton(480, 0.6, 0.4); };
  sonner();
  etat.sonnerie = setInterval(sonner, 2500);
}
function arreterSonnerie() { clearInterval(etat.sonnerie); etat.sonnerie = null; }
function bip() { ton(1000, 0, 0.25, 0.2); return attendre(300); }
const attendre = (ms) => new Promise((ok) => setTimeout(ok, ms));

/* ---------- lecture des phrases : clip si dispo, sinon voix du navigateur ---------- */
let voixFr = null;
function choisirVoixFr() {
  if (!("speechSynthesis" in window)) return;
  const voix = speechSynthesis.getVoices();
  voixFr = voix.find((v) => v.lang === "fr-FR") || voix.find((v) => v.lang && v.lang.startsWith("fr")) || null;
}
if ("speechSynthesis" in window) {
  choisirVoixFr();
  speechSynthesis.onvoiceschanged = choisirVoixFr;
}

function arreterLecture() {
  etat.jeton++;
  if (etat.audioCourant) { etat.audioCourant.pause(); etat.audioCourant = null; }
  if ("speechSynthesis" in window) speechSynthesis.cancel();
  document.querySelectorAll(".fil .en-cours").forEach((e) => e.classList.remove("en-cours"));
}

function jouerClip(url) {
  return new Promise((ok, ko) => {
    const a = new Audio(url);
    etat.audioCourant = a;
    etat.finClip = ok; // permet de passer à la suite si on coupe le son
    a.onended = () => ok();
    a.onerror = () => ko(new Error("clip illisible"));
    a.play().catch(ko);
  });
}
function lireTexte(texte) {
  return new Promise((ok) => {
    if (!("speechSynthesis" in window)) return ok();
    const u = new SpeechSynthesisUtterance(texte);
    u.lang = "fr-FR";
    if (voixFr) u.voice = voixFr;
    u.rate = 0.95;
    const secours = setTimeout(ok, 2500 + texte.length * 90); // si onend ne vient jamais
    u.onend = u.onerror = () => { clearTimeout(secours); ok(); };
    speechSynthesis.speak(u);
  });
}

async function direPhrases(phrases, elements) {
  arreterLecture();
  const jeton = etat.jeton;
  for (let i = 0; i < phrases.length; i++) {
    if (jeton !== etat.jeton) return false;
    const p = phrases[i];
    const el = elements[i];
    el.classList.add("en-cours");
    if (etat.son) {
      let lu = false;
      if (p.audio) {
        try { await jouerClip(p.audio); lu = true; } catch { el.querySelector(".source").textContent = "clip absent · lu par le navigateur"; }
      }
      if (!lu && jeton === etat.jeton) await lireTexte(p.texte);
    } else {
      await attendre(400);
    }
    el.classList.remove("en-cours");
  }
  return jeton === etat.jeton;
}

/* ---------- un tour du moteur ---------- */
const NOMS_ATTENTE = {
  touche: "une touche",
  montant: "un montant en chiffres, puis # pour valider",
  voix: "votre question à voix haute",
  fin: "rien : l'appel est terminé",
};

async function afficherTour(tour) {
  etat.tour = tour;
  const elements = tour.phrases.map((p) => {
    const source = p.audio_source === "clip" || (p.audio && !p.audio_source) ? "clip enregistré" : "lu par le navigateur";
    etat.compteurs[p.audio ? "clip" : "navigateur"]++;
    return bulle("service", `<span class="code">${echapper(p.id)}</span>${echapper(p.texte)}<span class="source">${source}</span>`);
  });
  majInfoVoix();
  majAttente(tour, true);
  const fini = await direPhrases(tour.phrases, elements);
  if (!fini) return;
  if (tour.fin) return finAppel("Le service a raccroché.");
  majAttente(tour, false);
  if (tour.attente === "voix") {
    await bip();
    statut("À vous de parler");
  }
}

function majAttente(tour, pendantLecture) {
  const touches = tour.touches_valides || [];
  document.querySelectorAll("#clavier button").forEach((b) => b.classList.toggle("valide", touches.includes(b.dataset.touche)));
  let html = `Le service attend : <b>${echapper(NOMS_ATTENTE[tour.attente] || tour.attente)}</b>`;
  if (tour.attente === "touche" && touches.length) html += ` (${touches.map(echapper).join(", ")})`;
  if (tour.attente === "voix") html += ` · ${tour.delai_s} s au plus · bouton vert pour parler`;
  if (pendantLecture && tour.phrases.length) html += "<br><small>Vous pouvez taper sans attendre la fin.</small>";
  $("attente").innerHTML = html;
  $("micro").disabled = tour.attente !== "voix" || !micPossible();
  statut(tour.fin ? "Fin de l'appel" : pendantLecture ? "Le service parle…" : "En communication");
  majSoftkeys("vue-appel");
}

function majInfoVoix() {
  const { clip, navigateur } = etat.compteurs;
  let t = `Dans cet appel : ${clip} phrase(s) jouée(s) avec un clip enregistré, ${navigateur} lue(s) par la voix du navigateur.`;
  if (!("speechSynthesis" in window)) t += " Ce navigateur ne sait pas lire le texte : seuls les clips sont audibles.";
  $("info-voix").textContent = t;
}

/* ---------- déroulé de l'appel ---------- */
async function biper() {
  erreur("");
  contexteAudio();
  if ("speechSynthesis" in window) speechSynthesis.getVoices();
  const numero = $("numero").value.replace(/\s+/g, "");
  if (!/^\+\d{8,15}$/.test(numero)) return erreur("Numéro invalide : tapez +229 puis 8 à 10 chiffres.");
  $("decrocher").disabled = true;
  try {
    const r = await appeler("/bip", json({ numero }));
    etat.appelId = r.appel_id;
    attendreRappel(r.rappel_dans_s ?? 5);
  } catch (e) {
    $("decrocher").disabled = false;
    erreur(e.status === 429 ? "Trop de bips pour ce numéro. Réessayez plus tard." : e.message);
  }
}

function attendreRappel(secondes) {
  montrer("vue-sonnerie");
  $("decrocher").disabled = true;
  const icone = document.querySelector(".icone-appel");
  if (icone) icone.classList.add("attente");
  let reste = secondes;
  const maj = () => {
    $("texte-sonnerie").textContent = `Bip reçu. Rappel dans ${reste} s…`;
    statut("Bip envoyé");
    majSoftkeys("vue-sonnerie");
  };
  maj();
  etat.rappel = setInterval(() => {
    reste--;
    if (reste > 0) return maj();
    clearInterval(etat.rappel);
    $("texte-sonnerie").textContent = "Appel entrant…";
    statut("Ça sonne");
    if (icone) icone.classList.remove("attente");
    $("decrocher").disabled = false;
    majSoftkeys("vue-sonnerie");
    demarrerSonnerie();
  }, 1000);
}

async function decrocher() {
  arreterSonnerie();
  $("fil").innerHTML = "";
  $("compris").classList.add("cache");
  etat.compteurs = { clip: 0, navigateur: 0 };
  montrer("vue-appel");
  try {
    await afficherTour(await appeler(`/appels/${etat.appelId}/decroche`));
  } catch (e) { echec(e); }
}

let dernierMontant = null;

function beepTouche(t) {
  ton(697 + Number(t === "#" ? 12 : t === "*" ? 10 : t) * 20, 0, 0.12, 0.08);
}

function composer(t) {
  const champ = $("numero");
  let v = champ.value;
  if (t === "*") {
    if (v.length > 4) champ.value = v.slice(0, -1);
  } else if (/^[0-9]$/.test(t)) {
    if (v.length < 16) champ.value = v + t;
  }
  afficherNumero();
  erreur("");
}

async function toucher(t) {
  const vue = vueCourante();
  beepTouche(t);
  if (vue === "vue-bip") {
    if (t === "*") return composer("*");
    if (/^[0-9]$/.test(t)) return composer(t);
    return;
  }
  if (vue !== "vue-appel") return;
  if (!etat.appelId || !etat.tour || etat.tour.fin) return;
  if (etat.enregistreur) return erreur("Arrêtez d'abord l'enregistrement (bouton vert).");
  erreur("");
  arreterLecture();
  if (etat.tour.attente === "montant" && dernierMontant) {
    dernierMontant.querySelector(".valeur").textContent += t;
  } else {
    const li = bulle("paysan", `⌨ <span class="valeur">${echapper(t)}</span>`);
    dernierMontant = etat.tour.attente === "montant" ? li : null;
  }
  try {
    const tour = await appeler(`/appels/${etat.appelId}/touche`, json({ touche: t }));
    if (tour.attente !== "montant" || tour.phrases.length) dernierMontant = null;
    await afficherTour(tour);
  } catch (e) { echec(e); }
}

function actionVerte() {
  const vue = vueCourante();
  if (vue === "vue-bip") return biper();
  if (vue === "vue-sonnerie" && !$("decrocher").disabled) return decrocher();
  if (vue === "vue-appel" && etat.tour && etat.tour.attente === "voix") return basculerMicro();
}

function actionRouge() {
  const vue = vueCourante();
  if (vue === "vue-bip") return composer("*");
  if (vue === "vue-sonnerie" || vue === "vue-appel") return raccrocher();
}

async function raccrocher() {
  const id = etat.appelId;
  finAppel("Vous avez raccroché.");
  if (id) { try { await appeler(`/appels/${id}/raccroche`); } catch { /* déjà fermé */ } }
}

function finAppel(message) {
  arreterSonnerie();
  clearInterval(etat.rappel);
  arreterLecture();
  arreterEnregistrement(true);
  const id = etat.appelId;
  etat.appelId = null;
  etat.tour = null;
  dernierMontant = null;
  if (id && message !== "Vous avez raccroché.") appeler(`/appels/${id}/raccroche`).catch(() => {});
  statut("Appel terminé");
  $("attente").textContent = message;
  document.querySelectorAll("#clavier button").forEach((b) => b.classList.remove("valide"));
  $("micro").disabled = true;
  montrer("vue-bip");
  statut("Prêt");
  $("minuteur").textContent = "";
}

function echec(e) {
  if (e.status === 404) {
    erreur("Cet appel n'existe plus (serveur redémarré ou appel trop ancien). Bipez à nouveau.");
    return finAppel("Appel perdu.");
  }
  erreur(e.message);
}

/* ---------- micro : question à voix haute (touche 3) ---------- */
function micPossible() {
  return window.isSecureContext && !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && "MediaRecorder" in window;
}
function typeAudio() {
  for (const t of ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"]) {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(t)) return t;
  }
  return "";
}

async function basculerMicro() {
  if (etat.enregistreur) return arreterEnregistrement(false);
  if (!micPossible()) return erreur("Micro indisponible : ouvrez la page sur http://localhost:8000 ou en https, avec un navigateur récent.");
  erreur("");
  arreterLecture();
  try {
    etat.flux = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return erreur("Accès au micro refusé. Autorisez le micro pour cette page, puis réessayez.");
  }
  const type = typeAudio();
  const rec = new MediaRecorder(etat.flux, type ? { mimeType: type } : undefined);
  etat.enregistreur = rec;
  etat.morceaux = [];
  rec.ondataavailable = (ev) => { if (ev.data.size) etat.morceaux.push(ev.data); };
  rec.onstop = () => envoyerVoix(rec.mimeType || type || "audio/webm");
  rec.start();
  // Limite côté navigateur : un peu sous AUDIO_MAX_S pour ne pas être refusé.
  const max = Math.max(2, (etat.tour?.delai_s || 12) - 0.5);
  const debut = Date.now();
  $("micro").classList.add("enregistre");
  $("decrocher").classList.add("enregistre");
  statut("Enregistrement…");
  majSoftkeys("vue-appel");
  etat.finEnregistrement = setInterval(() => {
    const ecoule = (Date.now() - debut) / 1000;
    $("minuteur").textContent = `🎙 ${ecoule.toFixed(0)} / ${Math.round(max)} s`;
    if (ecoule >= max) arreterEnregistrement(false);
  }, 200);
}

function arreterEnregistrement(annuler) {
  clearInterval(etat.finEnregistrement);
  $("minuteur").textContent = "";
  $("micro").classList.remove("enregistre");
  $("decrocher").classList.remove("enregistre");
  majSoftkeys("vue-appel");
  const rec = etat.enregistreur;
  etat.enregistreur = null;
  if (rec) {
    if (annuler) rec.onstop = null;
    if (rec.state !== "inactive") rec.stop();
  }
  if (etat.flux) { etat.flux.getTracks().forEach((t) => t.stop()); etat.flux = null; }
}

async function envoyerVoix(mime) {
  if (!etat.appelId) return;
  const blob = new Blob(etat.morceaux, { type: mime });
  const ext = mime.includes("mp4") ? "m4a" : mime.includes("ogg") ? "ogg" : "webm";
  const li = bulle("paysan", "🎤 <i>Transcription en cours…</i>");
  $("micro").disabled = true;
  statut("Le service réfléchit…");
  const form = new FormData();
  form.append("fichier", blob, `question.${ext}`);
  try {
    const r = await appeler(`/appels/${etat.appelId}/voix`, { body: form });
    li.innerHTML = r.transcription ? `🎤 « ${echapper(r.transcription)} »` : "🎤 <i>(rien de compris)</i>";
    if (r.erreur === "audio_trop_long") erreur(`Question trop longue : ${etat.tour?.delai_s || 12} secondes au plus.`);
    else if (r.erreur === "transcription_indisponible") erreur("Transcription impossible : vérifiez internet et la clé Groq dans le .env (ou le Whisper local).");
    afficherCompris(r);
    await afficherTour(r);
  } catch (e) {
    li.innerHTML = "🎤 <i>non envoyé</i>";
    echec(e);
  }
}

const NOMS_INTENTION = { prix: "demande de prix", juger_offre: "offre d'un acheteur", hors_sujet: "hors sujet", inconnu: "pas comprise" };
function afficherCompris(r) {
  const box = $("compris");
  if (!r.intention && !r.compris) return box.classList.add("cache");
  const c = r.compris || {};
  const morceaux = [`Intention : <b>${echapper(NOMS_INTENTION[r.intention] || r.intention)}</b>`];
  if (c.famille) morceaux.push(`produit : ${echapper([c.famille, c.variete].filter(Boolean).join(" "))}`);
  if (c.marche) morceaux.push(`marché : ${echapper(c.marche)}`);
  if (c.montant) morceaux.push(`montant : ${echapper(c.montant)} F${c.unite ? " / " + echapper(c.unite) : ""}`);
  box.innerHTML = "Ce que le service a compris : " + morceaux.join(" · ");
  box.classList.remove("cache");
}

/* ---------- branchements : uniquement les touches du Nokia ---------- */
$("biper").onclick = biper;
$("decrocher").onclick = actionVerte;
$("soft-gauche").onclick = actionVerte;
$("nav-rond").onclick = actionVerte;
$("refuser").onclick = raccrocher;
$("raccrocher").onclick = actionRouge;
$("soft-droite").onclick = actionRouge;
$("micro").onclick = basculerMicro;
document.querySelectorAll("#clavier button").forEach((b) => { b.onclick = () => toucher(b.dataset.touche); });
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "INPUT") return;
  if (/^[0-9*#]$/.test(e.key)) toucher(e.key);
  if (e.key === "Enter") actionVerte();
  if (e.key === "Backspace" || e.key === "Escape") actionRouge();
});
$("son").onclick = () => {
  etat.son = !etat.son;
  $("son").setAttribute("aria-pressed", String(etat.son));
  $("son").textContent = etat.son ? "🔊 Son activé" : "🔇 Son coupé";
  if (!etat.son) {
    if (etat.audioCourant) { etat.audioCourant.pause(); etat.audioCourant = null; }
    if (etat.finClip) etat.finClip();
    if ("speechSynthesis" in window) speechSynthesis.cancel();
  }
};
if (!micPossible()) {
  $("info-voix").insertAdjacentHTML("afterend", '<p class="petit">⚠ Micro indisponible ici : utilisez http://localhost:8000/simulateur/ ou https.</p>');
}
afficherNumero();
montrer("vue-bip");
