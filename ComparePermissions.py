import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc

# Funzione per connettersi al database
def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        'jdbc:as400://p10lug/BPSAUTHNEW',  # Sostituisci con i dettagli del tuo server e database
        ['nextlux', 'next'],  # Sostituisci con le credenziali
        'C:/temp/jt400.jar'  # Path al driver JDBC
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
    with conn.cursor() as cursor:
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
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

# Funzione per aggiornare o inserire un record
def update_or_insert_permission(conn, ext_id, name, action):
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
            query_insert = "INSERT INTO PERMISSION (EXT_ID, NAME, ACTION) VALUES (?, ?, ?)"
            cursor.execute(query_insert, [ext_id, name, action])
            conn.commit()
            return f"Inserito: {name} in {ext_id} con ACTION = {action}"

# App Dash
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Confronto Permission Domain"

# Layout iniziale
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
                {"name": "ACTION_right", "id": "ACTION_right"},
                {"name": "Status", "id": "Status"},
                {"name": "Action", "id": "Action", "presentation": "markdown"}
            ],
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
    dbc.Offcanvas(
        id="update-result",
        title="Notifica",
        is_open=False,
        placement="end",
        style={"width": "300px"}
    ),
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
    )
], fluid=True)

# Callback per popolare i dropdown
def get_domains_options():
    try:
        with connect_to_db() as conn:
            domains = fetch_permission_domains(conn)
        return [{"label": domain, "value": domain} for domain in domains]
    except Exception as e:
        return []

@app.callback(
    [Output('left-domains', 'options'), Output('right-domains', 'options')],
    [Input('compare-button', 'n_clicks')]
)
def populate_domains(_):
    options = get_domains_options()
    return options, options

# Callback per aprire il pannello filtri
@app.callback(
    Output("filter-status", "is_open"),
    [Input("open-filter-button", "n_clicks")],
    [State("filter-status", "is_open")]
)
def toggle_filter_panel(n_clicks, is_open):
    if n_clicks:
        return not is_open
    return is_open

# Funzione per il confronto
def compare_permissions(left_domains, right_domains):
    try:
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
            lambda row: f"Aggiorna" if row["Status"] not in ["Comuni", "Unico a Destra"] else "-",
            axis=1
        )
        return comparison
    except Exception as e:
        return pd.DataFrame()

@app.callback(
    [Output("comparison-table", "data"), Output("update-result", "children"), Output("update-result", "is_open")],
    [Input("compare-button", "n_clicks"), Input("comparison-table", "active_cell"), Input("apply-filter", "n_clicks")],
    [State("left-domains", "value"), State("right-domains", "value"), State("comparison-table", "data"), State("toggle-notifications", "value"), State("status-filter", "value")]
)
def update_comparison_and_handle_action(compare_clicks, active_cell, apply_filter_clicks, left_domains, right_domains, table_data, notifications_enabled, status_filter):
    ctx_trigger = ctx.triggered_id

    if ctx_trigger == "compare-button":
        if not left_domains or not right_domains:
            return [], "Seleziona i domini per il confronto.", notifications_enabled

        comparison = compare_permissions(left_domains, right_domains)

        if comparison.empty:
            return [], "Nessun dato disponibile per il confronto.", notifications_enabled

        if status_filter:
            comparison = comparison[comparison["Status"].isin(status_filter)]

        return comparison.to_dict("records"), "Confronto completato.", notifications_enabled

    elif ctx_trigger == "comparison-table" and active_cell:
        if not table_data:
            return [], "Nessun dato disponibile per l'aggiornamento.", notifications_enabled

        col = active_cell.get("column_id")
        if col != "Action":
            return table_data, "Seleziona un'azione valida nella colonna Action.", notifications_enabled

        row = table_data[active_cell["row"]]

        if row["Action"] == "-":
            return table_data, "Nessuna azione disponibile per questo record.", notifications_enabled

        try:
            with connect_to_db() as conn:
                if row["Status"] == "Unico a Sinistra":
                    result = update_or_insert_permission(
                        conn,
                        ext_id=right_domains[0],
                        name=row["NAME"],
                        action=row["ACTION_left"]
                    )
                else:
                    result = update_or_insert_permission(
                        conn,
                        ext_id=row["EXT_ID_right"] or row["EXT_ID_left"],
                        name=row["NAME"],
                        action=row["ACTION_left"]
                    )

            updated_comparison = compare_permissions(left_domains, right_domains)

            if status_filter:
                updated_comparison = updated_comparison[updated_comparison["Status"].isin(status_filter)]

            return updated_comparison.to_dict("records"), result, notifications_enabled

        except Exception as e:
            return table_data, f"Errore: {str(e)}", notifications_enabled

    elif ctx_trigger == "apply-filter":
        if not table_data:
            return [], "Nessun dato disponibile per il confronto.", notifications_enabled

        filtered_data = pd.DataFrame(table_data)
        if status_filter:
            filtered_data = filtered_data[filtered_data["Status"].isin(status_filter)]

        return filtered_data.to_dict("records"), "Filtro applicato.", notifications_enabled

    return dash.no_update, dash.no_update, dash.no_update

if __name__ == "__main__":
    app.run_server(debug=True)
