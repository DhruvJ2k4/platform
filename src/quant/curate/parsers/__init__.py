"""Format-epoch-versioned parsers for raw source files (one module per source format epoch).

Contract (docs 06 §6.2, 09): each parser maps one raw file format epoch to typed rows, is pure
(bytes in, rows out), and is pinned by fixture tests per epoch. Format drift creates a new parser
version rather than mutating an old one, so historical raw remains parseable forever.
"""
