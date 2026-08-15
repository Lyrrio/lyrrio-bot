# Guide complet — Anime Games Bot

## 1. Discord Developer Portal

1. Ouvre le [Discord Developer Portal](https://discord.com/developers/applications).
2. Clique sur **New Application**, choisis un nom puis ouvre l’onglet **Bot**.
3. Dans **Privileged Gateway Intents**, active seulement **Message Content Intent**.
   Le jeu de personnages en a besoin pour lire les réponses écrites.
4. Dans **Bot > Token**, clique sur **Reset Token**, puis **Copy**. Ne montre jamais
   ce token : il donne le contrôle total du bot.
5. Dans **Installation**, garde **Guild Install** et **Discord Provided Link**.
6. Ajoute les scopes `applications.commands` et `bot`.
7. Accorde uniquement **View Channels**, **Send Messages**, **Embed Links** et
   **Read Message History**.
8. Copie l’Install Link et ouvre-le pour inviter le bot. Il faut la permission
   **Gérer le serveur** sur Discord pour réaliser cette étape.

Aucune Interactions Endpoint URL n’est nécessaire : le programme se connecte depuis
ton PC.

## 2. Installation sur le PC

1. Installe Python 3.12 ou 3.13 depuis
   [python.org](https://www.python.org/downloads/windows/).
2. Double-clique sur `installer.bat`.
3. Ouvre le fichier `.env` créé par l’installateur.
4. Colle le token après `DISCORD_TOKEN=`.

Exemple de forme — ce n’est pas un vrai token :

```text
DISCORD_TOKEN=abc123.exemple.secret
WIN_REWARD=100
TEST_GUILD_ID=
```

Pour faire apparaître les commandes immédiatement sur un serveur de test, active le
mode développeur de Discord, copie l’identifiant du serveur et colle-le après
`TEST_GUILD_ID=`. Sans cela, les commandes globales peuvent mettre un peu de temps à
se synchroniser après une mise à jour.

## 3. Allumer, mettre à jour et éteindre

- **Allumer :** double-clique sur `demarrer.bat` et laisse la fenêtre ouverte.
- **Éteindre :** clique dans la fenêtre puis appuie sur `Ctrl+C`.
- **Après une modification du code :** arrête puis relance simplement `demarrer.bat`.
- **Mettre à jour les personnages en ligne :** arrête le bot puis lance
  `mettre-a-jour-personnages.bat`.

Ne lance jamais deux fenêtres avec le même token. Si le PC s’éteint, redémarre ou se
met en veille, le bot passe hors ligne jusqu’au prochain lancement.

## 4. Jeu du tour des personnages

### Commandes de jeu

- `/anime_creer anime vies chrono` : crée la salle d’attente ;
- `/anime_statut` : affiche joueurs, vies, tour et chrono ;
- `/anime_stop` : arrête la partie, pour l’hôte ou un modérateur ;
- `/anime_liste` : affiche tous les univers disponibles ;
- `/personnages anime recherche page` : affiche les personnages et alias reconnus.

L’hôte est automatiquement inscrit. À partir de deux joueurs, il peut démarrer. Un
nom valide passe au joueur suivant. Un doublon, un personnage inconnu ou un chrono
dépassé retire une vie. Le dernier survivant gagne des pièces.

La comparaison ignore la casse, les accents, la ponctuation et tolère une petite
faute. Des alias tels que `Big Mom`, `Barbe Blanche`, `Pipo`, `Kirua`, `Deku`,
`Jotaro`, `The World` ou `Tortue Géniale` sont acceptés.

Le catalogue contient One Piece, Naruto, Mushoku Tensei, My Hero Academia, Demon
Slayer, Jujutsu Kaisen, L’Attaque des Titans, Dragon Ball, Bleach, Hunter x Hunter,
Death Note, Fullmetal Alchemist et JoJo's Bizarre Adventure.

## 5. Corriger et personnaliser le catalogue

Ces commandes demandent la permission Discord **Gérer le serveur** :

- `/catalogue anime_ajouter nom identifiant` ;
- `/catalogue anime_renommer anime nouveau_nom` ;
- `/catalogue anime_supprimer anime confirmer` ;
- `/catalogue personnage_ajouter anime nom alias` ;
- `/catalogue personnage_renommer anime personnage nouveau_nom` ;
- `/catalogue personnage_supprimer anime personnage confirmer` ;
- `/catalogue alias_ajouter anime personnage surnom`.

Dans `personnage_ajouter`, plusieurs alias peuvent être séparés avec `;` :

```text
alias: Surnom français; Nom de héros; Autre orthographe
```

Un anime ajouté manuellement porte la mention **custom**, apparaît dans les mêmes
suggestions que les animes fournis et fonctionne avec le même moteur de tolérance.
Les changements sont sauvegardés dans `data/catalog_edits.json` et résistent aux
redémarrages ainsi qu’aux mises à jour du catalogue téléchargé.

Utilise d’abord `/personnages anime recherche` quand une réponse est refusée. Tu
pourras vérifier le nom officiel puis ajouter immédiatement l’orthographe manquante
avec `/catalogue alias_ajouter`.

## 6. Undercover

### Jouer

1. Lance `/undercover_creer categorie discussion imposteurs`.
2. Les joueurs rejoignent avec le bouton. Minimum : 3 joueurs.
3. L’hôte démarre.
4. Chaque joueur clique sur **Voir mon mot**. Le message est éphémère et privé.
5. Discutez sans prononcer le mot exact.
6. Votez avec `/undercover_vote membre`.
7. Lorsque tous les survivants ont voté, la personne majoritaire est éliminée.

Le bot choisit aléatoirement lequel des deux mots est celui des Undercover : le
premier mot d’une paire n’est donc pas toujours le mot civil. En cas d’égalité, une
nouvelle discussion commence. Les civils gagnent quand tous les Undercover sont
éliminés. Les Undercover gagnent lorsqu’ils sont au moins aussi nombreux que les
civils survivants.

Commandes utiles :

- `/undercover_statut` : survivants, joueurs ayant regardé leur mot et chrono ;
- `/undercover_vote membre` : vote privé, modifiable jusqu’au dernier vote ;
- `/undercover_stop` : arrête la partie ;
- `/undercover_paires categorie recherche page` : affiche les mots disponibles.

Deux catégories sont fournies : **Général** et **Anime**, avec 60 paires chacune.

### Modifier les mots

Ces commandes demandent également **Gérer le serveur** :

- `/undercover_mots categorie_ajouter nom identifiant` ;
- `/undercover_mots categorie_renommer categorie nouveau_nom` ;
- `/undercover_mots categorie_supprimer categorie confirmer` ;
- `/undercover_mots paire_ajouter categorie mot_1 mot_2` ;
- `/undercover_mots paire_modifier categorie paire_id mot_1 mot_2` ;
- `/undercover_mots paire_supprimer categorie paire_id confirmer`.

Les identifiants `#...` sont visibles avec `/undercover_paires` et proposés dans les
suggestions des commandes de modification. Les changements sont conservés dans
`data/undercover_edits.json`.

## 7. Économie et sauvegardes

- `/solde` affiche tes pièces et victoires ;
- `/solde membre` consulte un autre joueur ;
- `/classement` affiche les dix joueurs les plus riches.

Le vainqueur du tour des personnages reçoit `WIN_REWARD` pièces. Dans Undercover,
chaque membre du camp gagnant reçoit cette récompense. La valeur par défaut est 100.

À sauvegarder si tu changes de PC :

- `.env` pour la configuration secrète ;
- `data/economy.db` pour les portefeuilles ;
- `data/catalog_edits.json` pour les animes et alias custom ;
- `data/undercover_edits.json` pour les mots custom.

Ces fichiers sont ignorés par Git afin de ne pas publier le token ni les données de
ton serveur.

## 8. Dépannage

- **Bot hors ligne :** vérifie le token et garde `demarrer.bat` ouvert.
- **Réponses non lues :** active Message Content Intent puis redémarre.
- **Commandes absentes :** vérifie le scope `applications.commands`, renseigne
  temporairement `TEST_GUILD_ID`, puis redémarre.
- **Missing Access / Forbidden :** donne au bot les permissions indiquées plus haut.
- **Personnage refusé :** cherche-le avec `/personnages`, puis ajoute son orthographe
  avec `/catalogue alias_ajouter`.
- **Mot privé inaccessible :** seul un joueur inscrit dans la partie active peut
  utiliser le bouton **Voir mon mot**.
