# Anime Turn Bot

Bot Discord léger de mini-jeu : chaque joueur doit citer à son tour un personnage
différent de l’univers choisi. Les fautes légères sont tolérées.

➡️ Commence par **[GUIDE.md](GUIDE.md)**. Sous Windows, l’installation et le
démarrage se font ensuite en double-cliquant sur les fichiers `.bat` fournis.

## Commandes

- `/anime_creer` — crée une partie avec anime, vies et chrono configurables ;
- `/anime_statut` — affiche les joueurs, vies et nombre de réponses utilisées ;
- `/anime_stop` — arrête la partie (hôte ou modérateur) ;
- `/anime_liste` — affiche tous les univers et la taille de leur catalogue.

Le bot utilise un seul processus Python, aucune base de données et aucun serveur
web. Le catalogue est un JSON local lu une fois au démarrage.
