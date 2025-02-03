import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc
from decouple import config

# =============================================================================
#  SEZIONE: Connessione e cache
# =============================================================================
DB_HOST = config("DB_HOST", cast=str)
DB_DATABASE = config("DB_DATABASE", cast=str)

# Cache in memoria: { (domini_ordinati) : DataFrame }
permission_cache = {}

def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        f'jdbc:as400://{config("DB_HOST")}/{config("DB_DATABASE")}',
        [config("DB_USER"), config("DB_PASSWORD")],
        config("DB_DRIVER_PATH")
    )
    return conn

# =============================================================================
#  SEZIONE: Funzioni per il recupero e la gestione dei permessi
# =============================================================================
def fetch_permission_domains(conn):
    query = "SELECT DMN_ID FROM DOMAIN"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

def fetch_permissions(conn, domains):
    """
    Recupera i permessi dai domini specificati.
    Se sono in cache, li restituisce direttamente.
    Altrimenti esegue la query, li salva in cache e poi li restituisce.
    """
    # Creiamo una chiave in base ai domini (ordinandoli per evitare duplicati)
    domains_key = tuple(sorted(domains))

    # Se la chiave è in cache, restituiamo i dati direttamente
    if domains_key in permission_cache:
        return permission_cache[domains_key]

    # Altrimenti, recuperiamo i dati dal DB
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
    df = pd.DataFrame(rows, columns=columns)

    # Salviamo in cache e restituiamo
    permission_cache[domains_key] = df
    return df

def update_or_insert_permission(conn, ext_id, name, action):
    """
    Aggiorna o inserisce un record nella tabella PERMISSION.
    Invalida l'intera cache dopo l'operazione.
    """
    class_name = 'ch.eri.core.security.TaskPermission'
    with conn.cursor() as cursor:
        query_check = "SELECT COUNT(*) FROM PERMISSION WHERE EXT_ID = ? AND NAME = ?"
        cursor.execute(query_check, [ext_id, name])
        exists = cursor.fetchone()[0] > 0
        if exists:
            query_update = "UPDATE PERMISSION SET ACTION = ? WHERE EXT_ID = ? AND NAME = ?"
            cursor.execute(query_update, [action, ext_id, name])
            conn.commit()
            result = f"Aggiornato: {name} in {ext_id} con ACTION = {action}"
        else:
            query_insert = "INSERT INTO PERMISSION (EXT_ID, CLASS, NAME, ACTION) VALUES (?, ?, ?, ?)"
            cursor.execute(query_insert, [ext_id, class_name, name, action])
            conn.commit()
            result = f"Inserito: {name} in {ext_id} con ACTION = {action}"

    # Invalido la cache perché i dati sono cambiati
    permission_cache.clear()
    return result

def delete_permission(conn, ext_id, name, action):
    """
    Elimina un record dalla tabella PERMISSION.
    Invalida l'intera cache dopo l'operazione.
    """
    with conn.cursor() as cursor:
        query_delete = "DELETE FROM PERMISSION WHERE EXT_ID = ? AND NAME = ? AND ACTION = ?"
        cursor.execute(query_delete, [ext_id, name, action])
        conn.commit()
    permission_cache.clear()
    return f"Eliminato: {name} con ACTION = {action} da {ext_id}"

def compare_permissions(left_domains, right_domains):
    """
    Confronta i permessi di più domini sorgente (left) con uno o più domini di destinazione (right).
    Restituisce un DataFrame con lo stato del confronto.
    """
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
    comparison["ACTION_left"] = (
        comparison["ACTION_left"]
        .astype(str)
        .replace("nan", "-")
    )
    comparison["ACTION_right"] = (
        comparison["ACTION_right"]
        .astype(str)
        .replace("nan", "-")
    )

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

    comparison["Action"] = comparison.apply(
        lambda row: "Aggiorna" if row["Status"] not in ["Comuni", "Unico a Destra"] else "-",
        axis=1
    )

    def delete_option(row):
        ext_id_right = row.get("EXT_ID_right")
        if ext_id_right and (str(ext_id_right).strip().lower() not in ["", "nan", "-"]):
            return "Elimina"
        return "-"


    comparison["Delete"] = comparison.apply(delete_option, axis=1)

    return comparison

# =============================================================================
#  SEZIONE: Layout dell'app Dash
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
        dbc.Col(
            dcc.Input(
                id="filter-name",
                placeholder="Filtra per NAME",
                type="text",
                value="",
                className="mb-3"
            ),
            width=4
        )
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Switch(id="toggle-notifications", label="Abilita notifiche", value=True, className="me-3")
        ], width=12, className="mb-3 d-flex justify-content-start align-items-center")
    ]),
    dbc.Row([
        dbc.Col(dash_table.DataTable(
            id="comparison-table",
            columns=[
                {"name": "Dominio Sorgente", "id": "EXT_ID_left", "editable": False},
                {"name": "NAME", "id": "NAME", "editable": False},
                {"name": "ACTION Sorgente", "id": "ACTION_left", "editable": False},
                {"name": "Dominio Target", "id": "EXT_ID_right", "editable": False},
                {"name": "ACTION Target", "id": "ACTION_right", "editable": True},
                {"name": "Status", "id": "Status", "editable": False},
                {"name": "Action", "id": "Action", "presentation": "markdown", "editable": False},
                {"name": "Delete", "id": "Delete", "presentation": "markdown", "editable": False}
            ],
            editable=False,  # solo le colonne con "editable=True" sono modificabili
            page_size=1000,
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
        dash.dependencies.Output('left-domains', 'options'),
        dash.dependencies.Output('right-domains', 'options'),
        dash.dependencies.Output("comparison-table", "data"),
        dash.dependencies.Output("notification-alert", "children"),
        dash.dependencies.Output("notification-alert", "is_open"),
        dash.dependencies.Output("toast-message", "children"),
        dash.dependencies.Output("toast-message", "is_open"),
        dash.dependencies.Output("old-data", "data"),
    ],
    [
        dash.dependencies.Input("compare-button", "n_clicks"),
        dash.dependencies.Input("filter-name", "value"),
        dash.dependencies.Input("comparison-table", "data_timestamp"),
        dash.dependencies.Input("comparison-table", "active_cell"),
    ],
    [
        dash.dependencies.State("left-domains", "value"),
        dash.dependencies.State("right-domains", "value"),
        dash.dependencies.State("toggle-notifications", "value"),
        dash.dependencies.State("old-data", "data"),
        dash.dependencies.State("comparison-table", "data")
    ]
)
def main_callback(compare_clicks, filter_name, data_timestamp, active_cell,
                  left_domains, right_domains,
                  notifications_enabled, old_data, table_data):

    # Se right_domains è una singola stringa, trasformala in lista
    if isinstance(right_domains, str):
        right_domains = [right_domains]

    comparison_data = dash.no_update
    alert_children = dash.no_update
    alert_is_open = False
    toast_message = dash.no_update
    toast_is_open = False
    new_old_data = dash.no_update

    domains_options = get_domains_options()
    triggered_id = ctx.triggered_id

    # ------------------ Modifica tramite editing in DataTable ------------------
    if triggered_id == "comparison-table" and data_timestamp:
        if not table_data or not old_data or not right_domains:
            return (domains_options, domains_options, dash.no_update,
                    dash.no_update, False, toast_message, toast_is_open,
                    dash.no_update)

        old_df = pd.DataFrame(old_data)
        new_df = pd.DataFrame(table_data)

        # Trova le righe modificate a livello di ACTION_right
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
                        # Se non è presente un EXT_ID_right valido, usiamo il target selezionato
                        if (not row["EXT_ID_right"]) or (str(row["EXT_ID_right"]).strip().lower() in ["", "nan", "-"]):
                            ext_id = right_domains[0]
                        else:
                            ext_id = row["EXT_ID_right"]

                        update_or_insert_permission(
                            conn,
                            ext_id=ext_id,
                            name=row["NAME"],
                            action=row["ACTION_right"]
                        )
                toast_message = "Modifica salvata con successo."
                updated_comparison = compare_permissions(left_domains, right_domains)
                if filter_name:
                    updated_comparison = updated_comparison[
                        updated_comparison["NAME"].str.contains(filter_name, case=False, na=False)
                    ]
                updated_comparison = updated_comparison.to_dict("records")
                new_old_data = updated_comparison
                return (domains_options, domains_options,
                        updated_comparison, dash.no_update, False,
                        toast_message, True,
                        new_old_data)
            except Exception as e:
                toast_message = f"Errore durante l'aggiornamento: {str(e)}"
                return (domains_options, domains_options,
                        dash.no_update, dash.no_update, False,
                        toast_message, True,
                        dash.no_update)

    # ------------------ Pulsante "Confronta" o modifica filtro ------------------
    if triggered_id in ["compare-button", "filter-name"]:
        if not left_domains or not right_domains:
            alert_children = "Seleziona i domini per il confronto."
            alert_is_open = notifications_enabled
            toast_message = alert_children
            toast_is_open = notifications_enabled
            return (domains_options, domains_options, [],
                    alert_children, alert_is_open,
                    toast_message, toast_is_open,
                    [])

        comparison = compare_permissions(left_domains, right_domains)
        if filter_name:
            comparison = comparison[comparison["NAME"].str.contains(filter_name, case=False, na=False)]
        if comparison.empty:
            alert_children = "Nessun dato disponibile per il confronto."
            alert_is_open = notifications_enabled
            toast_message = alert_children
            toast_is_open = notifications_enabled
            return (domains_options, domains_options, [],
                    alert_children, alert_is_open,
                    toast_message, toast_is_open,
                    [])

        comparison_data = comparison.to_dict("records")
        alert_children = "Confronto completato."
        alert_is_open = notifications_enabled
        toast_message = alert_children
        toast_is_open = notifications_enabled
        new_old_data = comparison_data

        return (domains_options, domains_options,
                comparison_data, alert_children, alert_is_open,
                toast_message, toast_is_open,
                new_old_data)

    # ------------------ Azioni in DataTable: Action/Delete ------------------
    if triggered_id == "comparison-table":
        if not table_data or not old_data or not left_domains or not right_domains:
            return (domains_options, domains_options, dash.no_update,
                    dash.no_update, dash.no_update,
                    toast_message, toast_is_open,
                    dash.no_update)

        if active_cell:
            col = active_cell.get("column_id")
            row_data = table_data[active_cell["row"]]

            # Eliminazione (Delete)
            if col == "Delete":
                if row_data["Delete"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (domains_options, domains_options,
                            table_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            old_data)
                try:
                    with connect_to_db() as conn:
                        result = delete_permission(
                            conn,
                            ext_id=row_data["EXT_ID_right"],
                            name=row_data["NAME"],
                            action=row_data["ACTION_right"]
                        )
                    updated = compare_permissions(left_domains, right_domains)
                    if filter_name:
                        updated = updated[updated["NAME"].str.contains(filter_name, case=False, na=False)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    toast_message = result
                    toast_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return (domains_options, domains_options,
                            comparison_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            new_old_data)
                except Exception as e:
                    alert_children = f"Errore durante l'eliminazione: {str(e)}"
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (domains_options, domains_options,
                            table_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            old_data)

            # Aggiornamento/Inserimento (Action)
            elif col == "Action":
                if row_data["Action"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (domains_options, domains_options,
                            table_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            old_data)
                try:
                    with connect_to_db() as conn:
                        result = update_or_insert_permission(
                            conn,
                            ext_id=right_domains[0],
                            name=row_data["NAME"],
                            action=row_data["ACTION_left"]
                        )
                    updated = compare_permissions(left_domains, right_domains)
                    if filter_name:
                        updated = updated[updated["NAME"].str.contains(filter_name, case=False, na=False)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    toast_message = result
                    toast_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return (domains_options, domains_options,
                            comparison_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            new_old_data)
                except Exception as e:
                    alert_children = f"Errore durante l'aggiornamento: {str(e)}"
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (domains_options, domains_options,
                            table_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            old_data)

    return (domains_options, domains_options,
            comparison_data, alert_children, alert_is_open,
            toast_message, toast_is_open,
            new_old_data)

# =============================================================================
#  SEZIONE: Avvio dell'app
# =============================================================================
if __name__ == "__main__":
    app.run_server(debug=False)
