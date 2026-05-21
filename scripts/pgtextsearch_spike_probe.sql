CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_textsearch;

DROP TABLE IF EXISTS search_spike_documents;
CREATE TABLE search_spike_documents (
    id bigserial PRIMARY KEY,
    source_uri text NOT NULL,
    extension text NOT NULL,
    content text NOT NULL,
    embedding vector(3)
);

INSERT INTO search_spike_documents (source_uri, extension, content, embedding)
VALUES
    ('kia_ev6_charging.txt', '.txt', 'Kia EV6 fast charging guide and charging limits.', '[0.10,0.20,0.30]'),
    ('generic_charging.txt', '.txt', 'Generic charging schedule for household batteries.', '[0.20,0.10,0.30]'),
    ('kia_ev6_battery.txt', '.txt', 'Kia EV6 battery warranty and service notes.', '[0.30,0.20,0.10]'),
    ('banana_bread_recipe.txt', '.txt', 'Banana bread recipe with cinnamon and walnuts.', '[0.90,0.10,0.10]'),
    ('kia_ev6_manual.pdf', '.pdf', 'Kia EV6 owner manual with charging and battery care.', '[0.10,0.30,0.20]');

CREATE INDEX search_spike_documents_content_bm25
ON search_spike_documents
USING bm25(content)
WITH (text_config='english');

SELECT
    source_uri,
    extension,
    content <@> 'EV6 charging' AS bm25_score
FROM search_spike_documents
WHERE extension = '.txt'
ORDER BY content <@> 'EV6 charging'
LIMIT 5;
