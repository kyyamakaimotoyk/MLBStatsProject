"""Local-only site-traffic dashboard for moundmodel.com.

Visitor analytics read from CloudFront access logs in S3 through Athena
(Glue table moundmodel_logs.cf_site_logs, defined in infra/analytics.tf).
Internal only — our own traffic data, never shown on the public site.
Ported from the NBA project's Site Traffic tab
(NBAStatsProject/visualization/dataExploration.py).

Run:  .venv\\Scripts\\python visualization\\site_traffic.py   (http://localhost:8050)

Requires visualization/requirements-viz.txt (dash + pyathena — kept out of the
root requirements.txt so the pipeline/API Docker images don't inherit them)
and an active AWS login (account 583686634997, boto3 default credential chain).

Note: the Glue table is unpartitioned, so each query scans every log file. At
this site's volume that's a few MB (a fraction of a cent per query); add
partition projection in infra/analytics.tf if traffic ever grows large.
"""

import dash
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

_ATHENA_STAGING = 's3://mlb-stats-logs-583686634997/athena-results/'
_ATHENA_REGION = 'us-east-1'
_ATHENA_WORKGROUP = 'mlb-stats'
_ATHENA_DB = 'moundmodel_logs'


def _athena_df(sql):
    """Run one Athena query, return a DataFrame. Lazy-imports pyathena so the
    app still boots (and shows a helpful error) if the package isn't installed."""
    from pyathena import connect
    from pyathena.pandas.cursor import PandasCursor
    cursor = connect(
        s3_staging_dir=_ATHENA_STAGING,
        region_name=_ATHENA_REGION,
        work_group=_ATHENA_WORKGROUP,
        schema_name=_ATHENA_DB,
    ).cursor(PandasCursor)
    return cursor.execute(sql).as_pandas()


def _traffic_card(label, value):
    return html.Div(
        [html.Div(value, style={'fontSize': '26px', 'fontWeight': 'bold'}),
         html.Div(label, style={'fontSize': '12px', 'color': '#aaa'})],
        style={'padding': '10px 14px', 'backgroundColor': '#1b1b1b',
               'borderRadius': '8px', 'textAlign': 'center'},
    )


app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY],
                title='moundmodel traffic')

app.layout = dbc.Container([
    html.Br(),
    html.H4('Site Traffic - CloudFront logs via Athena'),
    html.Div([
        'Visitor analytics for ', html.Code('moundmodel.com'),
        ', read from CloudFront access logs in S3 through Athena. ',
        'Internal only - our own traffic data, never shown on the public site. ',
        'Requires ', html.Code('pip install "pyathena[pandas]"'),
        ' and an active AWS login (account 583686634997).',
    ]),
    html.Hr(),
    dbc.Row([
        dbc.Col([
            html.Label('Window'),
            dcc.Dropdown(
                id='trafficWindow',
                options=[
                    {'label': 'Last 7 days', 'value': 7},
                    {'label': 'Last 30 days', 'value': 30},
                    {'label': 'Last 90 days', 'value': 90},
                ],
                value=30, clearable=False,
            ),
        ], width=3),
        dbc.Col(dbc.Switch(id='trafficExcludeBots',
                           label='Exclude known bots / scanners',
                           value=True, className='mt-4'), width=4),
        dbc.Col(dbc.Button('Refresh', id='trafficRefreshBtn',
                           color='primary', className='mt-4'), width=2),
    ]),
    html.Div(id='trafficStatus', className='mt-2'),
    html.Br(),
    html.Div(id='trafficHeadline'),
    html.Br(),
    dbc.Row([dbc.Col(dcc.Graph(id='trafficRequestsChart'), width=12)]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='trafficPagesChart'), width=6),
        dbc.Col(dcc.Graph(id='trafficReferrersChart'), width=6),
    ]),
    dbc.Row([
        dbc.Col(dcc.Graph(id='trafficCacheChart'), width=4),
        dbc.Col(dcc.Graph(id='trafficStatusChart'), width=4),
        dbc.Col(dcc.Graph(id='trafficGeoChart'), width=4),
    ]),
    html.Br(),
], fluid=True)


@callback(
    Output('trafficRequestsChart', 'figure'),
    Output('trafficPagesChart', 'figure'),
    Output('trafficReferrersChart', 'figure'),
    Output('trafficCacheChart', 'figure'),
    Output('trafficStatusChart', 'figure'),
    Output('trafficGeoChart', 'figure'),
    Output('trafficHeadline', 'children'),
    Output('trafficStatus', 'children'),
    Input('trafficRefreshBtn', 'n_clicks'),
    Input('trafficWindow', 'value'),
    Input('trafficExcludeBots', 'value'),
)
def _update_traffic(_n_clicks, days, exclude_bots):
    days = int(days or 30)
    blank = go.Figure().update_layout(template='plotly_dark')
    # "date" is a reserved word in Athena/Trino, so it must be double-quoted.
    where = f'"date" >= date_add(\'day\', -{days}, current_date)'
    # Public sites get hammered by vulnerability scanners probing for things a
    # static S3 site never has (wp-admin, xmlrpc, .env, .git, GraphQL, config
    # files, /api/*, /.aws/credentials, ...). There are FAR too many probe paths
    # to enumerate, but they share one tell: they all get a 403 (object missing /
    # access denied). So the decisive, complete filter is `status < 400` - real
    # visitors get 2xx/3xx. We keep a few URI patterns too, to drop the rare bot
    # that draws a non-error status (e.g. a 301 redirect hop before its 403).
    # Toggle off to see the raw firehose. Don't exclude /_next/* - legit assets.
    bots = ''
    ref_bots = ''
    if exclude_bots:
        bots = (
            " AND status < 400"
            " AND lower(uri) NOT LIKE '%wp-%'"
            " AND lower(uri) NOT LIKE '%wlwmanifest%'"
            " AND lower(uri) NOT LIKE '%xmlrpc%'"
            " AND lower(uri) NOT LIKE '%.php%'"
            " AND uri NOT LIKE '%.env%'"
            " AND uri NOT LIKE '%/.git%'"
            " AND lower(uri) NOT LIKE '%/flows'"
            " AND lower(uri) NOT LIKE '%/settings'"
        )
        ref_bots = (
            " AND referrer NOT LIKE '%aisearchindex%'"
            " AND referrer NOT LIKE '%aicrawler%'"
        )
    try:
        summary = _athena_df(
            'SELECT COUNT(*) AS requests, '
            'COUNT(DISTINCT request_ip) AS visitors, '
            "SUM(CASE WHEN response_result_type IN ('Hit','RefreshHit') THEN 1 ELSE 0 END) AS hits "
            f'FROM cf_site_logs WHERE {where}{bots}'
        )
        per_day = _athena_df(
            'SELECT "date" AS dt, COUNT(*) AS requests, '
            'COUNT(DISTINCT request_ip) AS visitors '
            f'FROM cf_site_logs WHERE {where}{bots} GROUP BY "date" ORDER BY "date"'
        )
        pages = _athena_df(
            f'SELECT uri, COUNT(*) AS hits FROM cf_site_logs WHERE {where} '
            "AND method = 'GET' AND status = 200 "
            "AND (sc_content_type LIKE 'text/html%' OR uri LIKE '%.html' OR uri = '/') "
            f'{bots} GROUP BY uri ORDER BY hits DESC LIMIT 15'
        )
        referrers = _athena_df(
            f'SELECT referrer, COUNT(*) AS n FROM cf_site_logs WHERE {where} '
            "AND referrer <> '-' AND referrer NOT LIKE '%moundmodel.com%' "
            f'{ref_bots} GROUP BY referrer ORDER BY n DESC LIMIT 15'
        )
        cache = _athena_df(
            'SELECT response_result_type AS result, COUNT(*) AS n '
            f'FROM cf_site_logs WHERE {where}{bots} GROUP BY response_result_type ORDER BY n DESC'
        )
        statuses = _athena_df(
            'SELECT CAST(status AS varchar) AS status_code, COUNT(*) AS n '
            f'FROM cf_site_logs WHERE {where}{bots} GROUP BY status ORDER BY n DESC'
        )
        geo = _athena_df(
            'SELECT substr(location, 1, 3) AS edge, COUNT(*) AS n '
            f'FROM cf_site_logs WHERE {where}{bots} GROUP BY substr(location, 1, 3) '
            'ORDER BY n DESC LIMIT 15'
        )
    except Exception as e:
        msg = html.Div(
            ['Athena query failed: ', html.Code(str(e)),
             '. Check that you ran ', html.Code('pip install "pyathena[pandas]"'),
             ' and are logged into AWS account 583686634997.'],
            style={'color': 'salmon'})
        return blank, blank, blank, blank, blank, blank, '', msg

    if summary.empty or int(summary['requests'].iloc[0] or 0) == 0:
        note = html.Div(
            f'No log rows in the last {days} days yet - CloudFront delivery lags '
            '~an hour, and the site is low-traffic.', style={'color': '#aaa'})
        return blank, blank, blank, blank, blank, blank, '', note

    req_total = int(summary['requests'].iloc[0] or 0)
    vis_total = int(summary['visitors'].iloc[0] or 0)
    hit_total = int(summary['hits'].iloc[0] or 0)
    hit_pct = (100.0 * hit_total / req_total) if req_total else 0.0

    headline = dbc.Row([
        dbc.Col(_traffic_card('Requests', f'{req_total:,}'), width=3),
        dbc.Col(_traffic_card('Unique IPs', f'{vis_total:,}'), width=3),
        dbc.Col(_traffic_card('Cache hit rate', f'{hit_pct:.0f}%'), width=3),
        dbc.Col(_traffic_card('Window', f'{days} days'), width=3),
    ])

    fig_req = go.Figure()
    fig_req.add_trace(go.Scatter(x=per_day['dt'], y=per_day['requests'],
                                 mode='lines+markers', name='Requests'))
    fig_req.add_trace(go.Scatter(x=per_day['dt'], y=per_day['visitors'],
                                 mode='lines+markers', name='Unique IPs'))
    fig_req.update_layout(title='Requests & unique visitors per day',
                          template='plotly_dark', legend_title_text='')

    # px plots the first row at the bottom; reverse so the biggest bar is on top.
    fig_pages = px.bar(pages.iloc[::-1], x='hits', y='uri', orientation='h',
                       title='Top pages (HTML document requests)', template='plotly_dark')
    fig_ref = px.bar(referrers.iloc[::-1], x='n', y='referrer', orientation='h',
                     title='Top external referrers', template='plotly_dark')
    fig_cache = px.pie(cache, names='result', values='n', hole=0.5,
                       title='Edge cache result', template='plotly_dark')
    fig_status = px.bar(statuses, x='status_code', y='n',
                        title='HTTP status codes', template='plotly_dark')
    fig_geo = px.bar(geo, x='edge', y='n',
                     title='Requests by CloudFront edge (rough geography)',
                     template='plotly_dark')

    status_msg = html.Div(f'Loaded {req_total:,} requests across {len(per_day)} day(s).',
                          style={'color': '#7CFC00', 'fontSize': '12px'})
    return (fig_req, fig_pages, fig_ref, fig_cache, fig_status, fig_geo,
            headline, status_msg)


if __name__ == '__main__':
    app.run(port=8050)
