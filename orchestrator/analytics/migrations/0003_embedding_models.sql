CREATE TABLE analytics.embedding_models (
    model_id      TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimension     INTEGER NOT NULL CHECK (dimension > 0),
    PRIMARY KEY (model_id, model_version)
);
