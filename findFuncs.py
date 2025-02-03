#!/usr/bin/env python3
import os
import xml.etree.ElementTree as ET
import pyperclip

# Parametri configurabili
base_dir = "c:/temp/repositories"  # percorso di partenza
db_name = "BPSAUTHNEW"             # nome del database

queries = []

# Scorri ricorsivamente la directory
for dirpath, dirnames, filenames in os.walk(base_dir):
    for filename in filenames:
        if filename.endswith(".func"):
            file_path = os.path.join(dirpath, filename)
            print(f"Elaboro file: {file_path}")
            try:
                tree = ET.parse(file_path)
                root = tree.getroot()
                print(f"Tag radice: {root.tag}")
                set_name = root.attrib.get("name", "")
                if not set_name:
                    print("Attenzione: attributo 'name' non trovato nel tag radice.")
                    continue
                # Cerca tutti gli elementi <functionality>
                functionalities = root.findall("functionality")
                if not functionalities:
                    print("Nessun elemento <functionality> trovato.")
                for func in functionalities:
                    func_name = func.attrib.get("name", "")
                    if func_name:
                        full_name = f"{set_name}.{func_name}"
                        query = (
                            f"INSERT INTO {db_name}.PERMISSION VALUES('___GLOBAL___',"
                            f"'ch.eri.core.security.TaskPermission','{full_name}','a');"
                        )
                        queries.append(query)
                        print(f"Generata query: {query}")
                    else:
                        print("Attenzione: attributo 'name' non trovato in <functionality>.")
            except Exception as e:
                print(f"Errore nell'elaborazione di {file_path}: {e}")

result = "\n".join(queries)
print("\nRisultato finale:\n" + result)

# Copia il risultato negli appunti
pyperclip.copy(result)
print("Risultato copiato negli appunti!")
