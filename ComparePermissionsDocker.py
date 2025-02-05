import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx, no_update
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc
import os
import dash_auth

# =============================================================================
#  SECTION: Authentication
# =============================================================================
CRED_PAIRS = os.getenv("CRED_PAIRS")
pairs_dict = {}

for pair in CRED_PAIRS.split(","):
    username, password = pair.split(":")
    pairs_dict[username] = password

VALID_USRS_PAIRS = pairs_dict

# =============================================================================
#  SECTION: Database Connection
#    - connect_to_db: creates a connection to DB2/AS400 via JDBC driver
# =============================================================================

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_DATABASE = os.getenv("DB_DATABASE", "default_db")
DB_USER = os.getenv("DB_USER", "user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "password")

print(f"Connecting to {DB_HOST}/{DB_DATABASE} with user {DB_USER}")

# Simple in-memory cache for fetched permissions
permission_cache = {}

def connect_to_db():
    conn = jaydebeapi.connect(
        'com.ibm.as400.access.AS400JDBCDriver',
        f'jdbc:as400://{DB_HOST}/{DB_DATABASE}',
        [DB_USER, DB_PASSWORD],
        "/app/jt400.jar"  # Adjust the path to your .jar as needed
    )
    return conn

# =============================================================================
#  SECTION: Functions for Fetching and Managing Permissions
# =============================================================================
def fetch_permission_domains(conn):
    query = "SELECT DMN_ID FROM DOMAIN"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

def fetch_permissions(conn, domains):
    domains_key = tuple(sorted(domains))
    if domains_key in permission_cache:
        return permission_cache[domains_key]

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
    permission_cache[domains_key] = df
    return df

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
            result = f"Updated: {name} in {ext_id} with ACTION = {action}"
        else:
            query_insert = "INSERT INTO PERMISSION (EXT_ID, CLASS, NAME, ACTION) VALUES (?, ?, ?, ?)"
            cursor.execute(query_insert, [ext_id, class_name, name, action])
            conn.commit()
            result = f"Inserted: {name} in {ext_id} with ACTION = {action}"
    permission_cache.clear()
    return result

def delete_permission(conn, ext_id, name, action):
    with conn.cursor() as cursor:
        query_delete = "DELETE FROM PERMISSION WHERE EXT_ID = ? AND NAME = ? AND ACTION = ?"
        cursor.execute(query_delete, [ext_id, name, action])
        conn.commit()
    permission_cache.clear()
    return f"Deleted: {name} with ACTION = {action} from {ext_id}"

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
            return "Common"
        elif row["ACTION_left"] == "-":
            return "Unique on Right"
        elif row["ACTION_right"] == "-":
            return "Unique on Left"
        else:
            return "Different"

    comparison["Status"] = comparison.apply(classify_status, axis=1)
    comparison["Action"] = comparison.apply(lambda row: "Update" if row["Status"] not in ["Common", "Unique on Right"] else "-", axis=1)

    def delete_option(row):
        ext_id_right = row.get("EXT_ID_right")
        if ext_id_right and (str(ext_id_right).strip().lower() not in ["", "nan", "-"]):
            return "Delete"
        return "-"

    comparison["Delete"] = comparison.apply(delete_option, axis=1)
    return comparison

# =============================================================================
#  SECTION: Layout of the Dash App (with New Styling)
# =============================================================================
app = Dash(__name__, external_stylesheets=[dbc.themes.FLATLY])
auth = dash_auth.BasicAuth(app, VALID_USRS_PAIRS)
app.title = "Permission Domain Comparison"

header = dbc.NavbarSimple(
    children=[],
    brand="Permission Management - Domain Comparison",
    brand_href="#",
    color="primary",
    dark=True,
    className="mb-4"
)

connection_info = dbc.Card(
    dbc.CardBody(
        html.H6(f"Active connection on: {DB_HOST} | Database: {DB_DATABASE}", className="text-center text-white")
    ),
    color="info",
    className="mb-4"
)

domain_selectors = dbc.Card(
    dbc.CardBody([
        dbc.Row([
            dbc.Col(dcc.Dropdown(id='left-domains', multi=True,
                                 placeholder="Select Source Domains", className="mb-3"), width=6),
            dbc.Col(dcc.Dropdown(id='right-domains', multi=False,
                                 placeholder="Select Target Domain", className="mb-3"), width=6)
        ]),
        dbc.Row([
            dbc.Col(html.Button("Compare", id="compare-button", n_clicks=0,
                                className="btn btn-primary w-100"), width=12)
        ]),
        dbc.Row([
            dbc.Col(dcc.Input(id="filter-name", placeholder="Filter by NAME",
                              type="text", value="", className="mt-3"), width=12)
        ]),
        dbc.Row([
            dbc.Col(dbc.Switch(id="toggle-notifications", label="Enable notifications", value=True,
                               className="mt-3"), width=12)
        ])
    ]),
    className="mb-4"
)

data_table = dash_table.DataTable(
    id="comparison-table",
    columns=[
        {"name": "Source Domain", "id": "EXT_ID_left", "editable": False},
        {"name": "NAME", "id": "NAME", "editable": False},
        {"name": "Source ACTION", "id": "ACTION_left", "editable": False},
        {"name": "Target Domain", "id": "EXT_ID_right", "editable": False},
        {"name": "Target ACTION", "id": "ACTION_right", "editable": True},
        {"name": "Status", "id": "Status", "editable": False},
        {"name": "Action", "id": "Action", "presentation": "markdown", "editable": False},
        {"name": "Delete", "id": "Delete", "presentation": "markdown", "editable": False}
    ],
    editable=False,
    page_size=1000,
    style_table={"overflowX": "auto"},
    style_cell={"textAlign": "left", "padding": "5px"},
    style_header={
        "backgroundColor": "#007BFF",
        "fontWeight": "bold",
        "color": "white"
    },
    style_data_conditional=[
        {
            'if': {'filter_query': '{Status} = "Common"'},
            'backgroundColor': '#d4edda',
            'color': '#155724',
        },
        {
            'if': {'filter_query': '{Status} = "Unique on Left"'},
            'backgroundColor': '#f8d7da',
            'color': '#721c24',
        },
        {
            'if': {'filter_query': '{Status} = "Unique on Right"'},
            'backgroundColor': '#d1ecf1',
            'color': '#0c5460',
        },
        {
            'if': {'filter_query': '{Status} = "Different"'},
            'backgroundColor': '#fff3cd',
            'color': '#856404',
        },
    ]
)

notification_alert = dbc.Alert(id="notification-alert", dismissable=True, is_open=False, duration=5000)
toast_message = dbc.Toast(
    id="toast-message",
    header="Notification",
    icon="primary",
    is_open=False,
    dismissable=True,
    duration=5500,
    style={"position": "fixed", "top": 10, "right": 10, "width": 350}
)

app.layout = dbc.Container([
    header,
    connection_info,
    domain_selectors,
    dbc.Card(
        dbc.CardBody(data_table),
        className="mb-4"
    ),
    notification_alert,
    toast_message,
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
#  SECTION: Main Callback
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
        Input("filter-name", "value"),
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
def main_callback(compare_clicks, filter_name, data_timestamp, active_cell,
                  left_domains, right_domains,
                  notifications_enabled, old_data, table_data):

    if isinstance(right_domains, str):
        right_domains = [right_domains]

    comparison_data = no_update
    alert_children = no_update
    alert_is_open = False
    toast_msg = no_update
    toast_is_open = False
    new_old_data = no_update

    domains_options = get_domains_options()
    triggered_id = ctx.triggered_id

    # Editing in the DataTable
    if triggered_id == "comparison-table" and data_timestamp:
        if not table_data or not old_data or not right_domains:
            return (domains_options, domains_options, no_update,
                    no_update, False, toast_msg, toast_is_open, no_update)

        old_df = pd.DataFrame(old_data)
        new_df = pd.DataFrame(table_data)
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
                        ext_id = row["EXT_ID_right"] if row["EXT_ID_right"] and str(row["EXT_ID_right"]).strip().lower() not in ["", "nan", "-"] else right_domains[0]
                        update_or_insert_permission(conn, ext_id=ext_id, name=row["NAME"], action=row["ACTION_right"])
                toast_msg = "Change saved successfully."
                updated_comparison = compare_permissions(left_domains, right_domains)
                if filter_name:
                    updated_comparison = updated_comparison[updated_comparison["NAME"].str.contains(filter_name, case=False, na=False)]
                comparison_data = updated_comparison.to_dict("records")
                new_old_data = comparison_data
                return (domains_options, domains_options,
                        comparison_data, no_update, False,
                        toast_msg, True,
                        new_old_data)
            except Exception as e:
                toast_msg = f"Error during update: {str(e)}"
                return (domains_options, domains_options,
                        no_update, no_update, False,
                        toast_msg, True, no_update)

    # Compare button or filter change
    if triggered_id in ["compare-button", "filter-name"]:
        if not left_domains or not right_domains:
            alert_children = "Select domains for comparison."
            toast_msg = alert_children
            return (domains_options, domains_options, [],
                    alert_children, notifications_enabled,
                    toast_msg, notifications_enabled,
                    [])
        comparison = compare_permissions(left_domains, right_domains)
        if filter_name:
            comparison = comparison[comparison["NAME"].str.contains(filter_name, case=False, na=False)]
        if comparison.empty:
            alert_children = "No data available for comparison."
            toast_msg = alert_children
            return (domains_options, domains_options, [],
                    alert_children, notifications_enabled,
                    toast_msg, notifications_enabled,
                    [])
        comparison_data = comparison.to_dict("records")
        if len(comparison_data) > 1000:
            warning_message = html.Span([
                html.B("Warning: "),
                "Too many records. ",
                html.I("Modifications applied only on first page."),
                html.Br(),
                html.Span("PLEASE REFINE YOUR FILTER.", style={'color': 'red'})
            ])
            alert_children = warning_message
            toast_msg = warning_message

        else:
            toast_msg = html.Span([
                html.B("Compare table is ready: "),
                f"{len(comparison_data)} records found."
            ])
            alert_children = "Compare table is ready."

        new_old_data = comparison_data
        return (domains_options, domains_options,
                comparison_data, alert_children, notifications_enabled,
                toast_msg, notifications_enabled,
                new_old_data)

    # Actions in DataTable: Action/Delete
    if triggered_id == "comparison-table":
        if not table_data or not old_data or not left_domains or not right_domains:
            return (domains_options, domains_options, no_update,
                    no_update, no_update,
                    toast_msg, toast_is_open,
                    no_update)
        if active_cell:
            col = active_cell.get("column_id")
            row_data = table_data[active_cell["row"]]
            # Deletion
            if col == "Delete":
                if row_data["Delete"] == "-":
                    alert_children = "No action available for this record."
                    toast_msg = alert_children
                    return (domains_options, domains_options,
                            table_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            old_data)
                try:
                    with connect_to_db() as conn:
                        result = delete_permission(conn, ext_id=row_data["EXT_ID_right"], name=row_data["NAME"], action=row_data["ACTION_right"])
                    updated = compare_permissions(left_domains, right_domains)
                    if filter_name:
                        updated = updated[updated["NAME"].str.contains(filter_name, case=False, na=False)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    toast_msg = result
                    new_old_data = comparison_data
                    return (domains_options, domains_options,
                            comparison_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            new_old_data)
                except Exception as e:
                    alert_children = f"Error during deletion: {str(e)}"
                    toast_msg = alert_children
                    return (domains_options, domains_options,
                            table_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            old_data)
            # Update/Insert (Action)
            elif col == "Action":
                if row_data["Action"] == "-":
                    alert_children = "No action available for this record."
                    toast_msg = alert_children
                    return (domains_options, domains_options,
                            table_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            old_data)
                try:
                    with connect_to_db() as conn:
                        result = update_or_insert_permission(conn, ext_id=right_domains[0], name=row_data["NAME"], action=row_data["ACTION_left"])
                    updated = compare_permissions(left_domains, right_domains)
                    if filter_name:
                        updated = updated[updated["NAME"].str.contains(filter_name, case=False, na=False)]
                    comparison_data = updated.to_dict("records")
                    alert_children = result
                    toast_msg = result
                    new_old_data = comparison_data
                    return (domains_options, domains_options,
                            comparison_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            new_old_data)
                except Exception as e:
                    alert_children = f"Error during update: {str(e)}"
                    toast_msg = alert_children
                    return (domains_options, domains_options,
                            table_data, alert_children, notifications_enabled,
                            toast_msg, notifications_enabled,
                            old_data)

    return (domains_options, domains_options,
            comparison_data, alert_children, alert_is_open,
            toast_msg, toast_is_open,
            new_old_data)

# =============================================================================
#  SECTION: Run the App
# =============================================================================
if __name__ == "__main__":
    app.run_server(host='0.0.0.0', port=8050, debug=False)
