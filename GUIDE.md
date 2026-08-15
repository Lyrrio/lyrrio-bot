# Installation complète sur Windows

## 1. Créer l’application Discord

1. Ouvre le [Discord Developer Portal](https://discord.com/developers/applications),
   connecte-toi, clique **New Application**, donne un nom au bot puis confirme.
2. Dans **Bot**, choisis éventuellement son pseudo et son avatar.
3. Toujours dans **Bot**, sous **Privileged Gateway Intents**, active uniquement
   **Message Content Intent**, puis sauvegarde. Le jeu en a besoin pour lire le nom
   écrit pendant le tour. `Presence Intent` et `Server Members Intent` sont inutiles.
4. Dans **Bot > Token**, clique **Reset Token**, confirme, puis **Copy**. Garde ce
   token secret : il donne le contrôle du bot. Ne le poste jamais dans Discord.

## 2. Autoriser et inviter le bot

Dans **Installation** :

1. garde **Guild Install** comme contexte d’installation ;
2. choisis **Discord Provided Link** comme type de lien ;
3. dans **Default Install Settings > Guild Install**, ajoute les scopes
   `applications.commands` et `bot` ;
4. pour les permissions du bot, coche seulement **View Channels**, **Send Messages**,
   **Embed Links** et **Read Message History** ;
5. sauvegarde, copie l’**Install Link**, ouvre-le et ajoute le bot à ton serveur.

Il faut avoir la permission **Gérer le serveur** pour l’ajouter. Aucun
**Interactions Endpoint URL** n’est nécessaire : ce bot se connecte directement à
Discord depuis ton PC.

## 3. Installer Python et le bot

1. Installe [Python](https://www.python.org/downloads/windows/) 3.12 ou 3.13.
   Pendant l’installation, autorise l’ajout de Python au `PATH` si l’option apparaît.
2. Double-clique sur `installer.bat`. Il crée un environnement isolé `.venv` et
   installe seulement `discord.py`.
3. Ouvre le fichier `.env` créé dans ce dossier avec le Bloc-notes.
4. Remplace la valeur après `DISCORD_TOKEN=` par le token copié, sans espaces ni
   guillemets, puis enregistre.

Exemple de forme (ceci n’est pas un vrai token) :

```text
DISCORD_TOKEN=abc123.exemple.secret
```

### Commandes visibles immédiatement sur le serveur de test (optionnel)

Les commandes globales peuvent parfois mettre un moment à apparaître. Pour une
synchronisation immédiate sur ton serveur :

1. dans Discord, ouvre **Paramètres utilisateur > Avancés** et active le
   **Mode développeur** ;
2. clic droit sur l’icône de ton serveur, puis **Copier l’identifiant du serveur** ;
3. colle ce nombre après `TEST_GUILD_ID=` dans `.env`.

Quand le bot sera utilisé sur plusieurs serveurs, vide cette valeur pour repasser
aux commandes globales, puis redémarre-le.

## 4. Allumer et éteindre

- **Allumer :** double-clique sur `demarrer.bat`. Garde la fenêtre ouverte. Quand
  le journal affiche `Connecté en tant que ...`, le bot est en ligne.
- **Éteindre proprement :** clique dans cette fenêtre, appuie sur `Ctrl+C`, puis
  confirme avec `O` si Windows le demande. Fermer la fenêtre arrête aussi le bot.
- Si le PC s’éteint, redémarre ou se met en veille, le bot passe hors ligne. Il
  suffit de relancer `demarrer.bat` au retour.

Ne lance pas deux fenêtres `demarrer.bat` en même temps avec le même token.

## 5. Jouer

1. Dans un salon textuel, lance `/anime_creer`.
2. Choisis un univers dans les suggestions. `vies` (défaut 3, de 1 à 10) et
   `chrono` (défaut 20 secondes, de 5 à 120) sont optionnels.
3. Les joueurs cliquent **Rejoindre**. L’hôte est inscrit automatiquement.
4. À partir de 2 joueurs, l’hôte clique **Démarrer**.
5. Le joueur mentionné écrit un nom dans le salon. Un personnage valide passe le
   tour. Un doublon, un nom inconnu ou un délai dépassé retire une vie. À zéro vie,
   le joueur est éliminé; le dernier gagne.

Il n’y a pas de maximum codé : la limite pratique est simplement le nombre de
membres présents sur Discord.

## Tolérance des noms et catalogue

La comparaison ignore les majuscules, accents, espaces et ponctuation. Elle accepte
aussi l’ordre prénom/nom, les alias courants configurés et une petite faute de
frappe. Une réponse courte ou ambiguë n’est volontairement pas devinée.

Le cache livré contient **4 461 fiches** issues des pages de personnages des entrées
anime configurées : One Piece, Naruto, Mushoku Tensei, My Hero Academia, Demon
Slayer, Jujutsu Kaisen, L’Attaque des Titans, Dragon Ball, Bleach, Hunter x Hunter,
Death Note et Fullmetal Alchemist.

« Tous les personnages » signifie ici tous ceux répertoriés sur ces pages au moment
de la génération. Un personnage uniquement présent dans le manga, tout juste ajouté
ou absent de la source peut manquer. Pour actualiser le cache, arrête le bot puis
double-clique sur `mettre-a-jour-personnages.bat`; l’opération nécessite Internet et
peut prendre quelques minutes.

Pour ajouter un anime, ajoute dans `anime_config.json` une entrée avec son libellé et
les identifiants MyAnimeList de ses saisons, puis relance la mise à jour.

## Dépannage rapide

- **Le bot est hors ligne :** `demarrer.bat` doit rester ouvert et le token doit être
  correct. Un token régénéré rend l’ancien invalide.
- **Il ne lit pas les réponses :** vérifie **Message Content Intent** dans l’onglet
  **Bot** du Developer Portal, puis redémarre.
- **Les commandes `/anime_...` n’apparaissent pas :** réinvite le bot avec le scope
  `applications.commands`, ou utilise temporairement `TEST_GUILD_ID`.
- **`Missing Access` / `Forbidden` :** donne au bot accès au salon et les quatre
  permissions indiquées plus haut.
- **Un personnage manque :** ajoute un alias dans `manual_aliases` de
  `anime_config.json`, ou actualise le catalogue.
