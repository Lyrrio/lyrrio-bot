from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from catalog import normalize


ROOT = Path(__file__).resolve().parent
DATASET = "fadhilakbar/anime-characters-dataset"
API = "https://datasets-server.huggingface.co/filter"
SEARCH_API = "https://datasets-server.huggingface.co/search"


def fetch_page(anime_id: int, offset: int) -> dict:
    source = f"https://myanimelist.net/anime/{anime_id}"
    params = urllib.parse.urlencode(
        {
            "dataset": DATASET,
            "config": "default",
            "split": "train",
            "where": f'"anime_source"=\'{source}\'',
            "offset": offset,
            "length": 100,
        }
    )
    url = f"{API}?{params}"
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "AnimeTurnBot/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 429 or error.code >= 500:
                time.sleep(2 + attempt * 2)
                continue
            raise
        except (TimeoutError, urllib.error.URLError):
            if attempt == 4:
                raise
            time.sleep(2 + attempt * 2)
    raise RuntimeError("La source de données ne répond pas.")


def fetch_anime(anime_id: int) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        payload = fetch_page(anime_id, offset)
        page = [item["row"] for item in payload.get("rows", [])]
        rows.extend(page)
        total = int(payload.get("num_rows_total", len(rows)))
        if not page or len(rows) >= total:
            return rows
        offset += len(page)


def fetch_mal_anime(anime_id: int) -> list[dict]:
    url = f"https://myanimelist.net/anime/{anime_id}/_/characters"
    for attempt in range(5):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; AnimeTurnBot/1.0)",
                    "Accept-Language": "fr,en;q=0.8",
                },
            )
            with urllib.request.urlopen(request, timeout=45) as response:
                page = response.read().decode("utf-8", errors="replace")
            section_start = page.find("Characters &amp; Voice Actors")
            if section_start < 0:
                section_start = page.find("Characters & Voice Actors")
            section_end = page.find("Most Popular Characters", max(0, section_start))
            if section_start >= 0:
                page = page[section_start : section_end if section_end >= 0 else None]
            found: dict[int, dict] = {}
            pattern = r'https://myanimelist\.net/character/(\d+)/([^"?#/<]+)'
            for raw_id, raw_slug in re.findall(pattern, page):
                name = html.unescape(urllib.parse.unquote(raw_slug)).replace("_", " ").strip()
                cid = int(raw_id)
                found[cid] = {
                    "character_name": name,
                    "character_source": f"https://myanimelist.net/character/{cid}/{raw_slug}",
                }
            if found:
                return list(found.values())
            raise RuntimeError(f"Aucun personnage trouvé sur {url}")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError):
            if attempt == 4:
                # Le dataset est une solution de repli si MAL est temporairement indisponible.
                return fetch_anime(anime_id)
            time.sleep(2 + attempt * 2)
    return []


def fetch_search(query: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        params = urllib.parse.urlencode(
            {
                "dataset": DATASET,
                "config": "default",
                "split": "train",
                "query": query,
                "offset": offset,
                "length": 100,
            }
        )
        request = urllib.request.Request(
            f"{SEARCH_API}?{params}", headers={"User-Agent": "AnimeTurnBot/1.0"}
        )
        with urllib.request.urlopen(request, timeout=45) as response:
            payload = json.load(response)
        page = [item["row"] for item in payload.get("rows", [])]
        # La recherche porte sur toutes les colonnes : on garde uniquement les
        # titres d'anime contenant réellement le nom de la franchise.
        wanted = normalize(query)
        rows.extend(row for row in page if wanted in normalize(str(row.get("anime_name", ""))))
        total = int(payload.get("num_rows_total", offset + len(page)))
        if not page or offset + len(page) >= total:
            return rows
        offset += len(page)


def stable_id(source: str) -> int:
    return int.from_bytes(hashlib.sha256(source.encode("utf-8")).digest()[:8], "big")


def basic_aliases(name: str) -> set[str]:
    aliases = {name, re.sub(r"[^\w\s]", " ", name)}
    comma_parts = [part.strip() for part in name.split(",") if part.strip()]
    if len(comma_parts) >= 2:
        aliases.add(" ".join(reversed(comma_parts)))
        aliases.add(comma_parts[-1])
    words = name.split()
    if len(words) >= 2:
        aliases.add(" ".join(reversed(words)))
    return {" ".join(alias.split()) for alias in aliases if alias.strip()}


def manual_target(canonical: str, characters: dict[int, dict]) -> int | None:
    key = normalize(canonical)
    exact = [cid for cid, item in characters.items() if key in {normalize(a) for a in basic_aliases(item["name"])}]
    if len(exact) == 1:
        return exact[0]
    last_part = normalize(canonical.split(",")[-1])
    matches = [
        cid for cid, item in characters.items()
        if last_part and last_part in normalize(item["name"]).split()
    ]
    if len(matches) == 1:
        return matches[0]
    wanted_words = set(key.split())
    ranked = sorted(
        (
            (len(wanted_words & set(normalize(item["name"]).split())), cid)
            for cid, item in characters.items()
        ),
        reverse=True,
    )
    if ranked and ranked[0][0] > 0 and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]):
        return ranked[0][1]
    return None


def build_anime(slug: str, config: dict) -> dict:
    characters: dict[int, dict] = {}
    names_seen: set[str] = set()

    def add_row(row: dict) -> None:
        name_key = normalize(row["character_name"])
        if not name_key or name_key in names_seen:
            return
        source = str(row.get("character_source") or f"name:{name_key}")
        cid = stable_id(source)
        characters[cid] = {"id": cid, "name": row["character_name"]}
        names_seen.add(name_key)

    for position, anime_id in enumerate(config["anime_ids"], 1):
        print(
            f"[{slug}] entrée {position}/{len(config['anime_ids'])} : MAL #{anime_id}",
            flush=True,
        )
        for row in fetch_mal_anime(anime_id):
            add_row(row)
        time.sleep(0.35)

    alias_sets = {cid: basic_aliases(item["name"]) for cid, item in characters.items()}
    token_owners: Counter[str] = Counter()
    for item in characters.values():
        for token in re.findall(r"[\wÀ-ÿ'-]+", item["name"]):
            key = normalize(token)
            if len(key) >= 3:
                token_owners[key] += 1
    for cid, item in characters.items():
        for token in re.findall(r"[\wÀ-ÿ'-]+", item["name"]):
            if token_owners[normalize(token)] == 1:
                alias_sets[cid].add(token)

    for canonical, aliases in config.get("manual_aliases", {}).items():
        cid = manual_target(canonical, characters)
        if cid is None:
            print(f"  avertissement : personnage manuel introuvable : {canonical}", flush=True)
            continue
        alias_sets[cid].update(aliases)

    return {
        "label": config["label"],
        "characters": [
            {**characters[cid], "aliases": sorted(alias_sets[cid], key=str.casefold)}
            for cid in sorted(characters, key=lambda value: characters[value]["name"].casefold())
        ],
    }


def main() -> None:
    config = json.loads((ROOT / "anime_config.json").read_text(encoding="utf-8"))
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": f"MyAnimeList character pages; fallback: Hugging Face {DATASET} (CC BY 4.0)",
        "anime": {slug: build_anime(slug, item) for slug, item in config.items()},
    }
    output = ROOT / "data" / "catalog.json"
    output.parent.mkdir(exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(output)
    total = sum(len(item["characters"]) for item in payload["anime"].values())
    print(f"Terminé : {total} fiches réparties dans {len(payload['anime'])} univers.", flush=True)


if __name__ == "__main__":
    main()
