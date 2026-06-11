import json
import os
import pathlib
import shutil
import zipfile
from urllib.request import urlretrieve

import plyvel
import requests


ADDITIONAL_MODULE_MANIFESTS = [
    "https://github.com/master-builder75/Builders-Crucible-Creature-Pack/releases/latest/download/module.json",
    "https://github.com/master-builder75/Builders-Crucible-Pregen-Characters/releases/latest/download/module.json",
]

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


def is_item_like_record(record: dict) -> bool:
    """Rozpoznaje dokument Item i odrzuca rekordy ActiveEffect o tym samym _id."""
    if not isinstance(record, dict):
        return False

    if record.get("type") in {"base", "effect", "affix"}:
        return False

    active_effect_keys = {
        "changes",
        "duration",
        "disabled",
        "start",
        "transfer",
        "statuses",
        "showIcon",
        "origin",
        "tint",
    }
    if any(key in record for key in active_effect_keys):
        return False

    return isinstance(record.get("system"), dict)


def resolve_item_reference(
        item_ref,
        all_records: list[dict],
        id_index: dict
) -> dict | None:
    """
    Rozwiązuje referencję do Item bez przebudowy globalnego id_index.

    Niektóre packi zawierają Item i jego ActiveEffect z identycznym _id.
    Dla aktorów trzeba wybrać dokument Item, a nie ostatni rekord zapisany
    pod tym identyfikatorem w zwykłym słowniku.
    """
    if isinstance(item_ref, dict):
        return item_ref if is_item_like_record(item_ref) else None

    if not isinstance(item_ref, str) or not item_ref:
        return None

    for candidate in all_records:
        if (
            isinstance(candidate, dict)
            and candidate.get("_id") == item_ref
            and is_item_like_record(candidate)
        ):
            return candidate

    fallback = id_index.get(item_ref) if isinstance(id_index, dict) else None
    if is_item_like_record(fallback):
        return fallback

    return None


def resolve_item_reference_list(
        ref_list,
        all_records: list[dict],
        id_index: dict
) -> list[dict]:
    resolved = []

    if isinstance(ref_list, list):
        references = ref_list
    elif isinstance(ref_list, (str, dict)):
        references = [ref_list]
    else:
        references = []

    for item_ref in references:
        record = resolve_item_reference(item_ref, all_records, id_index)
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
        transifex_dict: dict,
        all_records: list[dict] | None = None
) -> None:
    if all_records is None:
        all_records = []

    if bucket_name == "items":
        resolved_records = resolve_item_reference_list(
            ref_list=source_value,
            all_records=all_records,
            id_index=id_index
        )
    else:
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

        item_entry = parent_entry[bucket_name][record_name]

        fill_translated_object_from_record(
            target_obj=item_entry,
            source_record=record,
            transifex_dict=transifex_dict,
            preserve_description_shape=preserve_description_shape
        )

        # Effects dla itemów zagnieżdżonych w aktorach/pregenach/summonach.
        # Nie rusza globalnego id_index i nie wymusza _id jako klucza wyjściowego.
        if bucket_name == "items":
            populate_effects_object_from_refs(
                entry=item_entry,
                source_record=record,
                all_records=all_records,
                id_index=id_index,
                transifex_dict=transifex_dict,
                add_mapping=False
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



def build_embedded_items_mapping() -> dict:
    """
    Deklaratywne mapowanie Babele 2.8+ dla Itemów osadzonych w Actorach.

    Użycie wbudowanego convertera "document" jest konieczne, ponieważ Babele
    tworzy wtedy lokalny runtime scope dla Itemów i ich ActiveEffectów.
    Dzięki temu efekty osadzone w itemach nie są traktowane jak zwykłe ID.
    """
    return {
        "path": "items",
        "converter": "document",
        "documentType": "Item",
        "cardinality": "many",
        "mapping": {
            "description": {
                "path": "system.description",
                "converter": "crucible_description_converter"
            },
            "actions": {
                "path": "system.actions",
                "converter": "actions_converter"
            },
            "effects": {
                "path": "effects",
                "converter": "document",
                "documentType": "ActiveEffect",
                "cardinality": "many",
                "mapping": {
                    "changes": {
                        "path": "system.changes",
                        "converter": "structured",
                        "cardinality": "many",
                        "container": "array",
                        "key": "key",
                        "valuePath": "value"
                    }
                }
            }
        }
    }

def populate_prototype_fields(
        entry: dict,
        new_data: dict,
        id_index: dict,
        transifex_dict: dict,
        items_source=None,
        all_records: list[dict] | None = None
) -> None:
    mapping_data = {
        "actions": ("system.actions", "actions_converter"),
        "ancestry": ("system.details.ancestry", "nested_object_converter"),
        "background": ("system.details.background", "nested_object_converter"),
        "biography": ("system.details.biography", "nested_object_converter"),
        "archetype": ("system.details.archetype", "nested_object_converter"),
        "taxonomy": ("system.details.taxonomy", "nested_object_converter"),
    }

    transifex_dict.setdefault("mapping", {})
    transifex_dict["mapping"]["items"] = build_embedded_items_mapping()

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
        transifex_dict=transifex_dict,
        all_records=all_records
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
            "items": build_embedded_items_mapping(),
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
        transifex_dict: dict,
        all_records: list[dict] | None = None,
        id_index: dict | None = None
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

            populate_effects_object_from_refs(
                entry=actor_entry["items"][item_name],
                source_record=item,
                all_records=all_records or [],
                id_index=id_index or {},
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
    transifex_dict["mapping"]["items"] = build_embedded_items_mapping()

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


def populate_caption_entry(
        entry: dict,
        new_data: dict,
        id_index: dict,
        transifex_dict: dict,
        all_records: list[dict] | None = None
) -> None:
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
                transifex_dict=transifex_dict,
                all_records=all_records,
                id_index=id_index
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

def add_actions_from_record_by_id(target_entry: dict, source_record: dict) -> None:
    actions = source_record.get("system", {}).get("actions", [])
    if not isinstance(actions, list) or not actions:
        return

    target_entry.setdefault("actions", {})

    for action in actions:
        if not isinstance(action, dict):
            continue

        action_id = (action.get("id") or "").strip()
        if not action_id:
            continue

        action_entry = {}

        action_name = action.get("name")
        if isinstance(action_name, str) and action_name.strip():
            action_entry["name"] = action_name.strip()

        action_description = action.get("description")
        if isinstance(action_description, str) and action_description.strip():
            action_entry["description"] = action_description.strip()

        action_condition = action.get("condition")
        if isinstance(action_condition, str):
            action_entry["condition"] = action_condition

        if action_entry:
            target_entry["actions"][action_id] = action_entry


def populate_embedded_affixes(entry: dict, new_data: dict, id_index: dict, transifex_dict: dict) -> None:
    """
    Equipment trzyma affiksy w polu effects jako listę _id.
    W pliku tłumaczenia zostawiamy też klucz effects, bo Babele dostaje właśnie
    document.effects i converter może wtedy tłumaczyć każdy ActiveEffect in-place.
    """
    effect_ids = new_data.get("effects", [])
    if not isinstance(effect_ids, list) or not effect_ids:
        return

    effects = {}

    for effect_id in effect_ids:
        if not isinstance(effect_id, str):
            continue

        affix = id_index.get(effect_id)
        if not isinstance(affix, dict) or affix.get("type") != "affix":
            continue

        affix_name = (affix.get("name") or "").strip()
        if not affix_name:
            continue

        effect_entry = {"name": affix_name}

        label = affix.get("label")
        if isinstance(label, str) and label.strip():
            effect_entry["label"] = label.strip()

        description = affix.get("description")
        if isinstance(description, str) and description.strip():
            effect_entry["description"] = description.strip()

        adjective = affix.get("system", {}).get("adjective")
        if isinstance(adjective, str) and adjective.strip():
            effect_entry["adjective"] = adjective.strip()

        add_actions_from_record_by_id(effect_entry, affix)

        effects[affix_name] = effect_entry

    if effects:
        entry["effects"] = effects
        transifex_dict["mapping"]["effects"] = {
            "path": "effects",
            "converter": "itemEffectsConverter"
        }


def is_effect_like_record(record: dict, source_record: dict | None = None) -> bool:
    """
    Rozpoznaje rekordy ActiveEffect bez zmieniania globalnego id_index.
    To jest ważne dla przypadków typu Sunlight Weakness, gdzie item i efekt
    mogą mieć ten sam _id. Nie wybieramy wtedy ślepo id_index[_id].
    """
    if not isinstance(record, dict):
        return False

    if source_record is not None and record is source_record:
        return False

    # Foundry ActiveEffect zwykle ma te pola na poziomie głównym.
    active_effect_keys = {
        "changes",
        "duration",
        "disabled",
        "start",
        "transfer",
        "statuses",
        "showIcon",
        "origin",
        "tint",
    }

    if any(key in record for key in active_effect_keys):
        return True

    # W niektórych eksportach pomocnicze efekty bywają oznaczone typem.
    if record.get("type") in {"base", "effect", "affix"}:
        return True

    return False


def resolve_effect_reference(effect_ref, all_records: list[dict], id_index: dict, source_record: dict | None = None) -> dict | None:
    """
    Rozwiązuje effects bez przebudowywania id_index na listę rekordów.
    Najpierw skanuje oryginalne dane i wybiera rekord wyglądający jak ActiveEffect,
    z wykluczeniem samego itemu źródłowego. Dopiero potem używa id_index jako fallbacku.
    """
    if isinstance(effect_ref, dict):
        return effect_ref

    if not isinstance(effect_ref, str) or not effect_ref:
        return None

    candidates = [
        record for record in all_records
        if isinstance(record, dict)
        and record.get("_id") == effect_ref
        and record is not source_record
    ]

    for candidate in candidates:
        if is_effect_like_record(candidate, source_record):
            return candidate

    if candidates:
        return candidates[0]

    fallback = id_index.get(effect_ref) if isinstance(id_index, dict) else None
    if isinstance(fallback, dict) and fallback is not source_record:
        return fallback

    return None


def extract_effect_changes(effect_obj: dict):
    changes = effect_obj.get("changes")

    if changes is None and isinstance(effect_obj.get("system"), dict):
        changes = effect_obj.get("system", {}).get("changes")

    if isinstance(changes, dict):
        return {
            key: value.strip()
            for key, value in changes.items()
            if isinstance(key, str)
            and key.strip()
            and isinstance(value, str)
            and value.strip()
        }

    if isinstance(changes, list):
        result = {}
        for change in changes:
            if not isinstance(change, dict):
                continue

            key = change.get("key")
            value = change.get("value")

            if not isinstance(key, str) or not key.strip():
                continue

            # Do pliku tłumaczenia trafiają tylko wartości tekstowe.
            # Liczby i wartości logiczne są mechaniką, nie treścią do tłumaczenia.
            if isinstance(value, str) and value.strip():
                result[key] = value.strip()

        return result

    return {}

def build_effect_translation(effect_obj: dict) -> dict:
    if not isinstance(effect_obj, dict):
        return {}

    effect_entry = {}

    effect_name = (effect_obj.get("name") or "").strip()
    if effect_name:
        effect_entry["name"] = effect_name

    effect_label = (effect_obj.get("label") or "").strip()
    if effect_label:
        effect_entry["label"] = effect_label

    effect_description = effect_obj.get("description")
    if isinstance(effect_description, str) and effect_description.strip():
        effect_entry["description"] = effect_description.strip()
    else:
        system_description = effect_obj.get("system", {}).get("description")
        if isinstance(system_description, str) and system_description.strip():
            effect_entry["description"] = system_description.strip()

    adjective = effect_obj.get("system", {}).get("adjective")
    if isinstance(adjective, str) and adjective.strip():
        effect_entry["adjective"] = adjective.strip()

    changes = extract_effect_changes(effect_obj)
    if changes:
        effect_entry["changes"] = changes

    add_actions_from_record_by_id(effect_entry, effect_obj)

    return effect_entry


def populate_effects_object_from_refs(
        entry: dict,
        source_record: dict,
        all_records: list[dict],
        id_index: dict,
        transifex_dict: dict | None = None,
        add_mapping: bool = False,
        converter: str = "itemEffectsConverter"
) -> None:
    effect_refs = source_record.get("effects", [])
    if not isinstance(effect_refs, list) or not effect_refs:
        return

    effects = {}

    for effect_ref in effect_refs:
        effect_obj = resolve_effect_reference(
            effect_ref=effect_ref,
            all_records=all_records,
            id_index=id_index,
            source_record=source_record
        )

        if not isinstance(effect_obj, dict):
            continue

        effect_entry = build_effect_translation(effect_obj)
        if not effect_entry:
            continue

        effect_key = (
            effect_obj.get("name")
            or effect_obj.get("label")
            or effect_obj.get("_id")
            or (effect_ref if isinstance(effect_ref, str) else "")
        )

        if not isinstance(effect_key, str) or not effect_key.strip():
            continue

        effects[effect_key.strip()] = effect_entry

    if effects:
        entry["effects"] = effects
        if add_mapping and transifex_dict is not None:
            transifex_dict.setdefault("mapping", {})
            transifex_dict["mapping"]["effects"] = {
                "path": "effects",
                "converter": converter
            }


def populate_embedded_effects_from_ids(
        entry: dict,
        new_data: dict,
        id_index: dict,
        transifex_dict: dict,
        all_records: list[dict] | None = None
) -> None:
    effect_refs = new_data.get("effects", [])
    if not isinstance(effect_refs, list) or not effect_refs:
        return

    if all_records is None:
        all_records = []

    embedded_effects = []

    for effect_ref in effect_refs:
        effect_obj = resolve_effect_reference(
            effect_ref=effect_ref,
            all_records=all_records,
            id_index=id_index,
            source_record=new_data
        )

        if not isinstance(effect_obj, dict):
            continue

        effect_entry = build_effect_translation(effect_obj)
        if effect_entry:
            embedded_effects.append(effect_entry)

    if embedded_effects:
        entry["effects"] = embedded_effects
        transifex_dict["mapping"]["effects"] = {
            "path": "effects",
            "converter": "embeddedEffectsConverter"
        }

def load_manifest(manifest_url: str) -> dict:
    """Pobiera i zwraca manifest module.json."""
    response = requests.get(manifest_url, timeout=60)
    response.raise_for_status()

    module_meta = response.json()
    if not isinstance(module_meta, dict):
        raise ValueError(f"Manifest {manifest_url} nie zawiera obiektu JSON.")

    return module_meta


def find_module_root(extract_folder: pathlib.Path) -> pathlib.Path:
    """
    Zwraca katalog główny rozpakowanego modułu.

    Obsługuje archiwa, w których pliki modułu znajdują się bezpośrednio w
    katalogu docelowym, oraz archiwa z dodatkowym katalogiem nadrzędnym.
    """
    if (extract_folder / "packs").is_dir():
        return extract_folder

    manifest_files = list(extract_folder.rglob("module.json"))
    for manifest_file in manifest_files:
        candidate = manifest_file.parent
        if (candidate / "packs").is_dir():
            return candidate

    pack_directories = [
        path.parent
        for path in extract_folder.rglob("packs")
        if path.is_dir()
    ]
    if pack_directories:
        return pack_directories[0]

    return extract_folder


def download_and_extract_module(
        manifest_url: str,
        modules_folder: str = "pack_modules"
) -> tuple[dict, str]:
    """Pobiera moduł na podstawie module.json i rozpakowuje jego archiwum."""
    module_meta = load_manifest(manifest_url)

    module_id = (
        module_meta.get("id")
        or module_meta.get("name")
        or "unknown-module"
    )
    download_url = module_meta.get("download")

    if not isinstance(download_url, str) or not download_url.strip():
        raise ValueError(f"Manifest modułu {module_id} nie zawiera pola download.")

    modules_path = pathlib.Path(modules_folder)
    extract_folder = modules_path / module_id
    zip_filename = modules_path / f"{module_id}.zip"

    if extract_folder.exists():
        shutil.rmtree(extract_folder)

    extract_folder.mkdir(parents=True, exist_ok=True)
    zip_filename.parent.mkdir(parents=True, exist_ok=True)

    response = requests.get(download_url, timeout=120)
    response.raise_for_status()

    with open(zip_filename, "wb") as zip_file:
        zip_file.write(response.content)

    with zipfile.ZipFile(zip_filename, "r") as zip_file:
        zip_file.extractall(extract_folder)

    module_root = find_module_root(extract_folder)
    print(f"Pobrano i rozpakowano moduł: {module_id}")

    return module_meta, str(module_root)


def collect_pack_labels(module_meta: dict) -> dict:
    """Tworzy mapę nazwa packa -> etykieta z manifestu modułu."""
    labels = {}

    for pack in module_meta.get("packs", []):
        if not isinstance(pack, dict):
            continue

        pack_name = pack.get("name")
        pack_label = pack.get("label")

        if isinstance(pack_name, str) and isinstance(pack_label, str):
            labels[pack_name] = pack_label

    return labels


def write_pack_folders_translation(
        module_meta: dict,
        version: str,
        output_prefix: str
) -> None:
    """Tworzy plik tłumaczenia folderów grupujących packi modułu."""
    entries = {}

    for pack_folder in module_meta.get("packFolders", []):
        if not isinstance(pack_folder, dict):
            continue

        folder_name = (pack_folder.get("name") or "").strip()
        if folder_name:
            entries[folder_name] = folder_name

    if not entries:
        return

    output = {"entries": entries}
    output_path = pathlib.Path(version) / f"{output_prefix}._packs-folders.json"

    with open(output_path, "w", encoding="utf-8") as outfile:
        json.dump(output, outfile, ensure_ascii=False, indent=4)

    print(f"Zapisano foldery packów modułu: {output_path}")


def build_simple_global_id_index(folder: str) -> dict:
    """
    Buduje zwykły indeks _id -> rekord dla wszystkich plików JSON w folderze.

    Nie zmienia dotychczasowego formatu id_index i nie przechowuje list pod
    jednym _id. Indeks pliku aktualnie przetwarzanego ma później pierwszeństwo.
    """
    global_index = {}
    folder_path = pathlib.Path(folder)

    if not folder_path.is_dir():
        return global_index

    for file_path in folder_path.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as json_file:
                data = json.load(json_file)
        except (OSError, json.JSONDecodeError):
            continue

        if not isinstance(data, list):
            continue

        global_index.update(build_id_index(data))

    return global_index


def process_files(
        folders: str,
        version: str,
        output_prefix: str = "crucible",
        pack_labels: dict | None = None,
        extra_id_index: dict | None = None,
        include_folder_id_index: bool = False
) -> None:
    dict_key = []
    pack_labels = pack_labels or {}
    extra_id_index = extra_id_index or {}
    folder_id_index = (
        build_simple_global_id_index(folders)
        if include_folder_id_index
        else {}
    )

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

            id_index = dict(extra_id_index)
            id_index.update(folder_id_index)
            id_index.update(build_id_index(data))

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
            new_name = f'{version}/{output_prefix}.{pack_name}.json'
            print('Nowy plik:', new_name)
            print()

            folder_json_path = pathlib.Path(root) / f'{pack_name}_folders.json'
            label = pack_labels.get(pack_name, pack_name.title())

            if folder_json_path.is_file():
                transifex_dict = {
                    "label": label,
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
                    "label": label,
                    "folders": {},
                    "entries": {},
                    "mapping": {}
                }
            else:
                transifex_dict = {
                    "label": label,
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
                    populate_caption_entry(entry, new_data, id_index, transifex_dict, all_records=data)

                # zwykłe opisy
                if 'prototypeToken' not in keys and pack_name not in ['weapon']:
                    if 'caption' not in keys:
                        flag.append('description')

                    description = new_data.get("system", {}).get("description")
                    if description is None:
                        description = new_data.get("description", "")

                    if description:
                        entry["description"] = description

                    if pack_name != "equipment":
                        populate_embedded_effects_from_ids(entry, new_data, id_index, transifex_dict, all_records=data)

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
                        transifex_dict=transifex_dict,
                        all_records=data
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
    # crucible_url = "https://github.com/foundryvtt/crucible/releases/download/release-0.9.4/system.json"
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
    core_id_index = build_simple_global_id_index(folder)

    process_files(
        folder,
        version_crucible,
        output_prefix="crucible"
    )

    for manifest_url in ADDITIONAL_MODULE_MANIFESTS:
        try:
            module_meta, module_folder = download_and_extract_module(manifest_url)
        except Exception as error:
            print(f"Nie udało się pobrać modułu {manifest_url}: {error}")
            continue

        module_id = (
            module_meta.get("id")
            or module_meta.get("name")
            or pathlib.Path(module_folder).name
        )
        module_packs = os.path.join(module_folder, "packs")
        module_output = os.path.join(module_folder, "output")

        if not pathlib.Path(module_packs).is_dir():
            print(f"Moduł {module_id} nie ma folderu packs: {module_packs}")
            continue

        read_leveldb_to_json(module_packs, module_output)

        pack_labels = collect_pack_labels(module_meta)
        write_pack_folders_translation(
            module_meta=module_meta,
            version=version_crucible,
            output_prefix=module_id
        )

        process_files(
            folders=module_output,
            version=version_crucible,
            output_prefix=module_id,
            pack_labels=pack_labels,
            extra_id_index=core_id_index,
            include_folder_id_index=True
        )

    move_json_files(version_crucible)
    copy_en_json(version_crucible)
