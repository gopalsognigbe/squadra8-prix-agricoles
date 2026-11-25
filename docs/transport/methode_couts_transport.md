# Coûts de transport commune → marché : méthode et estimations

**Statut : ESTIMATIONS NON VÉRIFIÉES (25/11/2026).** Aucun chiffre ci-dessous n'est un tarif relevé auprès d'un transporteur du Zou.
Un membre de l'équipe doit les vérifier (appel à 2 ou 3 transporteurs / zémidjans / paysans par commune), puis les corriger et passer leur statut à « vérifié » dans le dashboard (`/admin/`, carte « Coûts de transport »).

## 1. Ce qu'on cherche
Le coût pour transporter **un sac de 100 kg** depuis le chef-lieu de la commune du paysan jusqu'à chacun des 3 marchés suivis : Bohicon, Houndjro (Abomey), Azogotchébou (Covè). Le service le convertit au kilo (coût ÷ 100), le retire du prix de détail (net = prix de détail − transport) et juge l'offre sur ce net, avec les mêmes seuils ±5 % que `juger_offre`.

## 2. Les 9 communes du Zou (touches 1 à 9)
Abomey, Agbangnizoun, Bohicon, Covè, Djidja, Ouinhi, Zagnanado, Za-Kpota, Zogbodomey (touche 0 = autre commune, pas de transport annoncé).
Sources : INSAE, *Cahier des villages et quartiers de ville du Zou* (RGPH-4, 2016) — https://instad.bj/images/docs/insae-statistiques/enquetes-recensements/RGPH/1.RGPH_4/resultats%20finaux/Cahiers%20villages/Cahier%20des%20villages%20et%20quartiers%20de%20ville%20du%20zou.pdf ; Ministère du Développement, monographie Zou-Collines — https://www.developpement.gouv.bj/media/Spat_bj_Monographie%20Zou-Collines-03-02.pdf

## 3. Distances
- Point de départ = coordonnées du chef-lieu de chaque commune (Wikipédia FR, API `prop=coordinates`).
- Marchés : Bohicon = centre de Bohicon (Wikipédia) ; Houndjro = « Marché Houndjro, Abomey » (OpenStreetMap/Nominatim : 7.18077, 1.99171) ; Azogotchébou = « Marché central de Covè » (OpenStreetMap/Nominatim : 7.21911, 2.34019) — *hypothèse : Nominatim ne trouve pas « Azogotchébou » ; on a pris le marché central de Covè. À confirmer.*
- Distance = itinéraire routier en voiture calculé par OSRM sur les données OpenStreetMap (https://router.project-osrm.org, profil `driving`), le 25/11/2026. Ce n'est pas la piste réelle depuis un village : un paysan d'un village éloigné du chef-lieu paiera plus.
- Données brutes : `distances_osrm.json` (livré avec ce document).

## 4. Sources sur les tarifs (aucune ne donne un tarif Zou par sac et par km)
1. **Burkina Faso, transport des marchandises vers un marché rural** (HAL, hal-03836199) : « Le prix du transport par sac varie entre 300 et 1 000 FCFA », selon la distance, le poids et le prix de l'essence. https://hal.science/hal-03836199/document
2. **Marges du maïs au Sud-Bénin** (GSJ 2018, HAL hal-01860891) : les détaillants paient en moyenne **100 FCFA/sac** de transport (trajets courts) ; coûts de transaction des grossistes ≈ 1 479 FCFA/sac (transport + taxes + stockage…). https://hal.science/hal-01860891/file/ETUDE-DES-MARGES-DANS-LES-CIRCUITS-DE-COMMERCIALISATION-DE-CEREALES-AU-SUD-BENIN-CAS-DU-MAIS.pdf
3. **Fafchamps, Gabre-Madhin & Minten (2005)**, enquête de 641 commerçants au Bénin (1999) : transport motorisé ≈ **0,28 $ par tonne-km** (≈ 0,028 $ par sac de 100 kg et par km en 1999 ; à réactualiser : carburant et inflation). http://web.stanford.edu/~fafchamp/incret.pdf
4. **Kandi (Bénin), Heliyon 2024** : les intermédiaires transportent 2 à 6 sacs de maïs par moto ou tricycle. https://pmc.ncbi.nlm.nih.gov/articles/PMC10958714/
5. **Zémidjan** : pas de tarif affiché, prix négocié ; 100 à 1 000 FCFA pour un petit trajet de personne (lepetitjournal, 2024) — https://lepetitjournal.com/cotonou/zem-les-taxis-moto-du-benin-299763 ; bonnearrivee.bj — https://www.bonnearrivee.bj/sejourner/toutes-les-infos-pratiques/se-deplacer

**Ce qui manque** : aucun tarif publié pour un sac de 100 kg sur les axes du Zou (ex. Zagnanado → Bohicon). D'où la formule ci-dessous et la vérification obligatoire.

## 5. Formule (hypothèse de travail, calée sur les sources 1 à 3)
- **Estimation** = 200 F (chargement, déchargement, petit trajet local) + **15 F par km** et par sac, arrondie aux 50 F.
- **Fourchette prudente** : bas = 100 F + 8 F/km ; haut = 300 F + 25 F/km (arrondis aux 50 F).
- Même commune que le marché (distance < 2 km) : 200 F (coût local estimé).
- Mode supposé : ≤ 20 km → moto ou tricycle ; > 20 km → taxi-brousse ou camion, payé au sac.
- Contrôle : 40 km → 800 F (fourchette 450–1 300 F), dans la plage 300–1 000 F/sac de la source 1 ; trajet court en ville → 200 F, proche des 100 F/sac de la source 2.

## 6. Tableau des estimations (fichier : `data/transport/couts_transport.csv`)
| Commune de départ | Marché | Distance route (km) | Estimation (F / sac 100 kg) | Soit F / kg | Fourchette prudente (F / sac) | Mode supposé | Statut |
|---|---|---|---|---|---|---|---|
| Abomey | Bohicon | 15.3 | 450 | 4 | 200 – 700 | moto ou tricycle | estimé (non vérifié) |
| Abomey | Houndjro (Abomey) | 0.8 | 200 | 2 | 100 – 300 | local (même commune) | estimé (non vérifié) |
| Abomey | Azogotchébou (Covè) | 44.3 | 850 | 8 | 450 – 1400 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Agbangnizoun | Bohicon | 23.2 | 550 | 6 | 300 – 900 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Agbangnizoun | Houndjro (Abomey) | 13.3 | 400 | 4 | 200 – 650 | moto ou tricycle | estimé (non vérifié) |
| Agbangnizoun | Azogotchébou (Covè) | 52.2 | 1000 | 10 | 500 – 1600 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Bohicon | Bohicon | 0.0 | 200 | 2 | 100 – 300 | local (même commune) | estimé (non vérifié) |
| Bohicon | Houndjro (Abomey) | 12.9 | 400 | 4 | 200 – 600 | moto ou tricycle | estimé (non vérifié) |
| Bohicon | Azogotchébou (Covè) | 34.8 | 700 | 7 | 400 – 1150 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Covè | Bohicon | 35.1 | 750 | 8 | 400 – 1200 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Covè | Houndjro (Abomey) | 43.9 | 850 | 8 | 450 – 1400 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Covè | Azogotchébou (Covè) | 0.5 | 200 | 2 | 100 – 300 | local (même commune) | estimé (non vérifié) |
| Djidja | Bohicon | 25.1 | 600 | 6 | 300 – 950 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Djidja | Houndjro (Abomey) | 23.2 | 550 | 6 | 300 – 900 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Djidja | Azogotchébou (Covè) | 59.6 | 1100 | 11 | 600 – 1800 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Ouinhi | Bohicon | 74.9 | 1300 | 13 | 700 – 2150 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Ouinhi | Houndjro (Abomey) | 83.7 | 1450 | 14 | 750 – 2400 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Ouinhi | Azogotchébou (Covè) | 40.2 | 800 | 8 | 400 – 1300 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Zagnanado | Bohicon | 40.8 | 800 | 8 | 450 – 1300 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Zagnanado | Houndjro (Abomey) | 49.6 | 950 | 10 | 500 – 1550 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Zagnanado | Azogotchébou (Covè) | 5.5 | 300 | 3 | 150 – 450 | moto ou tricycle | estimé (non vérifié) |
| Za-Kpota | Bohicon | 21.1 | 500 | 5 | 250 – 850 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Za-Kpota | Houndjro (Abomey) | 30.0 | 650 | 6 | 350 – 1050 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Za-Kpota | Azogotchébou (Covè) | 16.7 | 450 | 4 | 250 – 700 | moto ou tricycle | estimé (non vérifié) |
| Zogbodomey | Bohicon | 12.4 | 400 | 4 | 200 – 600 | moto ou tricycle | estimé (non vérifié) |
| Zogbodomey | Houndjro (Abomey) | 21.2 | 500 | 5 | 250 – 850 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |
| Zogbodomey | Azogotchébou (Covè) | 41.4 | 800 | 8 | 450 – 1350 | taxi-brousse ou camion, payé au sac | estimé (non vérifié) |

## 7. Comment vérifier (pour le membre de l'équipe)
1. Pour chaque ligne, demander le prix réel d'un sac de 100 kg à 2 ou 3 transporteurs (zémidjan, tricycle, taxi-brousse) ou paysans ; noter la date.
2. Ouvrir `http://127.0.0.1:8000/admin/`, se connecter, carte « Coûts de transport ».
3. Corriger le coût, le mode, passer le statut à « vérifié », cliquer sur « Enregistrer ». Le fichier CSV est réécrit, la modification est inscrite dans le journal (qui, quand). Le service l'utilise au prochain appel (pas besoin de redémarrer).
4. Statut « vérifié » : le service ne dit plus « c'est une estimation ».
