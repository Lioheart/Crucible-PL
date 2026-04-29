import json
import os
import pathlib
import shutil
import zipfile
from urllib.request import urlretrieve

import plyvel
import requests

CAPTION_ACTOR_MAPPING = {
    "tokenName": {
        "path": "prototypeToken.name",
        "converter": "nested_object_converter"
    },
    "items": {
        "path": "items",
        "converter": "embedded_items_converter"
    },
    "actions": {
        "path": "system.actions",
        "converter": "actions_converter"
    },
    "ancestry": {
        "path": "system.details.ancestry",
        "converter": "embedded_object_with_actions_converter"
    },
    "background": {
        "path": "system.details.background",
        "converter": "embedded_object_with_actions_converter"
    },
    "biography": {
        "path": "system.details.biography",
        "converter": "embedded_biography_converter"
    },
    "archetype": {
        "path": "system.details.archetype",
        "converter": "embedded_object_with_actions_converter"
    },
    "taxonomy": {
        "path": "system.details.taxonomy",
        "converter": "embedded_object_with_actions_converter"
    }
}


def create_version_directory(version: str) -> bool:
    folder_path = pathlib.Path(version).resolve()

    if folder_path.exists():
        print(f'Katalog {version} istnieje, czyszczę jego zawartość.')

        if not folder_path.is_dir():
            print(f"Ścieżka {folder_path} nie jest folderem lub nie istnieje.")
            return False

        for item in folder_path.iterdir():
            try:
                if item.is_file() or item.is_symlink():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
                print(f"Usunięto: {item.name}")
            except Exception as e:
                print(f"Nie udało się usunąć {item.name}: {e}")

        print(f"\nFolder {folder_path.name} jest teraz pusty.")
        return False

    print(f'Tworzę katalog {version}')
    folder_path.mkdir(parents=True, exist_ok=True)
    return True


def download_and_extract_zip(zip_url: str, zip_filename: str, extract_folder_zip: str) -> None:
    response = requests.get(zip_url, timeout=60)
    response.raise_for_status()

    with open(zip_filename, 'wb') as zip_file:
        zip_file.write(response.content)

    with zipfile.ZipFile(zip_filename, 'r') as zip_file:
        zip_file.extractall(extract_folder_zip)

    print('Pobrano i rozpakowano plik .zip')


def read_leveldb_to_json(leveldb_path: str, output_json_path: str) -> None:
    def list_subfolders(directory: str):
        try:
            return [f.name for f in os.scandir(directory) if f.is_dir()]
        except Exception as error:
            raise RuntimeError(f"Wystąpił błąd list_subfolders: {error}") from error

    folders_list = list_subfolders(leveldb_path.replace('\\', '/'))

    for sub_folder in folders_list:
        output_file = os.path.join(output_json_path, f"{sub_folder}.json").replace('\\', '/')
        output_folder = os.path.join(leveldb_path, sub_folder).replace('\\', '/')
        os.makedirs(output_json_path, exist_ok=True)

        db = None
        try:
            db = plyvel.DB(output_folder, create_if_missing=False)
            data = []

            for key, value in db:
                try:
                    value_str = value.decode('utf-8', errors='ignore')
                    try:
                        value_data = json.loads(value_str)
                    except json.JSONDecodeError:
                        value_data = {"name": value_str}

                    data.append(value_data)
                except Exception as e:
                    print(f"Błąd dekodowania dla klucza {key}: {e}")

            with open(output_file, 'w', encoding='utf-8') as json_file:
                json.dump(data, json_file, ensure_ascii=False, indent=4)

            print(f"Dane zostały zapisane do {output_file}")

        except Exception as e:
            raise RuntimeError(f"Wystąpił błąd read_leveldb_to_json dla {output_folder}: {e}") from e
        finally:
            if db is not None:
                db.close()


def sort_entries(input_dict):
    if "entries" in input_dict and isinstance(input_dict["entries"], dict):
        input_dict["entries"] = dict(sorted(input_dict["entries"].items()))

    for key, value in input_dict.items():
        if isinstance(value, dict):
            input_dict[key] = sort_entries(value)

    return input_dict


def remove_empty_keys(data_dict):
    def clean_dict_once(d):
        cleaned = {}
        for key, value in d.items():
            if isinstance(value, dict):
                value = clean_dict_once(value)

            if key == "pages" and not value:
                continue

            if key == "name" and "pages" in d and not d["pages"]:
                continue

            if value not in (None, {}, [], ""):
                cleaned[key] = value

        return cleaned

    previous = None
    current = data_dict

    while previous != current:
        previous = current
        current = clean_dict_once(previous)

    return current


def ensure_actions_mapping(transifex_dict: dict) -> None:
    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"]["actions"] = {
        "path": "system.actions",
        "converter": "actions_converter"
    }


def add_actions(entry_dict: dict, new_data: dict, default_name: str, transifex_dict: dict) -> None:
    actions = new_data.get("system", {}).get("actions", [])
    if not actions:
        return

    ensure_actions_mapping(transifex_dict)
    entry_dict.setdefault("actions", {})

    for action in actions:
        action_name = (action.get("name") or default_name).strip()
        entry_dict["actions"].setdefault(action_name, {})
        entry_dict["actions"][action_name]["name"] = action_name
        entry_dict["actions"][action_name]["condition"] = action.get("condition") or ""
        entry_dict["actions"][action_name]["description"] = action.get("description") or ""

        effects = action.get("effects", [])
        if effects:
            entry_dict["actions"][action_name]["effects"] = []

            for effect in effects:
                effect_name = (effect.get("name") or action_name).strip()
                entry_dict["actions"][action_name]["effects"].append({
                    "name": effect_name
                })


def build_id_index(data: list[dict]) -> dict:
    index = {}
    for obj in data:
        if isinstance(obj, dict) and obj.get("_id"):
            index[obj["_id"]] = obj
    return index


def extract_description(record: dict) -> str:
    if not isinstance(record, dict):
        return ""

    # 1. Najpierw typowy Crucible item/actor embedded description
    system_description = record.get("system", {}).get("description")
    if isinstance(system_description, dict):
        public_desc = (system_description.get("public") or "").strip()
        private_desc = (system_description.get("private") or "").strip()

        if public_desc and private_desc:
            return f"{public_desc}\n\n{private_desc}"
        if public_desc:
            return public_desc
        if private_desc:
            return private_desc

    # 2. Prostsze opisy stringowe
    candidates = [
        record.get("system", {}).get("description"),
        record.get("description"),
        record.get("system", {}).get("details", {}).get("description"),
    ]

    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()

    # 3. Biography jako fallback, tylko jeśli naprawdę chcesz ją traktować jako opis
    biography = record.get("system", {}).get("details", {}).get("biography")
    if isinstance(biography, dict):
        public_bio = (biography.get("public") or "").strip()
        private_bio = (biography.get("private") or "").strip()

        if public_bio and private_bio:
            return f"{public_bio}\n\n{private_bio}"
        if public_bio:
            return public_bio
        if private_bio:
            return private_bio

    return ""


def extract_description_value(record: dict):
    """
    Zwraca description w oryginalnym formacie:
    - dict {"public": "...", "private": "..."} jeśli źródło ma taki format
    - string jeśli źródło ma zwykły tekst
    - "" jeśli brak opisu
    """
    if not isinstance(record, dict):
        return ""

    system_description = record.get("system", {}).get("description")

    # 1. Format obiektowy: {"public": "...", "private": "..."}
    if isinstance(system_description, dict):
        result = {}

        public_desc = system_description.get("public")
        private_desc = system_description.get("private")

        if isinstance(public_desc, str) and public_desc.strip():
            result["public"] = public_desc.strip()
        if isinstance(private_desc, str) and private_desc.strip():
            result["private"] = private_desc.strip()

        if result:
            return result

    # 2. Format tekstowy
    if isinstance(system_description, str) and system_description.strip():
        return system_description.strip()

    # 3. Fallback na description w korzeniu
    plain_description = record.get("description")

    if isinstance(plain_description, dict):
        result = {}

        public_desc = plain_description.get("public")
        private_desc = plain_description.get("private")

        if isinstance(public_desc, str) and public_desc.strip():
            result["public"] = public_desc.strip()
        if isinstance(private_desc, str) and private_desc.strip():
            result["private"] = private_desc.strip()

        if result:
            return result

    if isinstance(plain_description, str) and plain_description.strip():
        return plain_description.strip()

    return ""


def extract_description_text(record: dict) -> str:
    """
    Zwraca opis jako tekst tam, gdzie wynik ma być płaski.
    """
    description_value = extract_description_value(record)

    if isinstance(description_value, str):
        return description_value

    if isinstance(description_value, dict):
        public_desc = (description_value.get("public") or "").strip()
        private_desc = (description_value.get("private") or "").strip()

        if public_desc and private_desc:
            return f"{public_desc}\n\n{private_desc}"
        if public_desc:
            return public_desc
        if private_desc:
            return private_desc

    details_description = record.get("system", {}).get("details", {}).get("description")
    if isinstance(details_description, str) and details_description.strip():
        return details_description.strip()

    biography = record.get("system", {}).get("details", {}).get("biography")
    if isinstance(biography, dict):
        public_bio = (biography.get("public") or "").strip()
        private_bio = (biography.get("private") or "").strip()

        if public_bio and private_bio:
            return f"{public_bio}\n\n{private_bio}"
        if public_bio:
            return public_bio
        if private_bio:
            return private_bio

    return ""


def ensure_nested_mapping(transifex_dict: dict, key: str, path: str, converter: str) -> None:
    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"][key] = {
        "path": path,
        "converter": converter
    }


def add_actions_from_record(
        target_entry: dict,
        source_record: dict,
        fallback_name: str,
        transifex_dict: dict,
        add_mapping: bool = True
) -> None:
    actions = source_record.get("system", {}).get("actions", [])
    if not actions:
        return

    if add_mapping:
        ensure_actions_mapping(transifex_dict)
    target_entry.setdefault("actions", {})

    for action in actions:
        action_name = (action.get("name") or fallback_name).strip()
        if not action_name:
            continue

        target_entry["actions"].setdefault(action_name, {})
        target_entry["actions"][action_name]["name"] = action_name
        target_entry["actions"][action_name]["condition"] = action.get("condition") or ""
        target_entry["actions"][action_name]["description"] = action.get("description") or ""

        effects = action.get("effects", [])
        if effects:
            target_entry["actions"][action_name]["effects"] = []
            for effect in effects:
                effect_name = (effect.get("name") or action_name).strip()
                target_entry["actions"][action_name]["effects"].append({
                    "name": effect_name
                })


def resolve_reference(ref_id: str, id_index: dict) -> dict | None:
    if not ref_id or not isinstance(ref_id, str):
        return None
    return id_index.get(ref_id)


def resolve_reference_list(ref_list, id_index: dict) -> list[dict]:
    resolved = []
    if isinstance(ref_list, list):
        for ref_id in ref_list:
            record = resolve_reference(ref_id, id_index)
            if record:
                resolved.append(record)
    elif isinstance(ref_list, str):
        record = resolve_reference(ref_list, id_index)
        if record:
            resolved.append(record)
    return resolved


def fill_translated_object_from_record(
        target_obj: dict,
        source_record: dict,
        transifex_dict: dict,
        preserve_description_shape: bool = False
) -> None:
    source_name = (source_record.get("name") or "").strip()
    if source_name:
        target_obj["name"] = source_name

    if preserve_description_shape:
        description_value = extract_description_value(source_record)
        if description_value not in ("", {}, None):
            target_obj["description"] = description_value
    else:
        description_text = extract_description_text(source_record)
        if description_text:
            target_obj["description"] = description_text

    add_actions_from_record(
        target_entry=target_obj,
        source_record=source_record,
        fallback_name=source_name or "action",
        transifex_dict=transifex_dict
    )


def populate_reference_bucket(
        parent_entry: dict,
        bucket_name: str,
        source_value,
        id_index: dict,
        transifex_dict: dict
) -> None:
    resolved_records = resolve_reference_list(source_value, id_index)
    if not resolved_records:
        return

    parent_entry.setdefault(bucket_name, {})

    for record in resolved_records:
        record_name = (record.get("name") or "").strip()
        if not record_name:
            continue

        parent_entry[bucket_name].setdefault(record_name, {})

        # Dla items zachowujemy oryginalny format description:
        # string albo {"public", "private"}
        preserve_description_shape = bucket_name == "items"

        fill_translated_object_from_record(
            target_obj=parent_entry[bucket_name][record_name],
            source_record=record,
            transifex_dict=transifex_dict,
            preserve_description_shape=preserve_description_shape
        )


def populate_single_reference_object(
        parent_entry: dict,
        field_name: str,
        source_value,
        id_index: dict,
        transifex_dict: dict
) -> None:
    record = None

    if isinstance(source_value, str):
        record = resolve_reference(source_value, id_index)
    elif isinstance(source_value, dict) and source_value.get("_id"):
        record = resolve_reference(source_value["_id"], id_index)

    if not record:
        return

    parent_entry.setdefault(field_name, {})
    fill_translated_object_from_record(
        target_obj=parent_entry[field_name],
        source_record=record,
        transifex_dict=transifex_dict
    )


def populate_prototype_fields(
        entry: dict,
        new_data: dict,
        id_index: dict,
        transifex_dict: dict,
        items_source=None
) -> None:
    mapping_data = {
        "items": ("items", "adventure_items_converter"),
        "actions": ("system.actions", "actions_converter"),
        "ancestry": ("system.details.ancestry", "nested_object_converter"),
        "background": ("system.details.background", "nested_object_converter"),
        "biography": ("system.details.biography", "nested_object_converter"),
        "archetype": ("system.details.archetype", "nested_object_converter"),
        "taxonomy": ("system.details.taxonomy", "nested_object_converter"),
    }

    transifex_dict.setdefault("mapping", {})
    for key, (path, conv) in mapping_data.items():
        transifex_dict["mapping"][key] = {
            "path": path,
            "converter": conv
        }

    # actions bezpośrednio na rekordzie
    add_actions_from_record(
        target_entry=entry,
        source_record=new_data,
        fallback_name=entry.get("name", "action"),
        transifex_dict=transifex_dict
    )

    # items: źródło zależne od typu danych
    if items_source is None:
        items_source = new_data.get("items", [])

    populate_reference_bucket(
        parent_entry=entry,
        bucket_name="items",
        source_value=items_source,
        id_index=id_index,
        transifex_dict=transifex_dict
    )

    # ancestry/background/biography/archetype/taxonomy
    details = new_data.get("system", {}).get("details", {})

    for field_name in ["ancestry", "background", "biography", "archetype", "taxonomy"]:
        source_value = details.get(field_name)

        record = None
        if isinstance(source_value, str):
            record = resolve_reference(source_value, id_index)
        elif isinstance(source_value, dict):
            if source_value.get("_id"):
                record = resolve_reference(source_value["_id"], id_index)
            else:
                record = source_value

        if not record:
            continue

        entry.setdefault(field_name, {})
        fill_translated_object_from_record(
            target_obj=entry[field_name],
            source_record=record,
            transifex_dict=transifex_dict
        )


def populate_actor_like_prototype(
        actor_entry: dict,
        actor_data: dict,
        id_index: dict,
        transifex_dict: dict
) -> None:
    actor_name = (actor_data.get("name") or "").strip()
    if actor_name:
        actor_entry["name"] = actor_name

    prototype = actor_data.get("prototypeToken", {})
    token_name = prototype.get("name")
    if token_name not in (None, ""):
        actor_entry["tokenName"] = {"name": token_name}

    populate_prototype_fields(
        entry=actor_entry,
        new_data=actor_data,
        id_index=id_index,
        transifex_dict=transifex_dict,
        items_source=prototype.get("items", [])
    )


def ensure_caption_actor_mapping(transifex_dict: dict) -> None:
    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"]["actors"] = {
        "path": "actors",
        "converter": "document",
        "documentType": "Actor",
        "cardinality": "many",
        "mapping": {
            "tokenName": {
                "path": "prototypeToken.name",
                "converter": "name"
            },
            "items": {
                "path": "items",
                "converter": "embedded_items_converter"
            },
            "actions": {
                "path": "system.actions",
                "converter": "actions_converter"
            },
            "ancestry": {
                "path": "system.details.ancestry",
                "converter": "embedded_object_with_actions_converter"
            },
            "background": {
                "path": "system.details.background",
                "converter": "embedded_object_with_actions_converter"
            },
            "archetype": {
                "path": "system.details.archetype",
                "converter": "embedded_object_with_actions_converter"
            },
            "taxonomy": {
                "path": "system.details.taxonomy",
                "converter": "embedded_object_with_actions_converter"
            },
            "biography": {
                "path": "system.details.biography",
                "converter": "embedded_biography_converter"
            }
        }
    }


def populate_caption_actor(
        actor_entry: dict,
        actor_data: dict,
        transifex_dict: dict
) -> None:
    actor_name = (actor_data.get("name") or "").strip()
    if actor_name:
        actor_entry["name"] = actor_name

    ensure_caption_actor_mapping(transifex_dict)

    prototype = actor_data.get("prototypeToken", {})
    token_name = prototype.get("name")
    if isinstance(token_name, str) and token_name.strip():
        actor_entry["tokenName"] = token_name.strip()

    # actions bezpośrednio na aktorze
    add_actions_from_record(
        target_entry=actor_entry,
        source_record=actor_data,
        fallback_name=actor_name or "action",
        transifex_dict=transifex_dict,
        add_mapping=False
    )

    # items są osadzone bezpośrednio w actor_data["items"]
    items = actor_data.get("items", [])
    if items and isinstance(items, list):
        actor_entry.setdefault("items", {})
        ensure_caption_actor_mapping(transifex_dict)

        for item in items:
            if not isinstance(item, dict):
                continue

            item_name = (item.get("name") or "").strip()
            if not item_name:
                continue

            actor_entry["items"].setdefault(item_name, {})
            actor_entry["items"][item_name]["name"] = item_name

            item_description = extract_description_value(item)
            if item_description not in ("", {}, None):
                actor_entry["items"][item_name]["description"] = item_description

            add_actions_from_record(
                target_entry=actor_entry["items"][item_name],
                source_record=item,
                fallback_name=item_name,
                transifex_dict=transifex_dict,
                add_mapping=False
            )

    details = actor_data.get("system", {}).get("details", {})

    for field_name in ["ancestry", "background", "archetype", "taxonomy"]:
        obj = details.get(field_name)
        if not isinstance(obj, dict):
            continue

        actor_entry.setdefault(field_name, {})

        obj_name = (obj.get("name") or "").strip()
        if obj_name:
            actor_entry[field_name]["name"] = obj_name

        obj_description = extract_description(obj)
        if obj_description:
            actor_entry[field_name]["description"] = obj_description

        add_actions_from_record(
            target_entry=actor_entry[field_name],
            source_record=obj,
            fallback_name=obj_name or field_name,
            transifex_dict=transifex_dict,
            add_mapping=False
        )

    biography = details.get("biography")
    if isinstance(biography, dict):
        actor_entry.setdefault("biography", {})
        for key, value in biography.items():
            if isinstance(value, str) and value.strip():
                actor_entry["biography"][key] = value.strip()


def ensure_items_mapping_for_caption(transifex_dict: dict) -> None:
    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"]["items"] = {
        "path": "items",
        "converter": "embedded_items_converter"
    }

    transifex_dict["mapping"]["actions"] = {
        "path": "system.actions",
        "converter": "actions_converter"
    }

    for key in ["ancestry", "background", "archetype", "taxonomy"]:
        transifex_dict["mapping"][key] = {
            "path": f"system.details.{key}",
            "converter": "embedded_object_with_actions_converter"
        }

    transifex_dict["mapping"]["biography"] = {
        "path": "system.details.biography",
        "converter": "embedded_biography_converter"
    }

    transifex_dict["mapping"]["tokenName"] = {
        "path": "prototypeToken.name",
        "converter": "nested_object_converter"
    }


def populate_caption_entry(entry: dict, new_data: dict, id_index: dict, transifex_dict: dict) -> None:
    entry["caption"] = new_data.get("caption", "")
    entry["description"] = new_data.get("description", "")

    # Foldery
    if "folders" in new_data and isinstance(new_data["folders"], list):
        entry.setdefault("folders", {})
        for folder in new_data["folders"]:
            folder_name = (folder.get("name") or "").strip()
            if folder_name:
                entry["folders"][folder_name] = folder_name

    # Dzienniki
    if "journal" in new_data and isinstance(new_data["journal"], list):
        entry.setdefault("journals", {})
        for journal in new_data["journal"]:
            journal_name = (journal.get("name") or "").strip()
            if not journal_name:
                continue

            entry["journals"].setdefault(journal_name, {})
            entry["journals"][journal_name]["name"] = journal_name
            entry["journals"][journal_name].setdefault("pages", {})

            for page in journal.get("pages", []):
                page_name = (page.get("name") or "").strip()
                if not page_name:
                    continue

                entry["journals"][journal_name]["pages"].setdefault(page_name, {})
                entry["journals"][journal_name]["pages"][page_name]["name"] = page_name
                entry["journals"][journal_name]["pages"][page_name]["text"] = (
                    " ".join(page.get("text", {}).get("content", "").split())
                )

    # Sceny
    if "scenes" in new_data and isinstance(new_data["scenes"], list):
        entry.setdefault("scenes", {})
        for scene in new_data["scenes"]:
            scene_name = (scene.get("name") or "").strip()
            if not scene_name:
                continue

            entry["scenes"].setdefault(scene_name, {})
            entry["scenes"][scene_name]["name"] = scene_name
            entry["scenes"][scene_name].setdefault("notes", {})

            for note in scene.get("notes", []):
                note_text = (note.get("text") or "").strip()
                if note_text:
                    entry["scenes"][scene_name]["notes"][note_text] = note_text

    # Makra
    if "macros" in new_data and isinstance(new_data["macros"], list):
        entry.setdefault("macros", {})
        for macro in new_data["macros"]:
            macro_name = (macro.get("name") or "").strip()
            if not macro_name:
                continue

            entry["macros"].setdefault(macro_name, {})
            entry["macros"][macro_name]["name"] = macro_name

            # if macro.get("command") not in (None, ""):
            #     entry["macros"][macro_name]["command"] = macro.get("command")

    # Tabele
    if "tables" in new_data and isinstance(new_data["tables"], list):
        entry.setdefault("tables", {})
        for table in new_data["tables"]:
            table_name = (table.get("name") or "").strip()
            if not table_name:
                continue

            entry["tables"].setdefault(table_name, {})
            entry["tables"][table_name]["name"] = table_name
            entry["tables"][table_name]["description"] = table.get("description", "")
            entry["tables"][table_name].setdefault("results", {})

            for result in table.get("results", []):
                range_data = result.get("range", [])
                if isinstance(range_data, list) and len(range_data) >= 2:
                    result_name = f'{range_data[0]}-{range_data[1]}'
                else:
                    result_name = "unknown"

                entry["tables"][table_name]["results"][result_name] = result.get("text", "")

    # Przedmioty
    if "items" in new_data and isinstance(new_data["items"], list):
        entry.setdefault("items", {})
        for item in new_data["items"]:
            item_name = (item.get("name") or "").strip()
            if not item_name:
                continue

            entry["items"].setdefault(item_name, {})
            entry["items"][item_name]["name"] = item_name

    # Playlisty
    if "playlists" in new_data and isinstance(new_data["playlists"], list):
        entry.setdefault("playlists", {})
        for playlist in new_data["playlists"]:
            playlist_name = (playlist.get("name") or "").strip()
            if not playlist_name:
                continue

            entry["playlists"].setdefault(playlist_name, {})
            entry["playlists"][playlist_name]["name"] = playlist_name
            entry["playlists"][playlist_name]["description"] = playlist.get("description")
            entry["playlists"][playlist_name].setdefault("sounds", {})

            for sound in playlist.get("sounds", []):
                sound_name = (sound.get("name") or "").strip()
                if not sound_name:
                    continue

                entry["playlists"][playlist_name]["sounds"].setdefault(sound_name, {})
                entry["playlists"][playlist_name]["sounds"][sound_name]["name"] = sound_name
                entry["playlists"][playlist_name]["sounds"][sound_name]["description"] = sound.get("description")

    # Aktorzy
    if "actors" in new_data and isinstance(new_data["actors"], list):
        entry.setdefault("actors", {})
        for actor in new_data["actors"]:
            actor_name = (actor.get("name") or "").strip()
            if not actor_name:
                continue

            entry["actors"].setdefault(actor_name, {})
            populate_caption_actor(
                actor_entry=entry["actors"][actor_name],
                actor_data=actor,
                transifex_dict=transifex_dict
            )


def ensure_rules_mapping(transifex_dict: dict) -> None:
    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"]["categories"] = {
        "path": "categories",
        "converter": "categories_converter"
    }


def populate_rules_entry(entry: dict, new_data: dict, id_index: dict, transifex_dict: dict) -> None:
    ensure_rules_mapping(transifex_dict)

    entry["name"] = (new_data.get("name") or "").strip()

    # Categories: kluczowane po _id, jak w Crucible-FR
    category_ids = new_data.get("categories", [])
    if isinstance(category_ids, list) and category_ids:
        entry.setdefault("categories", {})
        for category_id in category_ids:
            category_obj = id_index.get(category_id)
            if not isinstance(category_obj, dict):
                continue

            category_name = (category_obj.get("name") or "").strip()
            if not category_name:
                continue

            entry["categories"].setdefault(category_id, {})
            entry["categories"][category_id]["name"] = category_name

    # Pages: kluczowane po nazwie strony
    page_ids = new_data.get("pages", [])
    if isinstance(page_ids, list) and page_ids:
        entry.setdefault("pages", {})
        for page_id in page_ids:
            page_obj = id_index.get(page_id)
            if not isinstance(page_obj, dict):
                continue

            page_name = (page_obj.get("name") or "").strip()
            if not page_name:
                continue

            text_content = page_obj.get("text", {}).get("content", "")
            if not isinstance(text_content, str):
                text_content = ""

            entry["pages"].setdefault(page_name, {})
            entry["pages"][page_name]["name"] = page_name
            entry["pages"][page_name]["text"] = text_content

def populate_embedded_affixes(entry: dict, new_data: dict, id_index: dict, transifex_dict: dict) -> None:
    effect_ids = new_data.get("effects", [])
    if not isinstance(effect_ids, list) or not effect_ids:
        return

    affixes = {}

    for effect_id in effect_ids:
        affix = id_index.get(effect_id)
        if not isinstance(affix, dict) or affix.get("type") != "affix":
            continue

        affix_name = (affix.get("name") or "").strip()
        if not affix_name:
            continue

        affix_entry = {
            "name": affix_name
        }

        description = affix.get("description")
        if isinstance(description, str) and description.strip():
            affix_entry["description"] = description.strip()

        adjective = affix.get("system", {}).get("adjective")
        if isinstance(adjective, str) and adjective.strip():
            affix_entry["adjective"] = adjective.strip()

        add_actions_from_record(
            target_entry=affix_entry,
            source_record=affix,
            fallback_name=affix_name,
            transifex_dict=transifex_dict,
            add_mapping=False
        )

        affixes[affix_name] = affix_entry

    if affixes:
        entry["affixes"] = affixes
        transifex_dict["mapping"]["affixes"] = {
            "path": "effects",
            "converter": "embedded_affixes_converter"
        }

def process_files(folders: str, version: str) -> None:
    dict_key = []

    for root, dirs, files in os.walk(folders):
        for file in files:
            if not file.endswith(".json"):
                continue

            file_path = os.path.join(root, file)
            print('Oryginalny plik:', file)

            with open(file_path, 'r', encoding='utf-8') as json_file:
                data = json.load(json_file)

            if not isinstance(data, list):
                print(f"Pomijam {file}: plik nie zawiera listy rekordów.")
                continue

            id_index = build_id_index(data)

            try:
                compendium = data[0]
            except (KeyError, AttributeError, IndexError, TypeError):
                compendium = data

            if not isinstance(compendium, dict):
                print(f"Pomijam {file}: nieprawidłowy format danych.")
                continue

            keys = compendium.keys()
            print('Klucze pliku JSON:', list(keys))

            pack_name = file.split('.')[0]
            new_name = f'{version}/crucible.{pack_name}.json'
            print('Nowy plik:', new_name)
            print()

            folder_json_path = pathlib.Path(root) / f'{pack_name}_folders.json'

            if folder_json_path.is_file():
                transifex_dict = {
                    "label": pack_name.title(),
                    "folders": {},
                    "entries": {},
                    "mapping": {}
                }

                with open(folder_json_path, 'r', encoding='utf-8') as json_file:
                    data_folder = json.load(json_file)

                for new_data in data_folder:
                    name = (new_data.get("name") or "").strip()
                    if name:
                        transifex_dict["folders"][name] = name

            elif 'color' in keys or 'folder' in keys:
                transifex_dict = {
                    "label": pack_name.title(),
                    "folders": {},
                    "entries": {},
                    "mapping": {}
                }
            else:
                transifex_dict = {
                    "label": pack_name.title(),
                    "entries": {},
                    "mapping": {}
                }

            flag = []

            for new_data in data:
                if not isinstance(new_data, dict):
                    continue

                name = (new_data.get("name") or "").strip()
                if not name:
                    continue

                # foldery
                if 'folder' in new_data and 'color' in new_data:
                    transifex_dict.setdefault("folders", {})
                    transifex_dict["folders"][name] = name
                    continue

                if pack_name == "equipment" and new_data.get("type") == "affix":
                    continue

                # Specjalna obsługa rules - tylko rekordy z pages są entry
                if pack_name == 'rules':
                    # foldery rules są już łapane wyżej przez color+folder
                    # pomijamy rekordy kategorii i stron
                    if not isinstance(new_data.get("pages"), list):
                        continue

                    transifex_dict["entries"].setdefault(name, {})
                    entry = transifex_dict["entries"][name]
                    populate_rules_entry(entry, new_data, id_index, transifex_dict)
                    continue

                # Dla pozostałych pakietów tworzymy zwykły entry
                transifex_dict["entries"].setdefault(name, {})
                entry = transifex_dict["entries"][name]
                entry["name"] = name

                # Rekordy przygód / playtestów
                if 'caption' in keys:
                    populate_caption_entry(entry, new_data, id_index, transifex_dict)

                # zwykłe opisy
                if 'prototypeToken' not in keys and pack_name not in ['weapon']:
                    if 'caption' not in keys:
                        flag.append('description')

                    description = new_data.get("system", {}).get("description")
                    if description is None:
                        description = new_data.get("description", "")

                    if description:
                        entry["description"] = description

                    if pack_name == "equipment":
                        populate_embedded_affixes(entry, new_data, id_index, transifex_dict)

                    adjective = new_data.get("system", {}).get("adjective")
                    if isinstance(adjective, str) and adjective.strip():
                        entry["adjective"] = adjective.strip()
                        transifex_dict["mapping"]["adjective"] = "system.adjective"

                    add_actions_from_record(entry, new_data, name, transifex_dict)

                if 'description' in flag and 'caption' not in keys:
                    has_structured_description = any(
                        isinstance(item, dict)
                        and (
                                (
                                        isinstance(item.get("system", {}).get("description"), dict)
                                        and (
                                                "public" in item.get("system", {}).get("description", {})
                                                or "private" in item.get("system", {}).get("description", {})
                                        )
                                )
                                or (
                                        isinstance(item.get("description"), dict)
                                        and (
                                                "public" in item.get("description", {})
                                                or "private" in item.get("description", {})
                                        )
                                )
                        )
                        for item in data
                    )

                    has_system_description = any(
                        isinstance(item, dict)
                        and isinstance(item.get("system"), dict)
                        and "description" in item["system"]
                        for item in data
                    )

                    has_root_description = any(
                        isinstance(item, dict)
                        and "description" in item
                        for item in data
                    )

                    if has_structured_description:
                        transifex_dict["mapping"]["description"] = {
                            "path": "system.description",
                            "converter": "structured",
                            "cardinality": "one",
                            "mapping": {
                                "public": "public",
                                "private": "private"
                            }
                        }
                    elif has_system_description:
                        transifex_dict["mapping"]["description"] = "system.description"
                    elif has_root_description:
                        transifex_dict["mapping"]["description"] = "description"

                # SPECJALNA OBSŁUGA prototypeToken
                if 'prototypeToken' in keys:
                    populate_prototype_fields(
                        entry=entry,
                        new_data=new_data,
                        id_index=id_index,
                        transifex_dict=transifex_dict
                    )

            transifex_dict = remove_empty_keys(transifex_dict)
            transifex_dict = sort_entries(transifex_dict)

            with open(new_name, "w", encoding='utf-8') as outfile:
                json.dump(transifex_dict, outfile, ensure_ascii=False, indent=4)

            dict_key.append(f'{compendium.keys()}')


def copy_en_json(version_crucible: str) -> None:
    source_file = os.path.join("pack_crucible", "lang", "en.json")
    destination_dir = version_crucible
    destination_file = os.path.join(destination_dir, "en.json")

    os.makedirs(destination_dir, exist_ok=True)
    shutil.copy2(source_file, destination_file)
    print(f"Skopiowano: {source_file} -> {destination_file}")


def move_json_files(version_crucible: str) -> None:
    base_path = pathlib.Path(version_crucible).resolve()
    target_path = base_path / "compendium"
    target_path.mkdir(parents=True, exist_ok=True)

    json_files = list(base_path.glob("*.json"))

    if not json_files:
        print("Nie znaleziono żadnych plików .json do przeniesienia.")
        return

    for file_path in json_files:
        try:
            shutil.move(str(file_path), str(target_path / file_path.name))
            print(f"Pomyślnie przeniesiono: {file_path.name}")
        except Exception as e:
            print(f"Błąd przy pliku {file_path.name}: {e}")


if __name__ == '__main__':
    crucible_url = "https://github.com/foundryvtt/crucible/releases/latest/download/system.json"

    path_crucible, headers_crucible = urlretrieve(crucible_url, 'crucible.json')

    with open('crucible.json', 'r', encoding='utf-8') as f:
        crucible_meta = json.load(f)

    version_crucible = 'crucible_' + crucible_meta["version"]
    zip_crucible_filename = "system.zip"
    zip_crucible = crucible_meta["download"]
    extract_folder = 'pack_crucible'

    print()
    print("*** Wersja Crucible:", version_crucible, "***")

    if create_version_directory(version_crucible):
        download_and_extract_zip(zip_crucible, zip_crucible_filename, extract_folder)
    else:
        with zipfile.ZipFile(zip_crucible_filename, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)

    read_leveldb_to_json(os.path.join(extract_folder, 'packs'), os.path.join(extract_folder, 'output'))
    print()

    folder = os.path.join('pack_crucible', 'output')
    process_files(folder, version_crucible)
    move_json_files(version_crucible)
    copy_en_json(version_crucible)
