# Data Hub API Request: <short-name>

## Use Case
Describe the CO workflow that needs Data Hub data or behavior.

## Existing Endpoint Gap
List the existing Data Hub endpoint(s) checked and why they are insufficient.

## Proposed Contract
Method and path:

Query parameters:

Request body:

Response body:

Error cases:

## Auth
Required scope:

Client scoping rule:

Token type:

## Data Semantics
Source of truth:

Precision requirements:

Pagination:

Idempotency:

Versioning or pinning:

## Tests Required In Data Hub
Provider tests:

Negative tests:

Edge cases:

## CO Consumer Plan
Adapter method to add in `app/data_hub_client.py`:

Call sites that will consume the adapter:

Consumer tests:

## Approval
Data Hub contract owner:

Approval date:

Data Hub commit:
