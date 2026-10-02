"""Demo profiles seeded into the customers, agents and admins tables (SEED_DEMO_DATA=true).

They stand in for a CRM: the matching Keycloak users (same email) are in
infra/keycloak/import/baton-realm.json and claim these rows on their first sign-in.
"""

AGENTS = [
    {"id": "agt_alex", "name": "Alex Rivera", "email": "alex.rivera@baton.example", "capacity": 3, "active": True},
    {"id": "agt_priya", "name": "Priya Shah", "email": "priya.shah@baton.example", "capacity": 3, "active": True},
    {"id": "agt_jade", "name": "Jade Kim", "email": "jade.kim@baton.example", "capacity": 2, "active": True},
]

ADMINS = [
    {"id": "adm_jade", "name": "Jade Kim", "email": "jade.kim@baton.example"},
]

CUSTOMERS = [
    {"id": "cus_maya", "name": "Maya Chen", "email": "maya.chen@example.com", "tier": "plus", "location": "Seattle, US",
     "customerSince": "2022-03-14", "lifetimeValue": 1284.5, "orderCount": 14, "previousConversations": 3},
    {"id": "cus_jordan", "name": "Jordan Okafor", "email": "jordan@okafor-studio.com", "tier": "enterprise", "location": "Lagos, NG",
     "customerSince": "2020-11-02", "lifetimeValue": 18420, "orderCount": 61, "previousConversations": 9},
    {"id": "cus_sam", "name": "Sam Patel", "email": "sam.patel@example.com", "tier": "standard", "location": "Austin, US",
     "customerSince": "2025-07-21", "lifetimeValue": 212.4, "orderCount": 3, "previousConversations": 0},
    {"id": "cus_lena", "name": "Lena Fischer", "email": "lena.f@example.de", "tier": "standard", "location": "Berlin, DE",
     "customerSince": "2024-12-01", "lifetimeValue": 389.9, "orderCount": 5, "previousConversations": 1},
    {"id": "cus_chris", "name": "Chris Morgan", "email": "chris.morgan@example.com", "tier": "plus", "location": "Toronto, CA",
     "customerSince": "2023-05-09", "lifetimeValue": 956, "orderCount": 11, "previousConversations": 2},
    {"id": "cus_tom", "name": "Tom Reyes", "email": "tom.reyes@example.com", "tier": "standard", "location": "Denver, US",
     "customerSince": "2024-02-17", "lifetimeValue": 144, "orderCount": 2, "previousConversations": 1},
    {"id": "cus_aisha", "name": "Aisha Bello", "email": "aisha.bello@example.com", "tier": "plus", "location": "Vancouver, CA",
     "customerSince": "2023-09-30", "lifetimeValue": 702.35, "orderCount": 8, "previousConversations": 4},
    {"id": "cus_noah", "name": "Noah Williams", "email": "noah.w@example.com", "tier": "enterprise", "location": "London, UK",
     "customerSince": "2021-06-12", "lifetimeValue": 9310, "orderCount": 37, "previousConversations": 6},
]  # fmt: skip
