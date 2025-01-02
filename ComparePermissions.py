import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc

def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        'jdbc:as400://p10lug/BPSAUTHNEW',  # Modifica con i tuoi dettagli
        ['nextlux', 'next'],               # Credenziali
        'C:/temp/jt400.jar'                # Path al driver JDBC
    )
    return conn

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
    query = "SELECT DISTINCT EXT_ID FROM PERMISSION"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

def update_or_insert_permission(conn, ext_id, name, action):
    class_name=f'ch.eri.core.security.TaskPermission'
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
            query_insert = f"INSERT INTO PERMISSION (EXT_ID, CLASS, NAME, ACTION) VALUES (?, ?, ?, ?)"
            cursor.execute(query_insert, [ext_id, class_name, name, action])
            conn.commit()
            return f"Inserito: {name} in {ext_id} con ACTION = {action}"

def delete_permission(conn, ext_id, name, action):
    with conn.cursor() as cursor:
        query_delete = "DELETE FROM PERMISSION WHERE EXT_ID = ? AND NAME = ? AND ACTION = ?"
        cursor.execute(query_delete, [ext_id, name, action])
        conn.commit()
        return f"Eliminato: {name} con ACTION = {action} da {ext_id}"

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
    comparison["Action"] = comparison.apply(
        lambda row: "Aggiorna" if row["Status"] not in ["Comuni", "Unico a Destra"] else "-",
        axis=1
    )
    comparison["Delete"] = comparison.apply(
        lambda row: "Elimina" if row["Status"] in ["Comuni", "Unico a Destra"] else "-",
        axis=1
    )

    return comparison

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Confronto Permission Domain"

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H3("Confronto Permission Domain", className="text-center my-3"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Dropdown(id='left-domains', multi=True, placeholder="Seleziona Domini (Sinistra)", className="mb-3"), width=5),
        dbc.Col(dcc.Dropdown(id='right-domains', multi=True, placeholder="Seleziona Domini (Destra)", className="mb-3"), width=5),
        dbc.Col(html.Button("Confronta", id="compare-button", n_clicks=0, className="btn btn-primary"), width=2)
    ], justify="between"),
    dbc.Row([
        dbc.Col([
            dbc.Switch(id="toggle-notifications", label="Abilita notifiche", value=True, className="me-3"),
            dbc.Button("Filtra", id="open-filter-button", size="sm", className="btn-secondary")
        ], width=12, className="mb-3 d-flex justify-content-start align-items-center")
    ]),
    dbc.Row([
        dbc.Col(dash_table.DataTable(
            id="comparison-table",
            columns=[
                {"name": "EXT_ID_left", "id": "EXT_ID_left"},
                {"name": "NAME", "id": "NAME"},
                {"name": "ACTION_left", "id": "ACTION_left"},
                {"name": "EXT_ID_right", "id": "EXT_ID_right"},
                {"name": "ACTION_right", "id": "ACTION_right", "editable": True},
                {"name": "Status", "id": "Status"},
                {"name": "Action", "id": "Action", "presentation": "markdown"},
                {"name": "Delete", "id": "Delete", "presentation": "markdown"}
            ],
            editable=True,
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
    dbc.Alert(id="notification-alert", dismissable=True, is_open=False, duration=4000),
    dbc.Offcanvas(
        id="filter-status",
        title="Filtra per Status",
        is_open=False,
        placement="start",
        style={"width": "300px"},
        children=[
            dbc.Checklist(
                id="status-filter",
                options=[
                    {"label": "Comuni", "value": "Comuni"},
                    {"label": "Unico a Sinistra", "value": "Unico a Sinistra"},
                    {"label": "Unico a Destra", "value": "Unico a Destra"},
                    {"label": "Differenti", "value": "Differenti"}
                ],
                value=[],
                inline=True
            ),
            html.Button("Applica Filtro", id="apply-filter", className="btn btn-primary mt-3")
        ]
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

@app.callback(
    [Output('left-domains', 'options'),
     Output('right-domains', 'options'),
     Output("comparison-table", "data"),
     Output("notification-alert", "children"),
     Output("notification-alert", "is_open"),
     Output("old-data", "data"),
     Output("filter-status", "is_open")],
    [Input("compare-button", "n_clicks"),
     Input("apply-filter", "n_clicks"),
     Input("comparison-table", "data_timestamp"),
     Input("comparison-table", "active_cell"),
     Input("open-filter-button", "n_clicks")],
    [State("left-domains", "value"),
     State("right-domains", "value"),
     State("toggle-notifications", "value"),
     State("status-filter", "value"),
     State("old-data", "data"),
     State("comparison-table", "data")]
)
def main_callback(compare_clicks, apply_filter_clicks, data_timestamp, active_cell,
                  open_filter_clicks, left_domains, right_domains,
                  notifications_enabled, status_filter, old_data, table_data):

    # Valori di default per l'output
    comparison_data = dash.no_update
    alert_children = dash.no_update
    alert_is_open = False
    new_old_data = dash.no_update
    filter_is_open = dash.no_update

    # Opzioni domini
    domains_options = get_domains_options()

    # Determina il trigger
    triggered_id = ctx.triggered_id

    # Toggle pannello filtri
    if triggered_id == "open-filter-button":
        # Se open_filter_clicks è stato premuto, togglo lo stato
        if open_filter_clicks:
            if filter_is_open is dash.no_update:
                # Se non c'è uno stato precedente, assumo chiuso
                filter_is_open = True
            else:
                filter_is_open = not filter_is_open
        else:
            filter_is_open = True  # Se non cliccato prima, apri

    # Se è stato premuto "Confronta"
    if triggered_id == "compare-button":
        if not left_domains or not right_domains:
            alert_children = "Seleziona i domini per il confronto."
            alert_is_open = notifications_enabled
            # Ritorno vuoto perché non posso confrontare
            return domains_options, domains_options, [], alert_children, alert_is_open, [], filter_is_open
        comparison = compare_permissions(left_domains, right_domains)
        if comparison.empty:
            alert_children = "Nessun dato disponibile per il confronto."
            alert_is_open = notifications_enabled
            return domains_options, domains_options, [], alert_children, alert_is_open, [], filter_is_open

        if status_filter:
            comparison = comparison[comparison["Status"].isin(status_filter)]

        comparison_data = comparison.to_dict("records")
        alert_children = "Confronto completato."
        alert_is_open = notifications_enabled
        new_old_data = comparison.to_dict("records")

        return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open

    # Se è stato premuto "Applica Filtro"
    if triggered_id == "apply-filter":
        if not old_data:
            # Non c'è niente da filtrare
            alert_children = "Nessun dato disponibile per il confronto."
            alert_is_open = notifications_enabled
            return domains_options, domains_options, [], alert_children, alert_is_open, [], filter_is_open

        df = pd.DataFrame(old_data)
        if status_filter:
            df = df[df["Status"].isin(status_filter)]

        comparison_data = df.to_dict("records")
        alert_children = "Filtro applicato."
        alert_is_open = notifications_enabled
        new_old_data = df.to_dict("records")

        return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open

    # Gestione modifica in tabella (ACTION_right) o click su Action/Delete
    if triggered_id == "comparison-table":
        # Se non ci sono dati per la tabella o old_data, non faccio nulla
        if not table_data or not old_data or not left_domains or not right_domains:
            return domains_options, domains_options, dash.no_update, dash.no_update, dash.no_update, dash.no_update, filter_is_open

        # Se ho cliccato su una cella (Action o Delete)
        if active_cell:
            col = active_cell.get("column_id")
            row_data = table_data[active_cell["row"]]

            if col == "Delete":
                if row_data["Delete"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    return domains_options, domains_options, table_data, alert_children, alert_is_open, old_data, filter_is_open
                try:
                    with connect_to_db() as conn:
                        result = delete_permission(
                            conn,
                            ext_id=row_data["EXT_ID_right"],
                            name=row_data["NAME"],
                            action=row_data["ACTION_right"]
                        )
                    updated = compare_permissions(left_domains, right_domains)
                    if status_filter:
                        updated = updated[updated["Status"].isin(status_filter)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open
                except Exception as e:
                    alert_children = f"Errore durante l'eliminazione: {str(e)}"
                    alert_is_open = notifications_enabled
                    return domains_options, domains_options, table_data, alert_children, alert_is_open, old_data, filter_is_open

            elif col == "Action":
                if row_data["Action"] == "-":
                    alert_children = "Nessuna azione disponibile per questo record."
                    alert_is_open = notifications_enabled
                    return domains_options, domains_options, table_data, alert_children, alert_is_open, old_data, filter_is_open
                try:
                    with connect_to_db() as conn:
                        if row_data["Status"] == "Unico a Sinistra":
                            # Non esiste a destra, inserisco nel primo dominio a destra
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
                    if status_filter:
                        updated = updated[updated["Status"].isin(status_filter)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    alert_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open
                except Exception as e:
                    alert_children = f"Errore durante l'aggiornamento: {str(e)}"
                    alert_is_open = notifications_enabled
                    return domains_options, domains_options, table_data, alert_children, alert_is_open, old_data, filter_is_open

        # Se è un evento di data_timestamp (modifica nella cella ACTION_right)
        if data_timestamp:
            old_df = pd.DataFrame(old_data)
            new_df = pd.DataFrame(table_data)

            merged = old_df.merge(new_df, on=["EXT_ID_left","NAME","EXT_ID_right","Status","Action","Delete","ACTION_left"], suffixes=("_old",""))
            changed_rows = merged[merged["ACTION_right_old"] != merged["ACTION_right"]]

            if not changed_rows.empty:
                # Aggiorno il DB per ogni riga cambiata
                try:
                    with connect_to_db() as conn:
                        for _, row in changed_rows.iterrows():
                            ext_id_dest = row["EXT_ID_right"] or row["EXT_ID_left"]
                            update_or_insert_permission(
                                conn,
                                ext_id=ext_id_dest,
                                name=row["NAME"],
                                action=row["ACTION_right"]
                            )

                    # Ricarico i dati dal DB
                    updated = compare_permissions(left_domains, right_domains)
                    if status_filter:
                        updated = updated[updated["Status"].isin(status_filter)]
                    comparison_data = updated.to_dict("records")
                    alert_children = "Modifica salvata."
                    alert_is_open = notifications_enabled
                    new_old_data = comparison_data
                    return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open

                except Exception as e:
                    alert_children = f"Errore durante l'aggiornamento: {str(e)}"
                    alert_is_open = notifications_enabled
                    return domains_options, domains_options, table_data, alert_children, alert_is_open, old_data, filter_is_open

    # Se nessun trigger specifico ha modificato lo stato, ritorno i valori di default
    return domains_options, domains_options, comparison_data, alert_children, alert_is_open, new_old_data, filter_is_open

if __name__ == "__main__":
    app.run_server(debug=True)
