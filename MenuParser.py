"""
V1.0
Programma per leggere il file memu esportato da Olympic Editor
L'editor esporta il dato fino alla pagina, ma manca la funzionalità chiamata.
Questo script cerca la funzionalità e costruisce un excel con la struttura del menu e funzionalità chiamate

Parametrare i repository da usare (in main)

"""
import os
import xml.etree.ElementTree as ET
from tkinter import Tk
from tkinter.filedialog import askopenfilename
import pandas as pd

DEBUG = False  # Set to True to enable detailed logging

def debug_log(message):
    """Helper function to print debug logs."""
    if DEBUG:
        print(message)

def select_input_file():
    """Opens a dialog window to select an input file."""
    Tk().withdraw()  # Hide the main Tkinter window
    file_path = askopenfilename(
        title="Select the input file",
        filetypes=[("Text Files", "*.txt"), ("All Files", "*.*")]
    )
    if not file_path:
        raise FileNotFoundError("No file selected.")
    return file_path

def search_functionality_recursively(node):
    """Recursively searches for <functionality> nodes and returns the 'name' attribute."""
    for child in node.iter("functionality"):  # Optimized to directly iterate
        if "name" in child.attrib:
            return child.attrib["name"]
    return None

def find_functionality(xml_directories, pageset_name, page_name):
    """
    Searches for a <functionality> node in XML repositories under the given page.
    """
    for xml_directory in xml_directories:
        file_path = os.path.join(xml_directory, f"{pageset_name}.page")
        debug_log(f"Checking file: {file_path}")

        if not os.path.exists(file_path):
            continue  # Skip non-existent files

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()

            # Search for <page> nodes with matching name attributes
            for page in root.findall(f".//page[@name='{page_name}']"):
                functionality = search_functionality_recursively(page)
                if functionality:
                    debug_log(f"Functionality found: {functionality}")
                    return functionality
        except ET.ParseError:
            debug_log(f"XML Parsing error in file: {file_path}")
    return None


def process_input_file(input_file, xml_directories):
    """
    Processes the input file, extracts information, and updates functionality.
    Returns a DataFrame with updated data.
    """
    with open(input_file, "r", encoding="ISO-8859-1") as f:
        lines = f.readlines()

    # Validazione dell'intestazione
    header = lines[0].strip().split("|")
    while len(header) < 4:
        header.append("")  # Completa con stringhe vuote
    if len(header) == 5:
        header[4] = "Functionality"

    updated_menu = []

    for idx, line in enumerate(lines[1:], start=2):  # start=2 per indicare la riga nel file
        if not line.strip():  # Salta righe vuote
            print(f"⚠️ Riga {idx} vuota, ignorata.")
            continue

        parts = line.strip().split("|")

        # Controlla se ci sono colonne sufficienti
        if len(parts) < 3:
            print(f"⚠️ Riga {idx} malformata: {line.strip()}, ignorata.")
            continue

        # Assicurati che ci siano almeno 4 colonne
        while len(parts) < 4:
            parts.append("")

        path, symbol, label, target = parts[:4]
        functionality = ""

        # Determinazione della funzionalità
        try:
            if "functionality:" in target:
                functionality = target.split("functionality:")[-1].strip()
            elif "page:" in target:
                pageset_name, page_name = target.split("page:")[-1].split(".", 1)
                functionality = find_functionality(xml_directories, pageset_name, page_name) or ""
            elif "action:" in target or "help:" in target:
                functionality = ""
            else:
                functionality = target.strip()
        except Exception as e:
            print(f"❌ Errore alla riga {idx}: {e}. Riga ignorata.")
            continue

        updated_menu.append({
            header[0]: path.strip(),
            header[1]: symbol.strip(),
            header[2]: label.strip(),
            header[3]: target.strip(),
            header[4]: functionality
        })

    if not updated_menu:
        raise ValueError("Nessun dato valido trovato nel file di input.")

    return pd.DataFrame(updated_menu)




def main():
    try:
        # Select input file
        input_file = select_input_file()
        input_dir = os.path.dirname(input_file)
        output_file = os.path.join(input_dir, os.path.splitext(os.path.basename(input_file))[0] + ".xlsx")

        # XML directories (ensure they exist)
        xml_directories = [
            r"C:\ERI\Progetti\BPS\NuoviMenu\std-module-olympicadmin-xml-TRK\ch\eri\client\page",
            r"C:\ERI\Progetti\BPS\NuoviMenu\std-module-PMS-xml-A03\ch\eri\client\page",
            r"C:\ERI\Progetti\BPS\NuoviMenu\std-core-xml-A03\ch\eri\client\page"
        ]
        xml_directories = [d for d in xml_directories if os.path.exists(d)]

        # Process input file
        df = process_input_file(input_file, xml_directories)

        # Save to Excel
        df.to_excel(output_file, index=False)
        print(f"✅ Excel file saved successfully at: {output_file}")
        os.startfile(output_file)

    except FileNotFoundError as e:
        print(e)

    except Exception as e:
        if isinstance(e, IndexError):  # Verifica se l'errore è di tipo IndexError
            print(
                "Sicuro di aver generato il file di menu comprendendo la colonna della lingua? "
                "(Il file di partenza dovrebbe avere 5 colonne, di cui l'ultima è vuota)"
            )
            print(f"Dettaglio dell'errore: {e}")
        else:
            print(f"Errore generico: {e}")


if __name__ == "__main__":
    main()
