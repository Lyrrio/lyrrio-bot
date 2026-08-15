from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from pathlib import Path

import discord
from discord import app_commands

from catalog import AnimeCatalog, normalize
from economy import EconomyStore
from game_logic import AnswerKind, RoundGame, TurnResult
from undercover import UndercoverGame, UndercoverWordStore, VoteResult


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "catalog.json"
CONFIG_PATH = ROOT / "anime_config.json"
ECONOMY_PATH = ROOT / "data" / "economy.db"
CATALOG_EDITS_PATH = ROOT / "data" / "catalog_edits.json"
UNDERCOVER_WORDS_PATH = ROOT / "data" / "undercover_words.json"
UNDERCOVER_EDITS_PATH = ROOT / "data" / "undercover_edits.json"


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env(ROOT / ".env")
catalog = AnimeCatalog(CATALOG_PATH, CONFIG_PATH, CATALOG_EDITS_PATH)
economy = EconomyStore(ECONOMY_PATH)
undercover_words = UndercoverWordStore(UNDERCOVER_WORDS_PATH, UNDERCOVER_EDITS_PATH)
try:
    WIN_REWARD = max(1, int(os.getenv("WIN_REWARD", "100")))
except ValueError:
    WIN_REWARD = 100


class GameManager:
    def __init__(self, client: discord.Client, economy_store: EconomyStore, win_reward: int):
        self.client = client
        self.economy = economy_store
        self.win_reward = win_reward
        self.sessions: dict[int, RoundGame] = {}
        self.timers: dict[int, asyncio.Task[None]] = {}
        self.locks: dict[int, asyncio.Lock] = {}
        self.deadlines: dict[int, float] = {}

    def lock(self, channel_id: int) -> asyncio.Lock:
        return self.locks.setdefault(channel_id, asyncio.Lock())

    def create(self, channel_id: int, game: RoundGame) -> None:
        self.sessions[channel_id] = game

    async def start(self, channel: discord.abc.Messageable, game: RoundGame) -> None:
        game.start()
        deadline = self._schedule(channel, game)
        await channel.send(
            f"🎬 **La partie commence !** Premier tour : <@{game.current.user_id}> — "
            f"tu as **{game.seconds} secondes**. Écris le nom d’un personnage.\n"
            f"⏱️ Fin du tour <t:{deadline}:R> — à <t:{deadline}:T>.",
            view=TurnTimerView(self, channel.id, game.current.user_id),
        )

    async def handle_message(self, message: discord.Message) -> None:
        game = self.sessions.get(message.channel.id)
        if not game or not game.started or game.finished:
            return
        async with self.lock(message.channel.id):
            if game.finished or message.author.id != game.current.user_id:
                return
            character = catalog.resolve(game.anime, message.content)
            result = game.accept(
                character.id if character else None,
                character.name if character else None,
            )
            await self._announce_result(message.channel, game, result)

    async def stop(self, channel_id: int) -> None:
        self.sessions.pop(channel_id, None)
        self.locks.pop(channel_id, None)
        self.deadlines.pop(channel_id, None)
        timer = self.timers.pop(channel_id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()

    def remaining(self, channel_id: int) -> int | None:
        deadline = self.deadlines.get(channel_id)
        if deadline is None:
            return None
        return max(0, math.ceil(deadline - time.time()))

    def _schedule(self, channel: discord.abc.Messageable, game: RoundGame) -> int:
        old_timer = self.timers.pop(channel.id, None)
        if old_timer and old_timer is not asyncio.current_task():
            old_timer.cancel()
        expected_player = game.current.user_id
        deadline = time.time() + game.seconds
        self.deadlines[channel.id] = deadline

        async def wait_for_turn() -> None:
            try:
                await asyncio.sleep(game.seconds)
                async with self.lock(channel.id):
                    current = self.sessions.get(channel.id)
                    if current is not game or game.finished or game.current.user_id != expected_player:
                        return
                    await self._announce_result(channel, game, game.timeout())
            except asyncio.CancelledError:
                pass

        self.timers[channel.id] = asyncio.create_task(wait_for_turn())
        return math.ceil(deadline)

    async def _announce_result(
        self, channel: discord.abc.Messageable, game: RoundGame, result: TurnResult
    ) -> None:
        timer = self.timers.pop(channel.id, None)
        self.deadlines.pop(channel.id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()

        if result.kind is AnswerKind.VALID:
            text = f"✅ **{result.character_name}** est accepté."
        elif result.kind is AnswerKind.DUPLICATE:
            text = f"♻️ **{result.character_name}** a déjà été cité. Une vie en moins !"
        elif result.kind is AnswerKind.UNKNOWN:
            text = "❌ Personnage inconnu dans ce catalogue. Une vie en moins !"
        else:
            text = "⏰ Temps écoulé. Une vie en moins !"

        if result.lives_left is not None:
            text += f" <@{result.player_id}> : **{result.lives_left}** vie(s)."
        if result.eliminated:
            text += f"\n💀 <@{result.player_id}> est éliminé."
        if result.winner_id is not None:
            wallet = self.economy.award_win(result.winner_id, self.win_reward)
            text += f"\n🏆 <@{result.winner_id}> remporte la partie !"
            text += (
                f"\n💰 **+{self.win_reward} pièces** — nouveau solde : "
                f"**{wallet.balance} pièces** ({wallet.wins} victoire(s))."
            )
            await channel.send(text)
            await self.stop(channel.id)
            return

        deadline = self._schedule(channel, game)
        text += (
            f"\n➡️ À <@{game.current.user_id}> — **{game.seconds} secondes**."
            f"\n⏱️ Fin du tour <t:{deadline}:R> — à <t:{deadline}:T>."
        )
        await channel.send(
            text,
            view=TurnTimerView(self, channel.id, game.current.user_id),
        )


class TurnTimerView(discord.ui.View):
    def __init__(self, manager: GameManager, channel_id: int, player_id: int):
        super().__init__(timeout=125)
        self.manager = manager
        self.channel_id = channel_id
        self.player_id = player_id

    @discord.ui.button(label="Voir le chrono", emoji="⏱️", style=discord.ButtonStyle.secondary)
    async def show_timer(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.manager.sessions.get(self.channel_id)
        remaining = self.manager.remaining(self.channel_id)
        if (
            not game
            or not game.started
            or game.finished
            or game.current.user_id != self.player_id
            or remaining is None
            or remaining <= 0
        ):
            await interaction.response.send_message("Ce tour est déjà terminé.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"⏱️ Il reste **{remaining} seconde(s)** à <@{self.player_id}>.",
            ephemeral=True,
        )


def add_roster_fields(embed: discord.Embed, title: str, lines: list[str]) -> None:
    shown = lines[:100]
    chunks: list[str] = []
    current = ""
    for line in shown:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > 950:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    if len(lines) > len(shown):
        suffix = f"\n… et {len(lines) - len(shown)} autre(s)"
        if chunks:
            chunks[-1] += suffix
        else:
            chunks.append(suffix.strip())
    for position, chunk in enumerate(chunks or ["Aucun joueur"]):
        embed.add_field(
            name=title if position == 0 else "Joueurs — suite",
            value=chunk,
            inline=False,
        )


def build_lobby_embed(game: RoundGame) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮 {catalog.label(game.anime)}",
        description=(
            "Chacun cite un personnage différent à son tour. Un doublon, un nom inconnu "
            "ou un délai dépassé retire une vie. Le dernier survivant gagne."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Hôte", value=f"<@{game.host_id}>")
    embed.add_field(name="Vies", value=str(game.starting_lives))
    embed.add_field(name="Chrono", value=f"{game.seconds} s")
    embed.add_field(name="Récompense", value=f"{WIN_REWARD} pièces")
    embed.add_field(name="Catalogue", value=f"{catalog.count(game.anime)} personnages")
    player_lines = [
        f"• <@{player.user_id}>" + (" — hôte" if player.user_id == game.host_id else "")
        for player in game.players
    ]
    add_roster_fields(embed, f"Joueurs inscrits ({len(game.players)})", player_lines)
    return embed


class LobbyView(discord.ui.View):
    def __init__(self, manager: GameManager, channel_id: int):
        super().__init__(timeout=600)
        self.manager = manager
        self.channel_id = channel_id

    def game(self) -> RoundGame | None:
        return self.manager.sessions.get(self.channel_id)

    @discord.ui.button(label="Rejoindre", emoji="➕", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("Cette salle d’attente est fermée.", ephemeral=True)
            return
        if game.add_player(interaction.user.id, interaction.user.display_name):
            await interaction.response.edit_message(embed=build_lobby_embed(game), view=self)
            await interaction.followup.send("Tu as rejoint la partie.", ephemeral=True)
        else:
            await interaction.response.send_message("Tu es déjà dans la partie.", ephemeral=True)

    @discord.ui.button(label="Quitter", emoji="➖", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("La salle d’attente est fermée.", ephemeral=True)
            return
        if interaction.user.id == game.host_id:
            await interaction.response.send_message("L’hôte ne peut pas quitter; utilise Annuler.", ephemeral=True)
        elif game.remove_player(interaction.user.id):
            await interaction.response.edit_message(embed=build_lobby_embed(game), view=self)
            await interaction.followup.send("Tu as quitté la partie.", ephemeral=True)
        else:
            await interaction.response.send_message("Tu n’étais pas inscrit.", ephemeral=True)

    @discord.ui.button(label="Démarrer", emoji="▶️", style=discord.ButtonStyle.primary)
    async def launch(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("Cette salle d’attente est fermée.", ephemeral=True)
            return
        if interaction.user.id != game.host_id:
            await interaction.response.send_message("Seul l’hôte peut démarrer.", ephemeral=True)
            return
        if len(game.players) < 2:
            await interaction.response.send_message("Il faut au moins deux joueurs.", ephemeral=True)
            return
        await interaction.response.defer()
        self.stop()
        await self.manager.start(interaction.channel, game)

    @discord.ui.button(label="Annuler", emoji="🛑", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game:
            await interaction.response.send_message("Cette partie n’existe plus.", ephemeral=True)
            return
        if interaction.user.id != game.host_id:
            await interaction.response.send_message("Seul l’hôte peut annuler.", ephemeral=True)
            return
        await self.manager.stop(self.channel_id)
        self.stop()
        await interaction.response.send_message("Partie annulée.")

    async def on_timeout(self) -> None:
        game = self.game()
        if game and not game.started:
            await self.manager.stop(self.channel_id)


class UndercoverManager:
    def __init__(self, economy_store: EconomyStore, win_reward: int):
        self.economy = economy_store
        self.win_reward = win_reward
        self.sessions: dict[int, UndercoverGame] = {}
        self.timers: dict[int, asyncio.Task[None]] = {}
        self.deadlines: dict[int, float] = {}

    def create(self, channel_id: int, game: UndercoverGame) -> None:
        self.sessions[channel_id] = game

    async def stop(self, channel_id: int) -> None:
        self.sessions.pop(channel_id, None)
        self.deadlines.pop(channel_id, None)
        timer = self.timers.pop(channel_id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()

    def remaining(self, channel_id: int) -> int | None:
        deadline = self.deadlines.get(channel_id)
        return None if deadline is None else max(0, math.ceil(deadline - time.time()))

    async def start(self, channel: discord.abc.Messageable, game: UndercoverGame) -> None:
        pair = undercover_words.random_pair(game.category)
        game.start(pair)
        deadline = self._schedule_discussion(channel, game)
        await channel.send(
            "🕵️ **La partie Undercover commence !**\n"
            "Clique sur **Voir mon mot** : le bot te le montrera en privé. Ne montre pas "
            "l'écran aux autres. L'un des deux mots de la paire a été tiré aléatoirement "
            "pour le ou les imposteurs.\n"
            f"💬 Discussion : **{game.discussion_seconds} secondes**, jusqu'à <t:{deadline}:T> "
            f"(<t:{deadline}:R>). Ensuite, votez avec `/undercover_vote`.",
            view=UndercoverRevealView(self, channel.id),
        )

    def _schedule_discussion(
        self, channel: discord.abc.Messageable, game: UndercoverGame
    ) -> int:
        old = self.timers.pop(channel.id, None)
        if old and old is not asyncio.current_task():
            old.cancel()
        deadline = time.time() + game.discussion_seconds
        self.deadlines[channel.id] = deadline
        expected_round = game.round_number

        async def wait_for_discussion() -> None:
            try:
                await asyncio.sleep(game.discussion_seconds)
                current = self.sessions.get(channel.id)
                if current is game and not game.finished and game.round_number == expected_round:
                    self.deadlines.pop(channel.id, None)
                    await channel.send(
                        "⏰ **Discussion terminée !** Tous les survivants doivent voter avec "
                        "`/undercover_vote membre:@quelqu'un`. Vous pouvez changer votre vote "
                        "tant que tout le monde n'a pas voté."
                    )
            except asyncio.CancelledError:
                pass

        self.timers[channel.id] = asyncio.create_task(wait_for_discussion())
        return math.ceil(deadline)

    async def announce_vote(
        self,
        channel: discord.abc.Messageable,
        game: UndercoverGame,
        result: VoteResult,
    ) -> None:
        if not result.complete:
            return
        timer = self.timers.pop(channel.id, None)
        self.deadlines.pop(channel.id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()
        if result.tie:
            deadline = self._schedule_discussion(channel, game)
            await channel.send(
                "⚖️ **Égalité !** Personne n'est éliminé. Une nouvelle discussion commence "
                f"jusqu'à <t:{deadline}:T> (<t:{deadline}:R>)."
            )
            return
        eliminated_role = (
            "Undercover" if result.eliminated_id in game.undercover_ids else "Civil"
        )
        text = f"🗳️ <@{result.eliminated_id}> est éliminé : c'était un **{eliminated_role}**."
        if result.winner_ids:
            side = "les Undercover" if result.undercover_won else "les Civils"
            rewards: list[str] = []
            for user_id in result.winner_ids:
                wallet = self.economy.award_win(user_id, self.win_reward)
                rewards.append(f"<@{user_id}> ({wallet.balance} pièces)")
            assert game.pair is not None
            text += (
                f"\n🏆 Victoire de **{side}** ! Gagnants : "
                + ", ".join(rewards)
                + f"\n🔎 La paire était **{game.pair.word_1} / {game.pair.word_2}**. "
                f"Chaque gagnant reçoit **{self.win_reward} pièces**."
            )
            await channel.send(text)
            await self.stop(channel.id)
            return
        deadline = self._schedule_discussion(channel, game)
        text += (
            f"\n💬 Manche **{game.round_number}** : nouvelle discussion jusqu'à "
            f"<t:{deadline}:T> (<t:{deadline}:R>), puis revotez."
        )
        await channel.send(text)


def build_undercover_lobby_embed(game: UndercoverGame) -> discord.Embed:
    embed = discord.Embed(
        title=f"🕵️ Undercover — {undercover_words.label(game.category)}",
        description=(
            "Les civils reçoivent un mot et le ou les Undercover un mot proche. "
            "Discutez sans être trop précis, puis votez pour éliminer les suspects."
        ),
        color=discord.Color.dark_purple(),
    )
    embed.add_field(name="Hôte", value=f"<@{game.host_id}>")
    embed.add_field(name="Discussion", value=f"{game.discussion_seconds} s")
    embed.add_field(name="Undercover", value=str(game.undercover_count))
    embed.add_field(name="Paires disponibles", value=str(len(undercover_words.pairs(game.category))))
    embed.add_field(name="Récompense", value=f"{WIN_REWARD} pièces/gagnant")
    player_lines = [
        f"• <@{player.user_id}>" + (" — hôte" if player.user_id == game.host_id else "")
        for player in game.players
    ]
    add_roster_fields(embed, f"Joueurs inscrits ({len(game.players)})", player_lines)
    return embed


class UndercoverLobbyView(discord.ui.View):
    def __init__(self, manager: UndercoverManager, channel_id: int):
        super().__init__(timeout=600)
        self.manager = manager
        self.channel_id = channel_id

    def game(self) -> UndercoverGame | None:
        return self.manager.sessions.get(self.channel_id)

    @discord.ui.button(label="Rejoindre", emoji="➕", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("Cette salle d'attente est fermée.", ephemeral=True)
        elif game.add_player(interaction.user.id, interaction.user.display_name):
            await interaction.response.edit_message(embed=build_undercover_lobby_embed(game), view=self)
            await interaction.followup.send("Tu as rejoint Undercover.", ephemeral=True)
        else:
            await interaction.response.send_message("Tu es déjà inscrit.", ephemeral=True)

    @discord.ui.button(label="Quitter", emoji="➖", style=discord.ButtonStyle.secondary)
    async def leave(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("Cette salle d'attente est fermée.", ephemeral=True)
        elif interaction.user.id == game.host_id:
            await interaction.response.send_message("L'hôte doit utiliser Annuler.", ephemeral=True)
        elif game.remove_player(interaction.user.id):
            await interaction.response.edit_message(embed=build_undercover_lobby_embed(game), view=self)
            await interaction.followup.send("Tu as quitté Undercover.", ephemeral=True)
        else:
            await interaction.response.send_message("Tu n'étais pas inscrit.", ephemeral=True)

    @discord.ui.button(label="Démarrer", emoji="▶️", style=discord.ButtonStyle.primary)
    async def launch(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game or game.started:
            await interaction.response.send_message("Cette salle d'attente est fermée.", ephemeral=True)
            return
        if interaction.user.id != game.host_id:
            await interaction.response.send_message("Seul l'hôte peut démarrer.", ephemeral=True)
            return
        if len(game.players) < 3:
            await interaction.response.send_message("Il faut au moins trois joueurs.", ephemeral=True)
            return
        if game.undercover_count > len(game.players) - 2:
            await interaction.response.send_message(
                "Pas assez de civils pour ce nombre d'Undercover.", ephemeral=True
            )
            return
        await interaction.response.defer()
        self.stop()
        await self.manager.start(interaction.channel, game)

    @discord.ui.button(label="Annuler", emoji="🛑", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.game()
        if not game:
            await interaction.response.send_message("Cette partie n'existe plus.", ephemeral=True)
        elif interaction.user.id != game.host_id:
            await interaction.response.send_message("Seul l'hôte peut annuler.", ephemeral=True)
        else:
            await self.manager.stop(self.channel_id)
            self.stop()
            await interaction.response.send_message("Partie Undercover annulée.")

    async def on_timeout(self) -> None:
        game = self.game()
        if game and not game.started:
            await self.manager.stop(self.channel_id)


class UndercoverRevealView(discord.ui.View):
    def __init__(self, manager: UndercoverManager, channel_id: int):
        super().__init__(timeout=900)
        self.manager = manager
        self.channel_id = channel_id

    @discord.ui.button(label="Voir mon mot", emoji="👁️", style=discord.ButtonStyle.primary)
    async def reveal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        game = self.manager.sessions.get(self.channel_id)
        if not game:
            await interaction.response.send_message("Cette partie est terminée.", ephemeral=True)
            return
        try:
            word = game.reveal(interaction.user.id)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            f"🤫 Ton mot secret est : **{word}**\nNe le copie pas dans le salon !",
            ephemeral=True,
        )


intents = discord.Intents.none()
intents.guilds = True
intents.messages = True
intents.message_content = True


class AnimeBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.games = GameManager(self, economy, WIN_REWARD)
        self.undercover = UndercoverManager(economy, WIN_REWARD)

    async def setup_hook(self) -> None:
        test_guild = os.getenv("TEST_GUILD_ID", "").strip()
        if test_guild:
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            guild_synced = await self.tree.sync(guild=guild)
            logging.info(
                "%s commande(s) synchronisées immédiatement sur le serveur de test.",
                len(guild_synced),
            )
            global_synced = await self.tree.sync()
            logging.info(
                "%s commande(s) globales publiées pour les autres serveurs.",
                len(global_synced),
            )
        else:
            synced = await self.tree.sync()
            logging.info("%s commande(s) globale(s) synchronisée(s).", len(synced))

    async def on_ready(self) -> None:
        logging.info("Connecté en tant que %s (%s)", self.user, self.user.id if self.user else "?")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        await self.games.handle_message(message)


bot = AnimeBot()


async def anime_autocomplete(
    _: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    needle = current.casefold()
    return [
        app_commands.Choice(name=f"{label} ({catalog.count(slug)} persos)", value=slug)
        for slug, label in catalog.choices()
        if needle in label.casefold() or needle in slug
    ][:25]


async def character_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    slug = getattr(interaction.namespace, "anime", "")
    if not slug or not catalog.exists(slug):
        return []
    needle = catalog.find_characters(slug, current)
    return [
        app_commands.Choice(name=character.name[:100], value=character.name[:100])
        for character in needle[:25]
    ]


def custom_mark(slug: str) -> str:
    return " 🛠️ custom" if catalog.is_custom(slug) else ""


async def require_catalog_admin(interaction: discord.Interaction) -> bool:
    member = interaction.user
    if isinstance(member, discord.Member) and member.guild_permissions.manage_guild:
        return True
    await interaction.response.send_message(
        "Il faut la permission **Gérer le serveur** pour modifier le catalogue.",
        ephemeral=True,
    )
    return False


@bot.tree.command(name="personnages", description="Affiche les personnages reconnus pour un anime")
@app_commands.guild_only()
@app_commands.describe(
    anime="Anime à consulter",
    recherche="Nom ou surnom à rechercher",
    page="Page à afficher",
)
@app_commands.autocomplete(anime=anime_autocomplete)
async def characters_list(
    interaction: discord.Interaction,
    anime: str,
    recherche: str = "",
    page: app_commands.Range[int, 1, 999] = 1,
) -> None:
    if not catalog.exists(anime):
        await interaction.response.send_message("Anime introuvable.", ephemeral=True)
        return
    found = catalog.find_characters(anime, recherche)
    per_page = 9
    page_count = max(1, math.ceil(len(found) / per_page))
    if page > page_count:
        await interaction.response.send_message(
            f"Cette page n'existe pas. Dernière page : **{page_count}**.", ephemeral=True
        )
        return
    lines: list[str] = []
    for character in found[(page - 1) * per_page : page * per_page]:
        aliases = [alias for alias in character.aliases if normalize(alias) != normalize(character.name)]
        alias_text = f" — alias : {', '.join(aliases[:4])}" if aliases else ""
        lines.append(f"• **{character.name}**{alias_text}"[:190])
    title = f"📚 {catalog.label(anime)}{custom_mark(anime)}"
    details = (
        f"Résultats pour **{recherche}** : **{len(found)}**"
        if recherche
        else f"**{len(found)} personnages reconnus**"
    )
    await interaction.response.send_message(
        f"{title}\n{details} — page **{page}/{page_count}**\n\n"
        + ("\n".join(lines) if lines else "Aucun personnage trouvé."),
        ephemeral=True,
    )


catalogue_group = app_commands.Group(
    name="catalogue", description="Modifie les animes, personnages et surnoms du bot"
)


@catalogue_group.command(name="anime_ajouter", description="Ajoute un anime custom vide")
@app_commands.guild_only()
@app_commands.describe(nom="Nom affiché de l'anime", identifiant="Identifiant facultatif, ex. jojo")
async def catalogue_anime_add(
    interaction: discord.Interaction, nom: str, identifiant: str | None = None
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        slug = catalog.add_anime(nom, identifiant)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Anime custom **{catalog.label(slug)}** ajouté (`{slug}`). "
        "Ajoute maintenant ses personnages avec `/catalogue personnage_ajouter`.",
        ephemeral=True,
    )


@catalogue_group.command(name="anime_renommer", description="Change le nom affiché d'un anime")
@app_commands.guild_only()
@app_commands.autocomplete(anime=anime_autocomplete)
async def catalogue_anime_rename(
    interaction: discord.Interaction, anime: str, nouveau_nom: str
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        catalog.rename_anime(anime, nouveau_nom)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ L'anime s'appelle maintenant **{catalog.label(anime)}**.", ephemeral=True
    )


@catalogue_group.command(name="anime_supprimer", description="Supprime ou masque un anime du bot")
@app_commands.guild_only()
@app_commands.describe(confirmer="Doit être activé pour éviter une suppression accidentelle")
@app_commands.autocomplete(anime=anime_autocomplete)
async def catalogue_anime_delete(
    interaction: discord.Interaction, anime: str, confirmer: bool
) -> None:
    if not await require_catalog_admin(interaction):
        return
    if not confirmer:
        await interaction.response.send_message(
            "Suppression annulée : active l'option `confirmer`.", ephemeral=True
        )
        return
    try:
        label = catalog.label(anime)
        catalog.delete_anime(anime)
    except (ValueError, KeyError) as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(f"🗑️ **{label}** a été supprimé du bot.")


@catalogue_group.command(name="personnage_ajouter", description="Ajoute manuellement un personnage")
@app_commands.guild_only()
@app_commands.describe(
    alias="Surnoms séparés par des points-virgules, ex. JoJo; Jotaro-san"
)
@app_commands.autocomplete(anime=anime_autocomplete)
async def catalogue_character_add(
    interaction: discord.Interaction, anime: str, nom: str, alias: str = ""
) -> None:
    if not await require_catalog_admin(interaction):
        return
    aliases = [value for value in alias.split(";") if value.strip()]
    try:
        character = catalog.add_character(anime, nom, aliases)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ **{character.name}** ajouté à **{catalog.label(anime)}** "
        f"avec **{max(0, len(character.aliases) - 1)} alias**.",
        ephemeral=True,
    )


@catalogue_group.command(name="personnage_renommer", description="Corrige le nom d'un personnage")
@app_commands.guild_only()
@app_commands.autocomplete(anime=anime_autocomplete, personnage=character_autocomplete)
async def catalogue_character_rename(
    interaction: discord.Interaction, anime: str, personnage: str, nouveau_nom: str
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        old = catalog.resolve(anime, personnage)
        character = catalog.rename_character(anime, personnage, nouveau_nom)
    except (ValueError, KeyError) as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ **{old.name if old else personnage}** devient **{character.name}**.", ephemeral=True
    )


@catalogue_group.command(name="personnage_supprimer", description="Supprime un personnage d'un anime")
@app_commands.guild_only()
@app_commands.autocomplete(anime=anime_autocomplete, personnage=character_autocomplete)
async def catalogue_character_delete(
    interaction: discord.Interaction, anime: str, personnage: str, confirmer: bool
) -> None:
    if not await require_catalog_admin(interaction):
        return
    if not confirmer:
        await interaction.response.send_message(
            "Suppression annulée : active l'option `confirmer`.", ephemeral=True
        )
        return
    try:
        character = catalog.delete_character(anime, personnage)
    except (ValueError, KeyError) as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"🗑️ **{character.name}** a été supprimé de **{catalog.label(anime)}**.",
        ephemeral=True,
    )


@catalogue_group.command(name="alias_ajouter", description="Ajoute un surnom reconnu à un personnage")
@app_commands.guild_only()
@app_commands.autocomplete(anime=anime_autocomplete, personnage=character_autocomplete)
async def catalogue_alias_add(
    interaction: discord.Interaction, anime: str, personnage: str, surnom: str
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        character = catalog.add_alias(anime, personnage, surnom)
    except (ValueError, KeyError) as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ **{surnom}** désigne maintenant **{character.name}** dans "
        f"**{catalog.label(anime)}**.",
        ephemeral=True,
    )


bot.tree.add_command(catalogue_group)


@bot.tree.command(name="anime_creer", description="Crée une partie de noms de personnages d’anime")
@app_commands.guild_only()
@app_commands.describe(anime="Univers choisi", vies="Vies par joueur (défaut : 3)", chrono="Secondes par tour (défaut : 20)")
@app_commands.autocomplete(anime=anime_autocomplete)
async def anime_create(
    interaction: discord.Interaction,
    anime: str,
    vies: app_commands.Range[int, 1, 10] = 3,
    chrono: app_commands.Range[int, 5, 120] = 20,
) -> None:
    if not interaction.channel:
        return
    if anime not in dict(catalog.choices()):
        await interaction.response.send_message("Anime inconnu : choisis une suggestion de la liste.", ephemeral=True)
        return
    if interaction.channel_id in bot.games.sessions:
        await interaction.response.send_message("Une partie existe déjà dans ce salon.", ephemeral=True)
        return
    game = RoundGame(interaction.user.id, anime, vies, chrono)
    game.add_player(interaction.user.id, interaction.user.display_name)
    bot.games.create(interaction.channel_id, game)
    await interaction.response.send_message(
        embed=build_lobby_embed(game),
        view=LobbyView(bot.games, interaction.channel_id),
    )


@bot.tree.command(name="anime_statut", description="Affiche l’état de la partie de ce salon")
@app_commands.guild_only()
async def anime_status(interaction: discord.Interaction) -> None:
    game = bot.games.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie dans ce salon.", ephemeral=True)
        return
    shown_players = game.players[:50]
    players = "\n".join(f"• <@{p.user_id}> — {p.lives} vie(s)" for p in shown_players)
    if len(game.players) > len(shown_players):
        players += f"\n… et {len(game.players) - len(shown_players)} autre(s)"
    if game.started:
        remaining = bot.games.remaining(interaction.channel_id)
        timer_text = f" — ⏱️ **{remaining} s restantes**" if remaining is not None else ""
        phase = f"tour de <@{game.current.user_id}>{timer_text}"
    else:
        phase = "salle d’attente"
    await interaction.response.send_message(
        f"**{catalog.label(game.anime)}** — {phase}\n{players}\n"
        f"Personnages déjà cités : **{len(game.used_character_ids)}**"
    )


@bot.tree.command(name="anime_stop", description="Arrête la partie de ce salon")
@app_commands.guild_only()
async def anime_stop(interaction: discord.Interaction) -> None:
    game = bot.games.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie dans ce salon.", ephemeral=True)
        return
    can_manage = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages
    if interaction.user.id != game.host_id and not can_manage:
        await interaction.response.send_message("Seuls l’hôte ou un modérateur peuvent arrêter.", ephemeral=True)
        return
    await bot.games.stop(interaction.channel_id)
    await interaction.response.send_message("🛑 Partie arrêtée.")


@bot.tree.command(name="anime_liste", description="Liste les univers disponibles")
async def anime_list(interaction: discord.Interaction) -> None:
    lines = [f"• **{label}** — {catalog.count(slug)} personnages" for slug, label in catalog.choices()]
    await interaction.response.send_message("\n".join(lines), ephemeral=True)


@bot.tree.command(name="solde", description="Affiche le portefeuille et les victoires")
@app_commands.describe(membre="Membre à consulter (toi par défaut)")
async def balance(interaction: discord.Interaction, membre: discord.User | None = None) -> None:
    target = membre or interaction.user
    wallet = economy.get(target.id)
    await interaction.response.send_message(
        f"💰 **Portefeuille de {target.mention}**\n"
        f"• Solde : **{wallet.balance} pièces**\n"
        f"• Victoires : **{wallet.wins}**",
        ephemeral=True,
    )


@bot.tree.command(name="classement", description="Affiche les joueurs les plus riches")
async def leaderboard(interaction: discord.Interaction) -> None:
    wallets = economy.leaderboard(10)
    if not wallets:
        await interaction.response.send_message(
            "Le classement est vide : gagne une partie pour l’inaugurer !",
            ephemeral=True,
        )
        return
    medals = ["🥇", "🥈", "🥉"]
    lines = [
        f"{medals[position] if position < 3 else f'**{position + 1}.**'} "
        f"<@{wallet.user_id}> — **{wallet.balance} pièces** · {wallet.wins} victoire(s)"
        for position, wallet in enumerate(wallets)
    ]
    await interaction.response.send_message(
        "🏦 **Classement économique**\n" + "\n".join(lines)
    )


async def undercover_category_autocomplete(
    _: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    needle = normalize(current)
    return [
        app_commands.Choice(
            name=f"{label} ({len(undercover_words.pairs(slug))} paires)", value=slug
        )
        for slug, label in undercover_words.choices()
        if needle in normalize(label) or needle in normalize(slug)
    ][:25]


async def undercover_pair_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    category = getattr(interaction.namespace, "categorie", "")
    if not category or not undercover_words.exists(category):
        return []
    query = normalize(current)
    return [
        app_commands.Choice(
            name=f"#{pair.id} — {pair.word_1} / {pair.word_2}"[:100], value=pair.id
        )
        for pair in undercover_words.pairs(category)
        if not query
        or query in normalize(str(pair.id))
        or query in normalize(pair.word_1)
        or query in normalize(pair.word_2)
    ][:25]


@bot.tree.command(name="undercover_creer", description="Crée une partie d'Undercover personnalisable")
@app_commands.guild_only()
@app_commands.describe(
    categorie="Liste de paires à utiliser",
    discussion="Durée de discussion par manche",
    imposteurs="Nombre d'Undercover",
)
@app_commands.autocomplete(categorie=undercover_category_autocomplete)
async def undercover_create(
    interaction: discord.Interaction,
    categorie: str = "general",
    discussion: app_commands.Range[int, 15, 600] = 90,
    imposteurs: app_commands.Range[int, 1, 5] = 1,
) -> None:
    if not interaction.channel:
        return
    if not undercover_words.exists(categorie):
        await interaction.response.send_message("Catégorie Undercover inconnue.", ephemeral=True)
        return
    if interaction.channel_id in bot.undercover.sessions or interaction.channel_id in bot.games.sessions:
        await interaction.response.send_message(
            "Une partie existe déjà dans ce salon.", ephemeral=True
        )
        return
    if not undercover_words.pairs(categorie):
        await interaction.response.send_message(
            "Cette catégorie ne contient encore aucune paire.", ephemeral=True
        )
        return
    game = UndercoverGame(interaction.user.id, categorie, discussion, imposteurs)
    game.add_player(interaction.user.id, interaction.user.display_name)
    bot.undercover.create(interaction.channel_id, game)
    await interaction.response.send_message(
        embed=build_undercover_lobby_embed(game),
        view=UndercoverLobbyView(bot.undercover, interaction.channel_id),
    )


@bot.tree.command(name="undercover_vote", description="Vote contre un joueur pendant Undercover")
@app_commands.guild_only()
async def undercover_vote(
    interaction: discord.Interaction, membre: discord.Member
) -> None:
    game = bot.undercover.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie Undercover ici.", ephemeral=True)
        return
    try:
        result = game.vote(interaction.user.id, membre.id)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    missing = 0 if result.complete else len(game.alive_ids - set(game.votes))
    await interaction.response.send_message(
        f"🗳️ Vote enregistré contre {membre.mention}. "
        f"Il manque **{missing} vote(s)**.",
        ephemeral=True,
    )
    if interaction.channel:
        await interaction.channel.send(
            f"🗳️ <@{interaction.user.id}> a voté. Il manque **{missing} vote(s)**."
        )
        await bot.undercover.announce_vote(interaction.channel, game, result)


@bot.tree.command(name="undercover_statut", description="Affiche l'état de la partie Undercover")
@app_commands.guild_only()
async def undercover_status(interaction: discord.Interaction) -> None:
    game = bot.undercover.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie Undercover ici.", ephemeral=True)
        return
    shown_players = game.players[:50]
    players = "\n".join(
        f"• <@{player.user_id}>"
        + (
            (" — vivant" if player.user_id in game.alive_ids else " — éliminé")
            if game.started
            else " — inscrit"
        )
        + (" — mot vu" if player.user_id in game.revealed_ids else "")
        for player in shown_players
    )
    if len(game.players) > len(shown_players):
        players += f"\n… et {len(game.players) - len(shown_players)} autre(s)"
    remaining = bot.undercover.remaining(interaction.channel_id)
    phase = (
        f"manche {game.round_number}"
        + (f" — ⏱️ {remaining} s" if remaining is not None else " — votes ouverts")
        if game.started
        else "salle d'attente"
    )
    await interaction.response.send_message(
        f"🕵️ **Undercover — {undercover_words.label(game.category)}**\n"
        f"Phase : **{phase}**\n{players}",
        ephemeral=True,
    )


@bot.tree.command(name="undercover_stop", description="Arrête la partie Undercover de ce salon")
@app_commands.guild_only()
async def undercover_stop(interaction: discord.Interaction) -> None:
    game = bot.undercover.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie Undercover ici.", ephemeral=True)
        return
    can_manage = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.manage_messages
    if interaction.user.id != game.host_id and not can_manage:
        await interaction.response.send_message(
            "Seuls l'hôte ou un modérateur peuvent arrêter.", ephemeral=True
        )
        return
    await bot.undercover.stop(interaction.channel_id)
    await interaction.response.send_message("🛑 Partie Undercover arrêtée.")


@bot.tree.command(name="undercover_paires", description="Affiche les paires de mots Undercover")
@app_commands.describe(categorie="Catégorie à consulter", recherche="Mot à chercher", page="Page")
@app_commands.autocomplete(categorie=undercover_category_autocomplete)
async def undercover_pairs_list(
    interaction: discord.Interaction,
    categorie: str = "general",
    recherche: str = "",
    page: app_commands.Range[int, 1, 999] = 1,
) -> None:
    if not undercover_words.exists(categorie):
        await interaction.response.send_message("Catégorie introuvable.", ephemeral=True)
        return
    pairs = undercover_words.find_pairs(categorie, recherche)
    per_page = 18
    page_count = max(1, math.ceil(len(pairs) / per_page))
    if page > page_count:
        await interaction.response.send_message(
            f"Dernière page disponible : **{page_count}**.", ephemeral=True
        )
        return
    lines = [
        (f"• `#{pair.id}` **{pair.word_1}** / **{pair.word_2}**"
        + (" 🛠️" if pair.custom else ""))[:95]
        for pair in pairs[(page - 1) * per_page : page * per_page]
    ]
    custom = " 🛠️ custom" if undercover_words.is_custom(categorie) else ""
    await interaction.response.send_message(
        f"🗂️ **{undercover_words.label(categorie)}{custom}** — {len(pairs)} paire(s) — "
        f"page {page}/{page_count}\n" + ("\n".join(lines) if lines else "Aucun résultat."),
        ephemeral=True,
    )


undercover_words_group = app_commands.Group(
    name="undercover_mots", description="Modifie les catégories et paires d'Undercover"
)


@undercover_words_group.command(name="categorie_ajouter", description="Ajoute une catégorie custom")
@app_commands.guild_only()
async def undercover_category_add(
    interaction: discord.Interaction, nom: str, identifiant: str | None = None
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        slug = undercover_words.add_category(nom, identifiant)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Catégorie custom **{undercover_words.label(slug)}** ajoutée (`{slug}`).",
        ephemeral=True,
    )


@undercover_words_group.command(name="categorie_renommer", description="Renomme une catégorie")
@app_commands.guild_only()
@app_commands.autocomplete(categorie=undercover_category_autocomplete)
async def undercover_category_rename(
    interaction: discord.Interaction, categorie: str, nouveau_nom: str
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        undercover_words.rename_category(categorie, nouveau_nom)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Catégorie renommée **{undercover_words.label(categorie)}**.", ephemeral=True
    )


@undercover_words_group.command(name="categorie_supprimer", description="Supprime une catégorie")
@app_commands.guild_only()
@app_commands.autocomplete(categorie=undercover_category_autocomplete)
async def undercover_category_delete(
    interaction: discord.Interaction, categorie: str, confirmer: bool
) -> None:
    if not await require_catalog_admin(interaction):
        return
    if not confirmer:
        await interaction.response.send_message("Active `confirmer` pour supprimer.", ephemeral=True)
        return
    try:
        label = undercover_words.label(categorie)
        undercover_words.delete_category(categorie)
    except (ValueError, KeyError) as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(f"🗑️ Catégorie **{label}** supprimée.")


@undercover_words_group.command(name="paire_ajouter", description="Ajoute une paire de mots")
@app_commands.guild_only()
@app_commands.autocomplete(categorie=undercover_category_autocomplete)
async def undercover_pair_add(
    interaction: discord.Interaction, categorie: str, mot_1: str, mot_2: str
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        pair = undercover_words.add_pair(categorie, mot_1, mot_2)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Paire `#{pair.id}` **{pair.word_1} / {pair.word_2}** ajoutée.", ephemeral=True
    )


@undercover_words_group.command(name="paire_modifier", description="Modifie les deux mots d'une paire")
@app_commands.guild_only()
@app_commands.autocomplete(
    categorie=undercover_category_autocomplete, paire_id=undercover_pair_autocomplete
)
async def undercover_pair_edit(
    interaction: discord.Interaction,
    categorie: str,
    paire_id: int,
    mot_1: str,
    mot_2: str,
) -> None:
    if not await require_catalog_admin(interaction):
        return
    try:
        pair = undercover_words.edit_pair(categorie, paire_id, mot_1, mot_2)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"✅ Paire `#{pair.id}` modifiée : **{pair.word_1} / {pair.word_2}**.", ephemeral=True
    )


@undercover_words_group.command(name="paire_supprimer", description="Supprime une paire de mots")
@app_commands.guild_only()
@app_commands.autocomplete(
    categorie=undercover_category_autocomplete, paire_id=undercover_pair_autocomplete
)
async def undercover_pair_delete(
    interaction: discord.Interaction, categorie: str, paire_id: int, confirmer: bool
) -> None:
    if not await require_catalog_admin(interaction):
        return
    if not confirmer:
        await interaction.response.send_message("Active `confirmer` pour supprimer.", ephemeral=True)
        return
    try:
        pair = undercover_words.delete_pair(categorie, paire_id)
    except ValueError as error:
        await interaction.response.send_message(f"❌ {error}", ephemeral=True)
        return
    await interaction.response.send_message(
        f"🗑️ Paire `#{pair.id}` **{pair.word_1} / {pair.word_2}** supprimée.", ephemeral=True
    )


bot.tree.add_command(undercover_words_group)


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "colle_le_token_du_bot_ici":
        raise SystemExit("DISCORD_TOKEN manque dans le fichier .env. Consulte GUIDE.md.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
