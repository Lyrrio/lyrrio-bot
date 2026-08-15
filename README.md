# Anime Games Bot

Bot Discord léger, auto-hébergeable sur Windows, avec économie persistante et deux jeux :

- **Tour des personnages** : chacun cite un personnage différent avant la fin du chrono ;
- **Undercover** : mots secrets proches, discussion, votes et imposteurs.

➡️ Consulte **[GUIDE.md](GUIDE.md)** pour l’installation, les réglages du Discord
Developer Portal et toutes les commandes.

## Fonctions principales

- 13 univers et environ 4 680 personnages, dont **JoJo's Bizarre Adventure** ;
- fautes de frappe légères, accents, noms français et surnoms acceptés ;
- `/personnages` pour voir exactement les noms et alias reconnus ;
- catalogue modifiable sur Discord par les membres autorisés ;
- animes custom conservés après un redémarrage et utilisables comme les animes normaux ;
- 120 paires Undercover par défaut : 60 générales et 60 anime ;
- catégories et paires Undercover entièrement modifiables ;
- monnaie, récompenses, `/solde` et `/classement` ;
- un seul processus Python, `discord.py` et SQLite, sans serveur web.

Les données personnelles du serveur (`.env`, économie et modifications custom) sont
ignorées par Git et ne sont donc pas publiées accidentellement.
