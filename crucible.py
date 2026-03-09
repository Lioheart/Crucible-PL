import json
import os
import pathlib
import shutil
import zipfile
from urllib.request import urlretrieve

import plyvel
import requests


def create_version_directory(version):
    if os.path.exists(version):
        print(f'Katalog {version} istnieje, pomijam tworzenie.')
        return False
    else:
        print(f'Tworzę katalog {version}')
        os.makedirs(version)
        return True

def download_and_extract_zip(zip_url, zip_filename, extract_folder_zip):
    response = requests.get(zip_url)

    with open(zip_filename, 'wb') as zip_file:
        zip_file.write(response.content)

    with zipfile.ZipFile(zip_filename, 'r') as zip_file:
        zip_file.extractall(extract_folder_zip)
        print('Pobrano i rozpakowano plik .zip')

def read_leveldb_to_json(leveldb_path, output_json_path):
    def list_subfolders(directory):
        try:
            # Lista folderów w katalogu
            subfolders = [f.name for f in os.scandir(directory) if f.is_dir()]

            # Zwróć nazwy folderów, jeśli istnieją
            if subfolders:
                return subfolders
            else:
                return "Brak folderów w katalogu"
        except Exception as error:
            raise f"Wystąpił błąd list_subfolders: {error}"

    folders_list = list_subfolders(leveldb_path.replace('\\','/'))
    for sub_folders in folders_list:
        output_path = rf'{output_json_path}\{sub_folders}.json'
        output_folder = rf'{output_json_path.split("\\")[0]}\packs\{sub_folders}'.replace('\\','/')

        # Ensure the output folder exists
        output_file = output_path.replace('\\','/')
        output_dir = output_json_path.replace('\\','/')
        os.makedirs(output_dir, exist_ok=True)

        try:
            # Otwórz bazę danych LevelDB
            db = plyvel.DB(output_folder, create_if_missing=False)

            # Stwórz pustą listę na dane
            data = []

            # Iteruj przez wszystkie klucze i wartości w bazie danych
            for key, value in db:
                try:
                    value_str = value.decode('utf-8', errors='ignore')
                    # Jeśli wartość to poprawny JSON, konwertujemy ją do obiektu
                    try:
                        value_data = json.loads(value_str)
                    except json.JSONDecodeError:
                        value_data = {"name": value_str}  # Jeśli to nie JSON, utwórz obiekt z kluczem "name"

                    # Dodaj tylko wartość do listy
                    data.append(value_data)
                except Exception as e:
                    print(f"Błąd dekodowania dla klucza {key}: {e}")
                    continue

            # Zapisz dane do pliku JSON jako listę
            with open(output_file, 'w', encoding='utf-8') as json_file:
                json.dump(data, json_file, ensure_ascii=False, indent=4)

            print(f"Dane zostały zapisane do {output_file}")
        except Exception as e:
            raise f"Wystąpił błąd read_leveldb_to_json: {e}"
        finally:
            db.close()

def sort_entries(input_dict):
    if "entries" in input_dict:
        input_dict["entries"] = dict(sorted(input_dict["entries"].items()))

    for key, value in input_dict.items():
        if isinstance(value, dict):
            input_dict[key] = sort_entries(value)

    return input_dict


def remove_empty_keys(data_dict):
    """
    Usuwa puste klucze w słowniku i usuwa 'name', jeśli 'pages' jest pusty.
    Proces powtarza się aż do wyeliminowania wszystkich pustych kluczy.

    :param data_dict: Słownik wejściowy
    :return: Oczyszczony słownik
    """
    def clean_dict_once(d):
        """
        Jednokrotne przejście przez słownik w celu usunięcia pustych kluczy.
        """
        cleaned = {}
        for key, value in d.items():
            if isinstance(value, dict):  # Jeśli wartość to słownik, oczyść go rekurencyjnie
                value = clean_dict_once(value)
            if key == "pages" and not value:  # Jeśli "pages" jest pusty
                continue  # Usuń klucz "pages"
            if key == "name" and "pages" in d and not d["pages"]:
                continue  # Usuń klucz "name", jeśli "pages" jest pusty
            if value not in (None, {}, [], ""):  # Usuń inne puste wartości
                cleaned[key] = value
        return cleaned

    previous = None
    current = data_dict

    # Iteruj, aż słownik przestanie się zmieniać
    while previous != current:
        previous = current
        current = clean_dict_once(previous)

    return current


def process_files(folders, version):
    dict_key = []
    for root, dirs, files in os.walk(folders):
        for file in files:
            if file.endswith(".json"):
                file_path = os.path.join(root, file)
                print('Oryginalny plik:', file)
                with open(file_path, 'r', encoding='utf-8') as json_file:
                    data = json.load(json_file)

                try:
                    compendium = data[0]
                except (KeyError, AttributeError) as e:
                    compendium = data

                keys = compendium.keys()
                print('Klucze pliku JSON:', list(keys))

                new_name = fr'{version}/crucible.{file.split('.')[0]}.json'
                # try:
                #     name = compendium['_stats']['systemId'] # Nazwa pobierana z plików, na razie nie używane
                # except KeyError:
                #     print('BŁĄD!!!')
                print('Nowy plik:', new_name)
                print()

                if pathlib.Path(f'{root}/{file.split(".")[0]}_folders.json').is_file():
                    transifex_dict = {
                        "label": file.split('.')[0].title(),
                        "folders": {},
                        "entries": {},
                        "mapping": {}
                    }

                    with open(f'{root}/{file.split(".")[0]}_folders.json', 'r', encoding='utf-8') as json_file:
                        data_folder = json.load(json_file)

                    for new_data in data_folder:
                        name = new_data["name"].strip()
                        transifex_dict["folders"].update({name: name})

                elif 'color' in keys or 'folder' in keys:
                    transifex_dict = {
                        "label": file.split('.')[0].title(),
                        "folders": {},
                        "entries": {},
                        "mapping": {}
                    }
                else:
                    transifex_dict = {
                        "label": file.split('.')[0].title(),
                        "entries": {},
                        "mapping": {}
                    }

                flag = []
                for new_data in data:
                    name = new_data["name"].strip()

                    # Dla folderów - DZIAŁA
                    if 'folder' in new_data.keys() and 'color' in new_data.keys():
                        transifex_dict["folders"].update({name: name})
                        continue

                    # Dla Kompendium z nazwami
                    elif 'name' in keys:
                        transifex_dict["entries"].update({name: {}})
                        transifex_dict["entries"][name].update({"name": name})

                    # Dla Przygód
                    if 'caption' in keys:
                        transifex_dict["entries"][name].update({"caption": new_data["caption"]})
                        transifex_dict["entries"][name].update({"description": new_data["description"]})

                        # Foldery
                        if 'folders' in keys:
                            transifex_dict["entries"][name].update({"folders": {}})
                            for folder in new_data["folders"]:
                                if 'folders' in keys:
                                    transifex_dict["entries"][name]["folders"].update({folder['name']: folder['name']})

                        # Dzienniki
                        if 'journal' in keys:
                            transifex_dict["entries"][name.strip()].update({"journals": {}})
                            for journal in new_data["journal"]:
                                transifex_dict["entries"][name]["journals"].update({journal["name"]: {}})
                                transifex_dict["entries"][name]["journals"][journal["name"].strip()].update(
                                    {"name": journal["name"]})
                                transifex_dict["entries"][name]["journals"][journal["name"]].update({"pages": {}})
                                for pages in journal["pages"]:
                                    transifex_dict["entries"][name]["journals"][journal["name"]]["pages"].update(
                                        {pages["name"].strip(): {}})
                                    transifex_dict["entries"][name]["journals"][journal["name"]]["pages"][
                                        pages["name"].strip()].update({"name": pages["name"].strip()})
                                    transifex_dict["entries"][name]["journals"][journal["name"]]["pages"][
                                        pages["name"].strip()].update(
                                        {"text": " ".join(pages["text"].get("content", "").split())})
                        # Sceny
                        if 'scenes' in keys:
                            transifex_dict["entries"][name].update({"scenes": {}})
                            for scene in new_data["scenes"]:
                                transifex_dict["entries"][name]["scenes"].update({scene["name"]: {}})
                                transifex_dict["entries"][name]["scenes"][scene["name"]].update({"name": scene["name"]})
                                transifex_dict["entries"][name]["scenes"][scene["name"]].update({"notes": {}})
                                for note in scene["notes"]:
                                    transifex_dict["entries"][name]["scenes"][scene["name"]]["notes"].update(
                                        {note["text"]: note["text"]})

                        # Makra
                        if 'macros' in keys:
                            transifex_dict["entries"][name].update({"macros": {}})
                            for macro in new_data["macros"]:
                                transifex_dict["entries"][name]["macros"].update({macro["name"]: {}})
                                transifex_dict["entries"][name]["macros"][macro["name"]].update(
                                    {"name": macro["name"]})

                        # Tabele
                        if 'tables' in keys:
                            transifex_dict["entries"][name].update({"tables": {}})
                            for table in new_data["tables"]:
                                transifex_dict["entries"][name]["tables"].update({table["name"]: {}})
                                transifex_dict["entries"][name]["tables"][table["name"]].update(
                                    {"name": table["name"]})
                                transifex_dict["entries"][name]["tables"][table["name"]].update(
                                    {"description": table["description"]})
                                transifex_dict["entries"][name]["tables"][table["name"]].update({"results": {}})
                                for result in table['results']:
                                    result_name = f'{result["range"][0]}-{result["range"][1]}'
                                    transifex_dict["entries"][name]["tables"][table["name"]]['results'].update(
                                        {result_name: result['text']})

                        # Przedmioty
                        if 'items' in keys:
                            transifex_dict["entries"][name].update({"items": {}})
                            for item in new_data["items"]:
                                transifex_dict["entries"][name]["items"].update({item["name"]: {}})
                                transifex_dict["entries"][name]["items"][item["name"]].update(
                                    {"name": item["name"]})

                        # Playlisty
                        if 'playlists' in keys:
                            transifex_dict["entries"][name].update({"playlists": {}})
                            for playlist in new_data["playlists"]:
                                transifex_dict["entries"][name]["playlists"].update({playlist["name"]: {}})
                                transifex_dict["entries"][name]["playlists"][playlist["name"]].update(
                                    {"name": playlist["name"]})
                                transifex_dict["entries"][name]["playlists"][playlist["name"]].update(
                                    {"description": playlist.get("description")})
                                transifex_dict["entries"][name]["playlists"][playlist["name"]].update(
                                    {"sounds": {}})
                                for sound in playlist["sounds"]:
                                    transifex_dict["entries"][name]["playlists"][playlist["name"]][
                                        "sounds"].update(
                                        {sound["name"]: {}})
                                    transifex_dict["entries"][name]["playlists"][playlist["name"]]["sounds"][
                                        sound["name"]].update({"name": sound["name"]})
                                    transifex_dict["entries"][name]["playlists"][playlist["name"]]["sounds"][
                                        sound["name"]].update({"description": sound.get("description")})

                        # Aktorzy
                        if 'actors' in keys:
                            transifex_dict["entries"][name].update({"actors": {}})
                            for actor in new_data["actors"]:
                                transifex_dict["entries"][name]["actors"].update({actor["name"]: {}})
                                transifex_dict["entries"][name]["actors"][actor["name"]].update({"name": actor["name"]})
                                transifex_dict["entries"][name]["actors"][actor["name"]].update({"tokenName": {}})
                                transifex_dict["entries"][name]["actors"][actor["name"]]["tokenName"].update({"name": actor["prototypeToken"]["name"]})

                    # Dla Kompendium z opisami
                    if 'prototypeToken' not in keys and file.split('.')[0] not in ['rules', 'weapon']:
                        if 'caption' not in keys:
                            flag.append('description')
                        try:
                            transifex_dict["entries"][name].update({"description": new_data["system"]["description"]})
                        except KeyError:
                            transifex_dict["entries"][name].update({"description": new_data["description"]})

                    if 'description' in flag and 'caption' not in keys:
                        transifex_dict['mapping'].update(
                            {
                                "description": "system.description"
                            }
                        )

                    # Dla Makr
                    if 'command' in keys:
                        transifex_dict["entries"].update({name: {}})
                        transifex_dict["entries"][name].update({"name": name})

                    # Dla talentów
                    if file in ['talent.json', 'adversary-talents.json', 'spell.json']:
                        transifex_dict["mapping"].update({"actions": {}})
                        transifex_dict["mapping"]["actions"].update({"path": "system.actions"})
                        transifex_dict["mapping"]["actions"].update({"converter": "actions_converter"})
                        transifex_dict["entries"][name].update({"actions": {}})
                        if new_data.get("system", {}).get("actions"):
                            for action in new_data["system"]["actions"]:
                                action["name"] = action.get("name") or name
                                transifex_dict["entries"][name]["actions"].update({action["name"]: {}})
                                transifex_dict["entries"][name]["actions"][action["name"]].update({"name": action["name"]})
                                transifex_dict["entries"][name]["actions"][action["name"]].update({"condition": action.get("condition") or ""})
                                transifex_dict["entries"][name]["actions"][action["name"]].update({"description": action.get("description") or ""})
                                if action.get("effects"):
                                    transifex_dict["entries"][name]["actions"][action["name"]].update({"effects": []})
                                    transifex_dict["entries"][name]["actions"][action["name"]]["effects"].append({})
                                    for effect in action.get("effects"):
                                        effect["name"] = effect.get("name") or action["name"]
                                        transifex_dict["entries"][name]["actions"][action["name"]]["effects"][0].update({"name": effect["name"]})


                    # Dla Dzienników
                    if file.split('.')[0] == 'rules':
                        transifex_dict["entries"].update({name: {}})
                        transifex_dict["entries"][name].update({"name": name})
                        transifex_dict["entries"][name].update({"pages": {}})
                        try: # Obejscie na umiejętności Crucible #TODO: do przetłumaczenia
                            for result in new_data['pages']:
                                for pages in data:
                                    try:
                                        if result == pages['_id']:
                                            transifex_dict["entries"][name]['pages'].update({pages['name']: {}})
                                            transifex_dict["entries"][name]['pages'][pages['name']].update({"name": pages['name']})
                                            transifex_dict["entries"][name]['pages'][pages['name']].update(
                                                {"text": pages['text']['content']})
                                    except KeyError:
                                        pass
                        except KeyError:
                            pass

                    # elif 'permission' in keys:
                    #     transifex_dict["entries"].update({name: {}})
                    #     transifex_dict["entries"][name].update({"name": name})
                    #     transifex_dict["entries"][name].update({"pages": {}})
                    #     transifex_dict["entries"][name]['pages'].update({name: {}})
                    #     transifex_dict["entries"][name]['pages'][name].update({"name": name})
                    #     try:
                    #         transifex_dict["entries"][name]['pages'][name].update({"text": new_data['content']})
                    #     except KeyError:
                    #         del transifex_dict["entries"][name]['pages']
                    #         try:
                    #             transifex_dict["entries"][name].update({"description": new_data['data']['description']['value']})
                    #         except KeyError:
                    #             transifex_dict["entries"][name].update(
                    #                 {"description": new_data['system']['description']['value']})
                    #
                    # # Dla tabel
                    # elif 'displayRoll' in keys:
                    #     transifex_dict["entries"].update({name: {}})
                    #     transifex_dict["entries"][name].update({"name": name})
                    #     transifex_dict["entries"][name].update({"description": new_data['description']})
                    #     transifex_dict["entries"][name].update({"results": {}})
                    #     for result in new_data['results']:
                    #         result_name = f'{result["range"][0]}-{result["range"][1]}'
                    #         transifex_dict["entries"][name]['results'].update({result_name: result['text']})

                transifex_dict = remove_empty_keys(transifex_dict)
                transifex_dict = sort_entries(transifex_dict)

                with open(new_name, "w", encoding='utf-8') as outfile:
                    json.dump(transifex_dict, outfile, ensure_ascii=False, indent=4)

                dict_key.append(f'{compendium.keys()}')

def copy_en_json(version_crucible):
    source_file = os.path.join("pack_crucible", "lang", "en.json")
    destination_dir = version_crucible
    destination_file = os.path.join(destination_dir, "en.json")

    # Upewnij się, że katalog docelowy istnieje
    os.makedirs(destination_dir, exist_ok=True)

    # Skopiuj plik
    shutil.copy2(source_file, destination_file)
    print(f"Skopiowano: {source_file} -> {destination_file}")

def move_json_files(version_crucible):
    base_path = pathlib.Path(version_crucible).resolve()
    target_path = base_path / "compendium"

    # 1. Utwórz folder docelowy, jeśli nie istnieje
    target_path.mkdir(parents=True, exist_ok=True)

    # 2. Szukanie tylko plików z rozszerzeniem .json
    # glob("*.json") wybiera tylko pliki JSON w bieżącym folderze
    json_files = list(base_path.glob("*.json"))

    if not json_files:
        print("Nie znaleziono żadnych plików .json do przeniesienia.")
        return

    for file_path in json_files:
        try:
            # Przenoszenie pliku
            shutil.move(str(file_path), str(target_path / file_path.name))
            print(f"Pomyślnie przeniesiono: {file_path.name}")
        except Exception as e:
            print(f"Błąd przy pliku {file_path.name}: {e}")

if __name__ == '__main__':
    # Crucible
    # Ścieżka do pliku Crucible

    crucible_url = "https://github.com/foundryvtt/crucible/releases/latest/download/system.json"

    path_crucible, headers_crucible = urlretrieve(crucible_url, 'crucible.json')
    version_crucible = 'crucible_' + json.loads(open('crucible.json', 'r', encoding='utf-8').read())["version"]
    zip_crucible_filename = "system.zip"
    zip_crucible = json.loads(open('crucible.json', 'r', encoding='utf-8').read())["download"]
    extract_folder = 'pack_crucible'
    print()
    print("*** Wersja Crucible: ", version_crucible, " ***")

    if create_version_directory(version_crucible):
        download_and_extract_zip(zip_crucible, zip_crucible_filename, extract_folder)
    else:
        with zipfile.ZipFile(zip_crucible_filename, 'r') as zip_ref:
            zip_ref.extractall(extract_folder)

    # Konwersja z db na json
    read_leveldb_to_json(fr'{extract_folder}\packs', fr'{extract_folder}\output')
    print()

    # === === === === === === === === === === === === === === === === === === === === === === === === === === === ===

    # Utworzenie plików do tłumaczenia
    folder = r'pack_crucible/output'
    process_files(folder, version_crucible)
    move_json_files(version_crucible)
    copy_en_json(version_crucible)