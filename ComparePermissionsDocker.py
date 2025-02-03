import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc
import os
#from decouple import config

# =============================================================================
#  SEZIONE: Connessione al database
#    - connect_to_db: crea una connessione a DB2/AS400 tramite il driver JDBC
# =============================================================================
# =============================================================================
#  SEZIONE: Connessione al database
# =============================================================================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_DATABASE = os.getenv("DB_DATABASE", "default_db")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")
#DB_DRIVER_PATH_DOCKER = os.getenv("DB_DRIVER_PATH_DOCKER", "/path/to/db2jcc.jar")

print(f"Connettendo a {DB_HOST}/{DB_DATABASE} con l'utente {DB_USER}")

def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        f'jdbc:as400://{DB_HOST}/{DB_DATABASE}',
        [DB_USER, DB_PASSWORD],
        "/app/jt400.jar"
    )
    return conn

# =============================================================================
#  SEZIONE: Funzioni per il recupero e la gestione dei permessi
# =============================================================================
def fetch_permissions(conn, domains):
    placeholder = ', '.join(['?' for _ in domains])
    query = f"""
    SELECT EXT_ID, NAME, ACTION
    FROM PERMISSION
    WHERE EXT_ID IN ({placeholder})
    """
    with conn.cursor() as cursor:
        cursor.execute(query, domains)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
    return pd.DataFrame(rows, columns=columns)

def fetch_permission_domains(conn):
    query = "SELECT DMN_ID FROM DOMAIN"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

def update_or_insert_permission(conn, ext_id, name, action):
    class_name = 'ch.eri.core.security.TaskPermission'
    with conn.cursor() as cursor:
        query_check = "SELECT COUNT(*) FROM PERMISSION WHERE EXT_ID = ? AND NAME = ?"
        cursor.execute(query_check, [ext_id, name])
        exists = cursor.fetchone()[0] > 0
        if exists:
            query_update = "UPDATE PERMISSION SET ACTION = ? WHERE EXT_ID = ? AND NAME = ?"
            cursor.execute(query_update, [action, ext_id, name])
            conn.commit()
            return f"Aggiornato: {name} in {ext_id} con ACTION = {action}"
        else:
            query_insert = "INSERT INTO PERMISSION (EXT_ID, CLASS, NAME, ACTION) VALUES (?, ?, ?, ?)"
            cursor.execute(query_insert, [ext_id, class_name, name, action])
            conn.commit()
            return f"Inserito: {name} in {ext_id} con ACTION = {action}"

def delete_permission(conn, ext_id, name, action):
    with conn.cursor() as cursor:
        query_delete = "DELETE FROM PERMISSION WHERE EXT_ID = ? AND NAME = ? AND ACTION = ?"
        cursor.execute(query_delete, [ext_id, name, action])
        conn.commit()
        return f"Eliminato: {name} con ACTION = {action} da {ext_id}"


# =============================================================================
#  SEZIONE: Confronto dei permessi
# =============================================================================
def compare_permissions(left_domains, right_domains):
    with connect_to_db() as conn:
        left_permissions = fetch_permissions(conn, left_domains)
        right_permissions = fetch_permissions(conn, right_domains)

    comparison = pd.merge(
        left_permissions,
        right_permissions,
        on="NAME",
        how="outer",
        suffixes=("_left", "_right"),
        indicator=True
    )

    comparison["ACTION_left"] = comparison["ACTION_left"].astype(str).replace("nan", "-")
    comparison["ACTION_right"] = comparison["ACTION_right"].astype(str).replace("nan", "-")

    def classify_status(row):
        if row["ACTION_left"] == row["ACTION_right"]:
            return "Comuni"
        elif row["ACTION_left"] == "-":
            return "Unico a Destra"
        elif row["ACTION_right"] == "-":
            return "Unico a Sinistra"
        else:
            return "Differenti"

    comparison["Status"] = comparison.apply(classify_status, axis=1)

    # Colonne per azioni
    comparison["Action"] = comparison.apply(
        lambda row: "Aggiorna" if row["Status"] not in ["Comuni", "Unico a Destra"] else "-",
        axis=1
    )
    comparison["Delete"] = comparison.apply(
        lambda row: "Elimina" if row["Status"] in ["Comuni", "Unico a Destra"] else "-",
        axis=1
    )

    return comparison


# =============================================================================
#  SEZIONE: Inizializzazione dell'app Dash con Bootstrap
# =============================================================================
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Confronto Permission Domain"

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H2("Gestione Permessi - Confronto Domains", className="text-center my-3"), width=12)
    ]),
    dbc.Row([
        dbc.Col(html.H5(f"🔗 Connessione attiva su: {DB_HOST} | Database: {DB_DATABASE}",
                        className="text-center text-muted mb-3"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Dropdown(id='left-domains', multi=True,
                             placeholder="Seleziona Domini Sorgente", className="mb-3"),
                width=5),
        dbc.Col(dcc.Dropdown(id='right-domains', multi=False,
                             placeholder="Seleziona Dominio Target", className="mb-3"),
                width=5),
        dbc.Col(html.Button("Confronta", id="compare-button", n_clicks=0,
                            className="btn btn-primary"), width=2)
    ], justify="between"),

    dbc.Row([
        dbc.Col([
            dbc.Switch(id="toggle-notifications", label="Abilita notifiche", value=True, className="me-3")
        ], width=12, className="mb-3 d-flex justify-content-start align-items-center")
    ]),

    # Tabella con filtro nativo
    dbc.Row([
        dbc.Col(dash_table.DataTable(
            id="comparison-table",
            columns=[
                {"name": "Dominio Sorgente", "id": "EXT_ID_left"},
                {"name": "NAME", "id": "NAME"},
                {"name": "ACTION Sorgente", "id": "ACTION_left"},
                {"name": "Dominio Target", "id": "EXT_ID_right"},
                {"name": "ACTION Target", "id": "ACTION_right", "editable": True},
                {"name": "Status", "id": "Status"},
                {"name": "Action", "id": "Action", "presentation": "markdown"},
                {"name": "Delete", "id": "Delete", "presentation": "markdown"}
            ],
            editable=True,
            page_size=1000,
            filter_action="native",  # <--- Filtro nativo
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left"},
            style_data_conditional=[
                {
                    'if': {'filter_query': '{Status} = "Comuni"'},
                    'backgroundColor': '#d4edda',
                    'color': '#155724',
                },
                {
                    'if': {'filter_query': '{Status} = "Unico a Sinistra"'},
                    'backgroundColor': '#f8d7da',
                    'color': '#721c24',
                },
                {
                    'if': {'filter_query': '{Status} = "Unico a Destra"'},
                    'backgroundColor': '#d1ecf1',
                    'color': '#0c5460',
                },
                {
                    'if': {'filter_query': '{Status} = "Differenti"'},
                    'backgroundColor': '#fff3cd',
                    'color': '#856404',
                },
            ]
        ), width=12)
    ]),

    dbc.Alert(id="notification-alert", dismissable=True, is_open=False, duration=5000),
    dbc.Toast(
        id="toast-message",
        header="Notifica",
        icon="primary",
        is_open=False,
        dismissable=True,
        duration=4000,
        style={"position": "fixed", "top": 10, "right": 10, "width": 350}
    ),

    dcc.Store(id="old-data", storage_type='memory')
], fluid=True)


# =============================================================================
#  SEZIONE: Funzione di supporto per popolamento dropdown
# =============================================================================
def get_domains_options():
    try:
        with connect_to_db() as conn:
            domains = fetch_permission_domains(conn)
        return [{"label": domain, "value": domain} for domain in domains]
    except Exception:
        return []


# =============================================================================
#  SEZIONE: Callback principale
# =============================================================================
@app.callback(
    [
        Output('left-domains', 'options'),
        Output('right-domains', 'options'),
        Output("comparison-table", "data"),
        Output("notification-alert", "children"),
        Output("notification-alert", "is_open"),
        Output("toast-message", "children"),
        Output("toast-message", "is_open"),
        Output("old-data", "data"),
    ],
    [
        Input("compare-button", "n_clicks"),
        Input("comparison-table", "data_timestamp"),
        Input("comparison-table", "active_cell"),
    ],
    [
        State("left-domains", "value"),
        State("right-domains", "value"),
        State("toggle-notifications", "value"),
        State("old-data", "data"),
        State("comparison-table", "data")
    ]
)
def main_callback(compare_clicks, data_timestamp, active_cell,
                  left_domains, right_domains,
                  notifications_enabled, old_data, table_data):

    # Se right_domains è una stringa singola, la trasformiamo in lista
    if isinstance(right_domains, str):
        right_domains = [right_domains]

    comparison_data = dash.no_update
    alert_children = dash.no_update
    alert_is_open = False
    toast_message = dash.no_update
    toast_is_open = False
    new_old_data = dash.no_update

    # Recupera le opzioni per i dropdown
    domains_options = get_domains_options()

    triggered_id = ctx.triggered_id

    # ------------------ Modifica ACTION_right in tabella -------------------
    if triggered_id == "comparison-table" and data_timestamp:
        if not table_data or not old_data or not right_domains:
            return (
                domains_options, domains_options, dash.no_update,
                dash.no_update, False, toast_message, toast_is_open,
                dash.no_update
            )

        old_df = pd.DataFrame(old_data)
        new_df = pd.DataFrame(table_data)

        # Righe modificate
        changes = old_df.merge(
            new_df,
            on=["EXT_ID_left", "NAME", "EXT_ID_right", "Status", "Action", "Delete", "ACTION_left"],
            suffixes=("_old", "")
        )
        modified_rows = changes[changes["ACTION_right_old"] != changes["ACTION_right"]]

        if not modified_rows.empty:
            try:
                with connect_to_db() as conn:
                    for _, row in modified_rows.iterrows():
                        ext_id = row["EXT_ID_right"] or row["EXT_ID_left"]
                        update_or_insert_permission(
                            conn,
                            ext_id=ext_id,
                            name=row["NAME"],
                            action=row["ACTION_right"]
                        )

                toast_message = "Modifica salvata con successo."
                updated_comparison = compare_permissions(left_domains, right_domains).to_dict("records")
                new_old_data = updated_comparison
                return (
                    domains_options, domains_options,
                    updated_comparison, dash.no_update, False,
                    toast_message, True,
                    new_old_data
                )
            except Exception as e:
                toast_message = f"Errore durante l'aggiornamento: {str(e)}"
                return (
                    domains_options, domains_options,
                    dash.no_update, dash.no_update, False,
                    toast_message, True,
                    dash.no_update
                )

    # ------------------ Pulsante "Confronta" ------------------
    if triggered_id == "compare-button":
        if not left_domains or not right_domains:
            alert_children = "Seleziona i domini per il confronto."
            alert_is_open = notifications_enabled
            toast_message = alert_children
            toast_is_open = notifications_enabled
            return (
                domains_options, domains_options, [],
                alert_children, alert_is_open,
                toast_message, toast_is_open,
                []
            )

        comparison = compare_permissions(left_domains, right_domains)
        if comparison.empty:
            alert_children = "Nessun dato disponibile per il confronto."
            alert_is_open = notifications_enabled
            toast_message = alert_children
            toast_is_open = notifications_enabled
            return (
                domains_options, domains_options, [],
                alert_children, alert_is_open,
                toast_message, toast_is_open,
                []
            )

        comparison_data = comparison.to_dict("records")
        alert_children = "Confronto completato."
        alert_is_open = notifications_enabled
        toast_message = alert_children
        toast_is_open = notifications_enabled
        new_old_data = comparison_data

        return (
            domains_options, domains_options,
            comparison_data, alert_children, alert_is_open,
            toast_message, toast_is_open,
            new_old_data
        )

    # ------------------ Azioni in tabella: Action/Delete ------------------
    if triggered_id == "comparison-table":
        if not table_data or not old_data or not left_domains or not right_domains:
            return (
                domains_options, domains_options, dash.no_update,
                dash.no_update, dash.no_update,
                toast_message, toast_is_open,
                dash.no_update
            )

        if active_cell:
            col = active_cell.get("column_id")
            row_data = table_data[active_cell["row"]]

            # 1. Eliminazione permesso (colonna "Delete")
            if col == "Delete":
                if row_data["Delete"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (
                        domains_options, domains_options,
                        table_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        old_data
                    )
                try:
                    with connect_to_db() as conn:
                        result = delete_permission(
                            conn,
                            ext_id=row_data["EXT_ID_right"],
                            name=row_data["NAME"],
                            action=row_data["ACTION_right"]
                        )
                    updated = compare_permissions(left_domains, right_domains)
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    toast_message = result
                    toast_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return (
                        domains_options, domains_options,
                        comparison_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        new_old_data
                    )
                except Exception as e:
                    alert_children = f"Errore durante l'eliminazione: {str(e)}"
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (
                        domains_options, domains_options,
                        table_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        old_data
                    )

            # 2. Aggiornamento o Inserimento (colonna "Action")
            elif col == "Action":
                if row_data["Action"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (
                        domains_options, domains_options,
                        table_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        old_data
                    )
                try:
                    with connect_to_db() as conn:
                        if row_data["Status"] == "Unico a Sinistra":
                            result = update_or_insert_permission(
                                conn,
                                ext_id=right_domains[0],
                                name=row_data["NAME"],
                                action=row_data["ACTION_left"]
                            )
                        else:
                            ext_id_dest = row_data["EXT_ID_right"] or row_data["EXT_ID_left"]
                            result = update_or_insert_permission(
                                conn,
                                ext_id=ext_id_dest,
                                name=row_data["NAME"],
                                action=row_data["ACTION_left"]
                            )

                    updated = compare_permissions(left_domains, right_domains)
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    toast_message = result
                    toast_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return (
                        domains_options, domains_options,
                        comparison_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        new_old_data
                    )
                except Exception as e:
                    alert_children = f"Errore durante l'aggiornamento: {str(e)}"
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (
                        domains_options, domains_options,
                        table_data, alert_children, alert_is_open,
                        toast_message, toast_is_open,
                        old_data
                    )

    # -------------- Ritorno di default --------------
    return (
        domains_options, domains_options,
        comparison_data, alert_children, alert_is_open,
        toast_message, toast_is_open,
        new_old_data
    )


# =============================================================================
#  SEZIONE: Avvio dell'app
# =============================================================================
if __name__ == "__main__":
    app.run_server(host='0.0.0.0', port=8050, debug=False)
