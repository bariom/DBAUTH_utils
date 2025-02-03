import dash
from dash import Dash, dash_table, html, dcc, Input, Output, State, ctx
import pandas as pd
import jaydebeapi
import dash_bootstrap_components as dbc
import os

# =============================================================================
#  SECTION: Database connection
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
#  SECTION: Functions for retrieving and managing permissions
# =============================================================================
def fetch_permission_domains(conn):
    query = "SELECT DMN_ID FROM DOMAIN"
    with conn.cursor() as cursor:
        cursor.execute(query)
        rows = cursor.fetchall()
    return [row[0] for row in rows]

def fetch_permissions(conn, domains):
    """
    Fetches permissions from the specified domains.
    If they are in the in-memory cache, returns them directly.
    Otherwise, executes the query, stores them in cache, then returns them.
    """
    # Create a key based on the domains (sorted to avoid duplicates)
    domains_key = tuple(sorted(domains))

    # If the key is in cache, return the data directly
    if domains_key in permission_cache:
        return permission_cache[domains_key]

    # Otherwise, fetch from the DB
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

    # Store in cache and return
    permission_cache[domains_key] = df
    return df

def update_or_insert_permission(conn, ext_id, name, action):
    """
    Updates or inserts a record in the PERMISSION table.
    Invalidates the cache after the operation.
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
            result = f"Updated: {name} in {ext_id} with ACTION = {action}"
        else:
            query_insert = "INSERT INTO PERMISSION (EXT_ID, CLASS, NAME, ACTION) VALUES (?, ?, ?, ?)"
            cursor.execute(query_insert, [ext_id, class_name, name, action])
            conn.commit()
            result = f"Inserted: {name} in {ext_id} with ACTION = {action}"

    # Invalidate the cache since data changed
    permission_cache.clear()
    return result

def delete_permission(conn, ext_id, name, action):
    """
    Deletes a record from the PERMISSION table.
    Invalidates the cache after the operation.
    """
    with conn.cursor() as cursor:
        query_delete = "DELETE FROM PERMISSION WHERE EXT_ID = ? AND NAME = ? AND ACTION = ?"
        cursor.execute(query_delete, [ext_id, name, action])
        conn.commit()
    permission_cache.clear()
    return f"Deleted: {name} with ACTION = {action} from {ext_id}"

def compare_permissions(left_domains, right_domains):
    """
    Compares permissions from multiple source domains (left) with one or more target domains (right).
    Returns a DataFrame with the comparison status.
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
            return "Common"
        elif row["ACTION_left"] == "-":
            return "Only in Right"
        elif row["ACTION_right"] == "-":
            return "Only in Left"
        else:
            return "Different"

    comparison["Status"] = comparison.apply(classify_status, axis=1)

    # If they differ or are "Common", show the "Update" action to edit target
    comparison["Action"] = comparison.apply(
        lambda row: "Update" if row["Status"] not in ["Common", "Only in Right"] else "-",
        axis=1
    )

    # Always "Delete" if EXT_ID_right is valid in the target domain
    def delete_option(row):
        ext_id_right = row.get("EXT_ID_right")
        if ext_id_right and (str(ext_id_right).strip().lower() not in ["", "nan", "-"]):
            return "Delete"
        return "-"

    comparison["Delete"] = comparison.apply(delete_option, axis=1)

    return comparison

# =============================================================================
#  SECTION: Dash app layout
# =============================================================================
app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
app.title = "Permissions Management - Domain Comparison"

app.layout = dbc.Container([
    dbc.Row([
        dbc.Col(html.H2("Permissions Management - Domain Comparison", className="text-center my-3"), width=12)
    ]),
    dbc.Row([
        dbc.Col(html.H5(f"🔗 Active connection to: {DB_HOST} | Database: {DB_DATABASE}",
                        className="text-center text-muted mb-3"), width=12)
    ]),
    dbc.Row([
        dbc.Col(dcc.Dropdown(
                    id='left-domains',
                    multi=True,
                    placeholder="Select Source Domains",
                    className="mb-3"
                ),
                width=5),
        dbc.Col(dcc.Dropdown(
                    id='right-domains',
                    multi=False,
                    placeholder="Select Target Domain",
                    className="mb-3"
                ),
                width=5),
        dbc.Col(html.Button(
                    "Compare",
                    id="compare-button",
                    n_clicks=0,
                    className="btn btn-primary"
                ),
                width=2)
    ], justify="between"),
    dbc.Row([
        dbc.Col(
            dcc.Input(
                id="filter-name",
                placeholder="Filter by NAME",
                type="text",
                value="",
                className="mb-3"
            ),
            width=4
        )
    ]),
    dbc.Row([
        dbc.Col([
            dbc.Switch(id="toggle-notifications", label="Enable notifications", value=True, className="me-3")
        ], width=12, className="mb-3 d-flex justify-content-start align-items-center")
    ]),
    dbc.Row([
        dbc.Col(dash_table.DataTable(
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
            editable=False,  # Only columns with "editable=True" can be modified
            page_size=1000,
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left"},
            style_data_conditional=[
                {
                    'if': {'filter_query': '{Status} = "Common"'},
                    'backgroundColor': '#d4edda',
                    'color': '#155724',
                },
                {
                    'if': {'filter_query': '{Status} = "Only in Left"'},
                    'backgroundColor': '#f8d7da',
                    'color': '#721c24',
                },
                {
                    'if': {'filter_query': '{Status} = "Only in Right"'},
                    'backgroundColor': '#d1ecf1',
                    'color': '#0c5460',
                },
                {
                    'if': {'filter_query': '{Status} = "Different"'},
                    'backgroundColor': '#fff3cd',
                    'color': '#856404',
                },
            ]
        ), width=12)
    ]),
    dbc.Alert(id="notification-alert", dismissable=True, is_open=False, duration=5000),
    dbc.Toast(
        id="toast-message",
        header="Notification",
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
#  SECTION: Main Dash callback
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

    # If right_domains is a single string, transform it into a list
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

    # ------------------ Handle DataTable editing (ACTION_right changes) -------------
    if triggered_id == "comparison-table" and data_timestamp:
        if not table_data or not old_data or not right_domains:
            return (domains_options, domains_options, dash.no_update,
                    dash.no_update, False, toast_message, toast_is_open,
                    dash.no_update)

        old_df = pd.DataFrame(old_data)
        new_df = pd.DataFrame(table_data)

        # Find rows modified in ACTION_right
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
                        # If EXT_ID_right is not valid, use the selected target
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
                toast_message = "Modification successfully saved."
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
                toast_message = f"Error during update: {str(e)}"
                return (domains_options, domains_options,
                        dash.no_update, dash.no_update, False,
                        toast_message, True,
                        dash.no_update)

    # ------------------ "Compare" button or filter_name change ---------------------
    if triggered_id in ["compare-button", "filter-name"]:
        if not left_domains or not right_domains:
            alert_children = "Select the domains to compare."
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
            alert_children = "No data available for comparison."
            alert_is_open = notifications_enabled
            toast_message = alert_children
            toast_is_open = notifications_enabled
            return (domains_options, domains_options, [],
                    alert_children, alert_is_open,
                    toast_message, toast_is_open,
                    [])

        comparison_data = comparison.to_dict("records")
        alert_children = "Comparison completed."
        alert_is_open = notifications_enabled
        toast_message = alert_children
        toast_is_open = notifications_enabled
        new_old_data = comparison_data

        return (domains_options, domains_options,
                comparison_data, alert_children, alert_is_open,
                toast_message, toast_is_open,
                new_old_data)

    # ------------------ Table Actions: "Action" / "Delete" columns ------------------
    if triggered_id == "comparison-table":
        if not table_data or not old_data or not left_domains or not right_domains:
            return (domains_options, domains_options, dash.no_update,
                    dash.no_update, dash.no_update,
                    toast_message, toast_is_open,
                    dash.no_update)

        if active_cell:
            col = active_cell.get("column_id")
            row_data = table_data[active_cell["row"]]

            # Deletion (Delete)
            if col == "Delete":
                if row_data["Delete"] == "-":
                    alert_children = "No action available for this record."
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
                    alert_children = f"Error during deletion: {str(e)}"
                    alert_is_open = notifications_enabled
                    toast_message = alert_children
                    toast_is_open = notifications_enabled
                    return (domains_options, domains_options,
                            table_data, alert_children, alert_is_open,
                            toast_message, toast_is_open,
                            old_data)

            # Update/Insert (Action column)
            elif col == "Action":
                if row_data["Action"] == "-":
                    alert_children = "No action available for this record."
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
                    alert_children = f"Error during update: {str(e)}"
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
#  SECTION: Run the app
# =============================================================================
if __name__ == "__main__":
    app.run_server(host='0.0.0.0', port=8050, debug=False)
