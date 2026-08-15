from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import discord
from discord import app_commands

from catalog import AnimeCatalog
from game_logic import AnswerKind, RoundGame, TurnResult


ROOT = Path(__file__).resolve().parent
CATALOG_PATH = ROOT / "data" / "catalog.json"


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
catalog = AnimeCatalog(CATALOG_PATH)


class GameManager:
    def __init__(self, client: discord.Client):
        self.client = client
        self.sessions: dict[int, RoundGame] = {}
        self.timers: dict[int, asyncio.Task[None]] = {}
        self.locks: dict[int, asyncio.Lock] = {}

    def lock(self, channel_id: int) -> asyncio.Lock:
        return self.locks.setdefault(channel_id, asyncio.Lock())

    def create(self, channel_id: int, game: RoundGame) -> None:
        self.sessions[channel_id] = game

    async def start(self, channel: discord.abc.Messageable, game: RoundGame) -> None:
        game.start()
        await channel.send(
            f"🎬 **La partie commence !** Premier tour : <@{game.current.user_id}> — "
            f"tu as **{game.seconds} secondes**. Écris le nom d’un personnage."
        )
        self._schedule(channel, game)

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
        timer = self.timers.pop(channel_id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()

    def _schedule(self, channel: discord.abc.Messageable, game: RoundGame) -> None:
        old_timer = self.timers.pop(channel.id, None)
        if old_timer and old_timer is not asyncio.current_task():
            old_timer.cancel()
        expected_player = game.current.user_id

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

    async def _announce_result(
        self, channel: discord.abc.Messageable, game: RoundGame, result: TurnResult
    ) -> None:
        timer = self.timers.pop(channel.id, None)
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
            text += f"\n🏆 <@{result.winner_id}> remporte la partie !"
            await channel.send(text)
            await self.stop(channel.id)
            return

        text += f"\n➡️ À <@{game.current.user_id}> — **{game.seconds} secondes**."
        await channel.send(text)
        self._schedule(channel, game)


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
            await interaction.response.send_message("Tu as rejoint la partie.", ephemeral=True)
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
            await interaction.response.send_message("Tu as quitté la partie.", ephemeral=True)
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


intents = discord.Intents.none()
intents.guilds = True
intents.messages = True
intents.message_content = True


class AnimeBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.games = GameManager(self)

    async def setup_hook(self) -> None:
        test_guild = os.getenv("TEST_GUILD_ID", "").strip()
        if test_guild:
            guild = discord.Object(id=int(test_guild))
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("%s commande(s) synchronisée(s) sur le serveur de test.", len(synced))
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
    embed = discord.Embed(
        title=f"🎮 {catalog.label(anime)}",
        description=(
            "Chacun cite un personnage différent à son tour. Un doublon, un nom inconnu "
            "ou un délai dépassé retire une vie. Le dernier survivant gagne."
        ),
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Hôte", value=interaction.user.mention)
    embed.add_field(name="Vies", value=str(vies))
    embed.add_field(name="Chrono", value=f"{chrono} s")
    embed.add_field(name="Catalogue", value=f"{catalog.count(anime)} personnages")
    await interaction.response.send_message(embed=embed, view=LobbyView(bot.games, interaction.channel_id))


@bot.tree.command(name="anime_statut", description="Affiche l’état de la partie de ce salon")
@app_commands.guild_only()
async def anime_status(interaction: discord.Interaction) -> None:
    game = bot.games.sessions.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("Aucune partie dans ce salon.", ephemeral=True)
        return
    players = "\n".join(f"• <@{p.user_id}> — {p.lives} vie(s)" for p in game.players)
    phase = f"tour de <@{game.current.user_id}>" if game.started else "salle d’attente"
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


def main() -> None:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "colle_le_token_du_bot_ici":
        raise SystemExit("DISCORD_TOKEN manque dans le fichier .env. Consulte GUIDE.md.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
