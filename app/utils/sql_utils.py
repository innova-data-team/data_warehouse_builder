"""SQL safety helpers for MySQL identifier generation and DDL emission."""

from __future__ import annotations

import hashlib
import re
from typing import Final

# MySQL 8.x reserved words — a comprehensive (but not exhaustive) list.
# We include common pitfalls and historically reserved words to be safe.
MYSQL_RESERVED_WORDS: Final[frozenset[str]] = frozenset(
    {
        "accessible", "add", "all", "alter", "analyze", "and", "as", "asc",
        "asensitive", "before", "between", "bigint", "binary", "blob", "both",
        "by", "call", "cascade", "case", "change", "char", "character",
        "check", "collate", "column", "condition", "constraint", "continue",
        "convert", "create", "cross", "cube", "current_date", "current_time",
        "current_timestamp", "current_user", "cursor", "database", "databases",
        "day_hour", "day_microsecond", "day_minute", "day_second", "dec",
        "decimal", "declare", "default", "delayed", "delete", "desc",
        "describe", "deterministic", "distinct", "distinctrow", "div", "double",
        "drop", "dual", "each", "else", "elseif", "enclosed", "escaped",
        "exists", "exit", "explain", "false", "fetch", "float", "for", "force",
        "foreign", "from", "fulltext", "function", "generated", "get", "grant",
        "group", "grouping", "groups", "having", "high_priority",
        "hour_microsecond", "hour_minute", "hour_second", "if", "ignore", "in",
        "index", "infile", "inner", "inout", "insensitive", "insert", "int",
        "integer", "interval", "into", "io_after_gtids", "io_before_gtids",
        "is", "iterate", "join", "key", "keys", "kill", "lateral", "leading",
        "leave", "left", "like", "limit", "linear", "lines", "load",
        "localtime", "localtimestamp", "lock", "long", "longblob", "longtext",
        "loop", "low_priority", "master_bind", "master_ssl_verify_server_cert",
        "match", "maxvalue", "mediumblob", "mediumint", "mediumtext",
        "middleint", "minute_microsecond", "minute_second", "mod", "modifies",
        "natural", "not", "no_write_to_binlog", "null", "numeric", "of", "on",
        "optimize", "optimizer_costs", "option", "optionally", "or", "order",
        "out", "outer", "outfile", "over", "partition", "precision", "primary",
        "procedure", "purge", "range", "read", "reads", "read_write", "real",
        "recursive", "references", "regexp", "release", "rename", "repeat",
        "replace", "require", "resignal", "restrict", "return", "revoke",
        "right", "rlike", "rows", "schema", "schemas", "second_microsecond",
        "select", "sensitive", "separator", "set", "show", "signal", "smallint",
        "spatial", "specific", "sql", "sqlexception", "sqlstate", "sqlwarning",
        "sql_big_result", "sql_calc_found_rows", "sql_small_result", "ssl",
        "starting", "stored", "straight_join", "system", "table", "terminated",
        "then", "tinyblob", "tinyint", "tinytext", "to", "trailing", "trigger",
        "true", "undo", "union", "unique", "unlock", "unsigned", "update",
        "usage", "use", "using", "utc_date", "utc_time", "utc_timestamp",
        "values", "varbinary", "varchar", "varcharacter", "varying", "virtual",
        "when", "where", "while", "window", "with", "write", "xor", "year_month",
        "zerofill",
    }
)

# MySQL identifier hard limit
MYSQL_IDENTIFIER_MAX_LEN: Final = 64

_UNSAFE_CHARS_RE: Final = re.compile(r"[^a-zA-Z0-9_]+")
_LEADING_DIGIT_RE: Final = re.compile(r"^\d")


def is_reserved_word(name: str) -> bool:
    return name.lower() in MYSQL_RESERVED_WORDS


def quote_identifier(name: str) -> str:
    """Wrap an identifier in backticks, escaping embedded backticks."""
    escaped = name.replace("`", "``")
    return f"`{escaped}`"


def safe_identifier(
    name: str,
    *,
    fallback_prefix: str = "col",
    max_len: int = MYSQL_IDENTIFIER_MAX_LEN,
) -> str:
    """Convert an arbitrary string into a MySQL-safe snake_case identifier.

    Rules:
        * Non-alphanumeric chars become ``_``
        * Collapsed underscores
        * Leading digits prefixed with ``fallback_prefix``
        * Reserved words suffixed with ``_col`` / ``_t``
        * Length capped at ``max_len`` with a short stable hash suffix when
          truncation happens (so different long names don't collide).
    """
    if not name:
        return f"{fallback_prefix}_unnamed"

    cleaned = _UNSAFE_CHARS_RE.sub("_", name).strip("_").lower()
    if not cleaned:
        cleaned = f"{fallback_prefix}_unnamed"

    if _LEADING_DIGIT_RE.match(cleaned):
        cleaned = f"{fallback_prefix}_{cleaned}"

    if is_reserved_word(cleaned):
        cleaned = f"{cleaned}_{fallback_prefix}"

    if len(cleaned) > max_len:
        digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
        keep = max_len - len(digest) - 1
        cleaned = f"{cleaned[:keep]}_{digest}"

    return cleaned


def safe_table_name(name: str) -> str:
    return safe_identifier(name, fallback_prefix="t")


def safe_column_name(name: str) -> str:
    return safe_identifier(name, fallback_prefix="col")


def escape_string_literal(value: str) -> str:
    """Escape a string for inclusion in a MySQL single-quoted literal."""
    return (
        value.replace("\\", "\\\\")
        .replace("'", "''")
        .replace("\x00", "")
    )


def render_string_literal(value: str | None) -> str:
    if value is None:
        return "NULL"
    return f"'{escape_string_literal(value)}'"


def ddl_charset_clause(charset: str = "utf8mb4", collate: str = "utf8mb4_unicode_ci") -> str:
    return f"DEFAULT CHARACTER SET {charset} COLLATE {collate}"
