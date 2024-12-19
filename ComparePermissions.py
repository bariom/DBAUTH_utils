import streamlit as st
import pandas as pd
import jaydebeapi

# Funzione per connettersi al database
def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        'jdbc:as400://p10lug/bpsauthnew',  # Sostituisci con i dettagli del tuo server e database
        ['nextlux', 'next'],  # Sostituisci con le credenziali
        'c:/temp/jt400.jar'  # Path al driver JDBC
    )
    return conn

# Funzione per recuperare i permessi
def fetch_permissions(conn, domains):
    placeholder = ', '.join(['?' for _ in domains])
    query = f"""
    SELECT EXT_ID, NAME, ACTION
    FROM PERMISSION
    WHERE EXT_ID IN ({placeholder})
    """
    cursor = conn.cursor()
    cursor.execute(query, domains)
    rows = cursor.fetchall()
    columns = [desc[0] for desc in cursor.description]
    return pd.DataFrame(rows, columns=columns)

# Funzione per recuperare i domini di permessi
def fetch_permission_domains(conn):
    query = """
    SELECT DISTINCT EXT_ID
    FROM PERMISSION
    """
    cursor = conn.cursor()
    cursor.execute(query)
    rows = cursor.fetchall()
    return [row[0] for row in rows]

# Streamlit UI
st.set_page_config(layout="wide")
st.markdown("<h3 style='text-align: center; margin-bottom: 10px;'>Confronto Permission Domain</h3>", unsafe_allow_html=True)

# Barra laterale
with st.sidebar:
    st.markdown("<h4 style='margin-bottom: 5px;'>Configurazione</h4>", unsafe_allow_html=True)
    # Connettiti al database
    try:
        conn = connect_to_db()
        st.success("Connessione al database riuscita!", icon="✅")
    except Exception as e:
        st.error(f"Errore di connessione al database: {e}")
        st.stop()

    # Recupera i permission domains
    try:
        permission_domains = fetch_permission_domains(conn)
    except Exception as e:
        st.error(f"Errore durante il recupero dei permission domain: {e}")
        conn.close()
        st.stop()

    # Selezione dei permission domain
    left_domains = st.multiselect("Domini (Sinistra)", permission_domains, key="left")
    right_domains = st.multiselect("Domini (Destra)", permission_domains, key="right")

# Contenuto principale
if left_domains and right_domains:
    try:
        # Recupera i permessi per i domini selezionati
        left_permissions = fetch_permissions(conn, left_domains)
        right_permissions = fetch_permissions(conn, right_domains)

        # Unisci i dati per il confronto
        comparison = pd.merge(
            left_permissions,
            right_permissions,
            on="NAME",
            how="outer",
            suffixes=("_left", "_right"),
            indicator=True
        )

        # Classifica i risultati
        def classify_status(row):
            if row["_merge"] == "both" and row["ACTION_left"] != row["ACTION_right"]:
                return "Differenti"
            return {
                "both": "Comuni",
                "left_only": "Unico a Sinistra",
                "right_only": "Unico a Destra"
            }.get(row["_merge"], "Unknown")

        comparison["Status"] = comparison.apply(classify_status, axis=1)

        # Aggiungi colori basati sullo stato
        def highlight_row(row):
            if row["Status"] == "Comuni":
                return ['background-color: #d4edda'] * len(row)  # Verde chiaro
            elif row["Status"] == "Unico a Sinistra":
                return ['background-color: #f8d7da'] * len(row)  # Rosso chiaro
            elif row["Status"] == "Unico a Destra":
                return ['background-color: #d1ecf1'] * len(row)  # Blu chiaro
            elif row["Status"] == "Differenti":
                return ['background-color: #fff3cd'] * len(row)  # Giallo chiaro
            else:
                return [''] * len(row)

        # Filtra i risultati per status
        status_filter = st.multiselect("Filtra Status", ["Comuni", "Unico a Sinistra", "Unico a Destra", "Differenti"], default=["Comuni", "Unico a Sinistra", "Unico a Destra", "Differenti"], key="status")
        filtered_comparison = comparison[comparison["Status"].isin(status_filter)]

        # Visualizza la tabella con stile
        st.dataframe(filtered_comparison[["NAME", "ACTION_left", "ACTION_right", "Status"]]
                     .style.apply(highlight_row, axis=1), use_container_width=True, height=668)
    except Exception as e:
        st.error(f"Errore durante il recupero o il confronto dei dati: {e}")

# Chiudi la connessione al database
conn.close()
