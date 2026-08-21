"""Query layer shared by the HTTP API and the in-process client.

Each function here is the single implementation of one endpoint's data access.
`hub/app/routes/api.py` wraps it with auth, pagination and JSON encoding;
`app/data_hub_client.py` calls it directly when CO runs in-process, skipping
HTTP and — crucially — the OFFSET pagination walk.

Measured on johnson-vn (13,131 materials): the same SQL costs 0.65s as one
query and 5.38s as 14 OFFSET pages. Serialising the 8.7 MB result to JSON and
back costs 0.13s, and an in-process ASGI bridge measured no faster than the
socket. The pagination is the cost, which is why these functions take
`limit=None` to mean "everything, one query".
"""
