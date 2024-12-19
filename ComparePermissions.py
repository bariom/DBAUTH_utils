import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi

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
app = Dash(__name__)
app.title = "Confronto Permission Domain"

# Layout iniziale
app.layout = html.Div([
    html.H3("Confronto Permission Domain", style={"textAlign": "center"}),
    html.Div([
        dcc.Dropdown(id='left-domains', multi=True, placeholder="Seleziona Domini (Sinistra)", style={"width": "45%"}),
        dcc.Dropdown(id='right-domains', multi=True, placeholder="Seleziona Domini (Destra)", style={"width": "45%"}),
        html.Button("Confronta", id="compare-button", n_clicks=0, style={"width": "8%"})
    ], style={"display": "flex", "justifyContent": "space-between", "marginBottom": "20px"}),
    dash_table.DataTable(
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
    ),
    html.Div(id="update-result", style={"marginTop": "20px", "color": "green"})
])

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
    [Output("comparison-table", "data"), Output("update-result", "children")],
    [Input("compare-button", "n_clicks"), Input("comparison-table", "active_cell")],
    [State("left-domains", "value"), State("right-domains", "value"), State("comparison-table", "data")]
)
def update_comparison_and_handle_action(compare_clicks, active_cell, left_domains, right_domains, table_data):
    ctx_trigger = ctx.triggered_id

    if ctx_trigger == "compare-button":
        if not left_domains or not right_domains:
            return [], "Seleziona i domini per il confronto."

        comparison = compare_permissions(left_domains, right_domains)

        if comparison.empty:
            return [], "Nessun dato disponibile per il confronto."

        return comparison.to_dict("records"), "Confronto completato."

    elif ctx_trigger == "comparison-table" and active_cell:
        if not table_data:
            return [], "Nessun dato disponibile per l'aggiornamento."

        col = active_cell.get("column_id")
        if col != "Action":
            return table_data, "Seleziona un'azione valida nella colonna Action."

        row = table_data[active_cell["row"]]

        if row["Action"] == "-":
            return table_data, "Nessuna azione disponibile per questo record."

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
            return updated_comparison.to_dict("records"), result

        except Exception as e:
            return table_data, f"Errore: {str(e)}"

    return dash.no_update, dash.no_update

if __name__ == "__main__":
    app.run_server(debug=True)
