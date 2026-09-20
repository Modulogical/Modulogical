def marketplace(item):
    print(f"""
CREATE TABLE {item}_products (
title TEXT NOT NULL, 
developer_id TEXT NOT NULL,
developer_tier TEXT NOT NULL, 
{item}_id TEXT NOT NULL, 
schema TEXT NOT NULL,    
description TEXT NOT NULL DEFAULT '',    
display TEXT NOT NULL DEFAULT '',    
{item}_version TEXT NOT NULL, 
{item}_price TEXT NOT NULL,
{item}_dependencies TEXT NOT NULL
);
""")

def engine_forge(item):
    print(f"""
CREATE TABLE {item}_queue (
title TEXT NOT NULL, 
developer_id TEXT NOT NULL,
developer_tier TEXT NOT NULL, 
{item}_id TEXT NOT NULL, 
schema TEXT NOT NULL,    
description TEXT NOT NULL DEFAULT '',    
display TEXT NOT NULL DEFAULT '',    
{item}_version TEXT NOT NULL, 
{item}_price TEXT NOT NULL,
{item}_dependencies TEXT NOT NULL
);
""")

def atlas(item):
    print(f"""
CREATE TABLE {item}_items (
title TEXT NOT NULL, 
developer_id TEXT NOT NULL,
developer_tier TEXT NOT NULL, 
{item}_id TEXT NOT NULL, 
schema TEXT NOT NULL,    
description TEXT NOT NULL DEFAULT '',    
display TEXT NOT NULL DEFAULT '',    
{item}_version TEXT NOT NULL, 
{item}_price TEXT NOT NULL,
{item}_dependencies TEXT NOT NULL
);
""")

commands=[atlas, engine_forge, marketplace]
items=["module", "database", "personality", "workflow"]
for command in commands:
    for item in items:
        command(item)