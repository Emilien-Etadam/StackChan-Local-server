# StackChan Local Server

Serveur vocal local, en français, pour le robot M5Stack **StackChan** sous firmware
[ciniml/stackchan-idf](https://github.com/ciniml/stackchan-idf) (mode XiaoZhi).
Aucun service cloud : transcription, LLM et voix tournent sur le réseau local.

```
StackChan ──WebSocket──▶ xiaozhi-server (LXC)  ──▶ voix-fr : transcription Parakeet   (R750xa, CPU)
  (micro, haut-parleur)        │                 ──▶ llama-swap : LLM alias « chat » (R750xa, GPU)
                               └─────────────────▶ voix-fr : voix Pocket TTS + effet robot (R750xa, CPU)
```

| Dossier | Rôle | Où l'installer |
|---|---|---|
| `voix-fr/` | Service vocal : Parakeet TDT 0.6B v3 (transcription), Kyutai Pocket TTS « estelle » (voix), effet « petit robot », nombres et dates en toutes lettres, page de réglage `/test` | R750xa, utilisateur `et` |
| `xiaozhi/` | [xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server) figé sur une version testée, avec 6 correctifs (le 5 tient aussi compte de la voix reconnue) pour le français et un LLM local | LXC Debian 13 dédié, en root |
| `bench/` | Scripts de mesure utilisés pour choisir les modèles (vitesse CPU, écoute des voix et des effets) | R750xa |

## Installation

Une seule fois, sur chaque machine (`apt-get install -y git` si besoin) :

```bash
git clone https://github.com/Emilien-Etadam/StackChan-Local-server.git
```

**R750xa, shell de l'hôte, utilisateur `et`** :

```bash
cd StackChan-Local-server && git pull && bash voix-fr/install.sh
```

Puis page d'essai et de réglage : `http://192.168.30.121:8200/test`

**Console du LXC xiaozhi (pas l'hyperviseur Proxmox), en root** :

```bash
cd StackChan-Local-server && git pull && bash xiaozhi/install.sh
```

Le script demande la clé API de llama-swap au premier passage, puis affiche l'URL à saisir
dans le robot (onglet Conversation, fournisseur XiaoZhi).

Les deux scripts sont **rejouables** : `git pull` puis la même commande pour mettre à jour.
Ils ne touchent jamais aux configurations existantes :

- `/etc/voix-fr/voix.yaml` (R750xa) : voix, effet robot, nombre de cœurs ;
- `/opt/xiaozhi/main/xiaozhi-server/data/.config.yaml` (LXC) : prompt, adresses, clé API.

## Changer le nom du robot

Le robot ne répond qu'aux phrases contenant son nom. Pour le changer (console du LXC
xiaozhi, en root) :

```bash
cd StackChan-Local-server && git pull && bash xiaozhi/changer-nom.sh Hector
```

Choisir un nom que la transcription écrit toujours pareil : « Stack-chan » sort en
« Tak Shane », « Stack Shine »... alors que « Hector » est transcrit sans faute.

## Ne répondre qu'à ma voix

voix-fr calcule une empreinte vocale de chaque phrase reçue (modèle WeSpeaker, CPU).
1. Console du LXC xiaozhi, en root : `bash xiaozhi/activer-voix.sh Emilien`
2. Parler au robot, puis sur `http://192.168.30.121:8200/test`, section « Ma voix » :
   cliquer « C'est moi » sur 3 à 5 phrases. Tant qu'aucune voix n'est inscrite, tout le
   monde passe.
3. Retour en arrière : `bash xiaozhi/activer-voix.sh --off`

## Recherche internet

Le robot cherche sur le SearXNG local (format json activé) : `bash xiaozhi/activer-recherche.sh`
dans la console du LXC xiaozhi (port détecté sur 192.168.30.122 ; `--off` pour retirer).

## Regard, mémoire, agenda et mails

Ajoutés automatiquement à la config par `xiaozhi/install.sh` (rien d'existant n'est modifié) :

- **Regard** (bloc `regard`) : à chaque phrase acceptée, xiaozhi prend une photo par la
  caméra du robot, cherche ton visage (OpenCV YuNet) et tourne la tête vers toi.
  Tête du mauvais côté : `sens_yaw: -1` (ou `sens_pitch: -1`).
- **Mémoire** : « retiens que... » est gardé par voix-fr. Page :
  `http://192.168.30.121:8200/memoire` (voir, corriger, supprimer).
- **Agenda et mails Zimbra** (bloc `plugins.zimbra`, à remplir sur le LXC) : lire
  l'agenda, ajouter un rendez-vous (CalDAV), lire les mails sans les marquer lus, préparer
  une réponse dans **Brouillons**. Aucun envoi : le module ne contient pas de code d'envoi.

## Règle de modification

- **Configs et prompt** : modifier les fichiers ci-dessus directement, ils sont conservés.
- **Code de xiaozhi** : uniquement via `xiaozhi/correctifs.py`. Le script remet le code à la
  version figée avant d'appliquer les correctifs ; toute modification faite à la main dans
  `/opt/xiaozhi` est effacée au passage suivant.

## Correctifs appliqués à xiaozhi (`xiaozhi/correctifs.py`)

1. Coupure des phrases sur `.` `:` `…` sans couper les nombres (3.5, 3,5, 15:30).
2. Réglage `extra_body` pour le LLM (sert à couper la réflexion de Qwen : `enable_thinking: false`).
3. Jours de la semaine en français dans le contexte donné au LLM.
4. Exemples injectés en mode outils et descriptions des outils système traduits en français
   (sinon le modèle répond en chinois) ; calendrier lunaire chinois retiré.
5. Filtre du nom (`voixfr_filtre_nom.py`) : le robot ne répond qu'aux phrases contenant
   « Stack-chan » (orthographe approchée), puis sans le nom pendant 20 s après chaque réponse.
   Réglages `filtre_nom` dans `.config.yaml` (`actif: false` pour couper).
6. Outils du robot (`voixfr_outils_robot.py`) : descriptions japonaises traduites,
   `speak_katakoto` (voix japonaise en kana) masqué.

Chaque correctif vérifie que le code d'origine est celui attendu et s'arrête sans rien
modifier dans le cas contraire (nouvelle version de xiaozhi à revérifier).

## Firmware du robot

Utiliser le fork [stackchan-idf-EN-FR](https://github.com/Emilien-Etadam/stackchan-idf-EN-FR) :
écran, outils et voix propre du robot en français. Dans ses réglages (onglet Connecter,
« Langue et voix »), mettre l'URL du serveur vocal : `http://192.168.30.121:8200`.
