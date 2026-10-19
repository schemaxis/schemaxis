"""Relational intention discovery without importing or launching SQLite."""
import json
from importlib.resources import files


def catalogue():
    return {'application':{'label':'SQLite','purpose':'Build a fresh typed relational database and checked group totals from captured JSON tables, enforcing primary and foreign keys.','keywords':['relational','SQLite','typed tables','group totals','foreign key']},
        'searchCases':json.loads(files(__package__).joinpath('search-cases.json').read_text()),
        'requirements':['SQLite 3.54.1 command-line executable; exact bounded INTEGER or printable ASCII TEXT cells.','Declare local JSON row arrays, parent tables before children, primary keys and same-type foreign keys.','No authored SQL, existing database inputs, network, extensions or automatic type conversion.'],
        'references':['docs/sqlite.md','src/schemaxis/adaptors/sqlite/readiness.json'],
        'operations':{'summarise':{'purpose':'Import typed tables, enforce primary and foreign key integrity, inner join, filter integers and publish ordered group totals with COUNT/SUM plus a fresh SQLite database.',
            'keywords':['group totals','foreign key','table','relational','inner join','aggregate','summarise','integer','COUNT','SUM','SQLite','CSV','JSON'],
            'semantics':['Integer sums are exact; null amounts are ignored and all-null group sums are null. Counts include every surviving joined/filtered row.','Typed group keys use binary case-sensitive order, null first; empty strings and zero remain separate from null.'],
            'examples':[{'reference':'examples/schemaxis/sqlite-sales.json','purpose':'Group sales by joined department region, including null, empty-string, zero and negative totals.'},{'reference':'examples/schemaxis/sqlite-sales-variant.json','purpose':'Change the inclusive sales ID threshold to alter joined counts and totals.'}]}}}
