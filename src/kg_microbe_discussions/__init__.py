"""kg_microbe_discussions — discussions/knowledge-gap browser exporter.

Generalized port of DisMech's discussions_export. Walks a repo's records
(config-driven), flattens every `Discussion` into a search record, and writes a
self-contained static browser to app/discussions/ (index.html + data.js). See
export.py.
"""
