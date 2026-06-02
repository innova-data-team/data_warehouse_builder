"""Gold layer builder.

Consumes Silver tables + **approved** relationships and produces a star
schema in MySQL (``dw_gold``):

* ``gold_dim_*``  — dimension tables (surrogate key + natural key)
* ``gold_fact_*`` — fact tables (FK-resolved surrogate keys, measures)
* ``gold_v_*``    — joined analytical / KPI views

The builder refuses to run if no relationships are approved and there is
more than one Silver table — this is the safety contract that protects
downstream dashboards from accidental fan-traps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import gold_engine, silver_engine
from app.core.exceptions import ApprovalRequiredError
from app.core.logging import get_logger
from app.models import (
    ApprovedRelationship,
    ColumnProfile,
    GoldTable,
    SilverTable,
    TableProfile,
)
from app.utils.sql_utils import (
    ddl_charset_clause,
    quote_identifier,
    safe_table_name,
)

_log = get_logger(__name__)


# ---------------------------------------------------------------------------
@dataclass(slots=True)
class _SilverTableInfo:
    name: str
    classification: str
    columns: list[str]
    pk_candidate: str | None


class GoldBuilder:
    """Materializes Gold facts, dimensions, and views."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.silver: Engine = silver_engine()
        self.gold: Engine = gold_engine()

    # ------------------------------------------------------------------
    def build(self, batch_id: str) -> list[GoldTable]:
        silvers = (
            self.session.query(SilverTable)
            .filter(SilverTable.batch_id == batch_id)
            .all()
        )
        if not silvers:
            _log.warning("Gold build: no Silver tables for batch=%s", batch_id)
            return []

        approved = (
            self.session.query(ApprovedRelationship)
            .filter(ApprovedRelationship.batch_id == batch_id)
            .all()
        )
        if not approved and len(silvers) > 1:
            raise ApprovalRequiredError(
                "Gold cannot be built: no approved relationships and more than "
                "one Silver table exist. Approve at least one relationship first.",
                details={"silver_table_count": len(silvers)},
            )

        infos = [self._load_silver_info(batch_id, s.table_name) for s in silvers]
        info_by_name = {i.name: i for i in infos}

        outputs: list[GoldTable] = []

        # Dimensions: every Silver table classified as 'dim'
        for info in infos:
            if info.classification == "dim":
                outputs.append(self._build_dimension(batch_id, info))

        # Facts: 'fact' classification, plus 'flat' tables when there is at
        # least one approved relationship pointing into them.
        for info in infos:
            if info.classification == "fact":
                outputs.append(self._build_fact(batch_id, info, approved, info_by_name))

        # If we have nothing yet (e.g. single-file batch), produce a flat
        # Gold copy of the only Silver table so dashboards still have data.
        if not outputs and len(silvers) == 1:
            outputs.append(self._build_fact(batch_id, infos[0], [], info_by_name))

        # Analytical view per fact + KPI summary
        for table in [t for t in outputs if t.role == "fact"]:
            outputs.append(self._build_flat_view(batch_id, table, approved, info_by_name))

        outputs.append(self._build_kpi_view(batch_id, [t for t in outputs if t.role == "fact"]))

        return outputs

    # ------------------------------------------------------------------
    def _load_silver_info(self, batch_id: str, silver_table: str) -> _SilverTableInfo:
        tprof = (
            self.session.query(TableProfile)
            .filter(
                TableProfile.batch_id == batch_id,
                TableProfile.table_name == silver_table,
                TableProfile.layer == "silver",
            )
            .one_or_none()
        )
        cprofs = (
            self.session.query(ColumnProfile)
            .filter(
                ColumnProfile.batch_id == batch_id,
                ColumnProfile.table_name == silver_table,
                ColumnProfile.layer == "silver",
            )
            .all()
        )
        cols = [c.column_name for c in cprofs if not c.column_name.startswith("_")]
        pk = next(
            (c.column_name for c in cprofs if c.uniqueness_ratio >= 0.99 and (c.null_percentage or 0) < 1),
            None,
        )
        return _SilverTableInfo(
            name=silver_table,
            classification=(tprof.classification if tprof else "flat"),
            columns=cols,
            pk_candidate=pk,
        )

    # ------------------------------------------------------------------
    def _build_dimension(self, batch_id: str, info: _SilverTableInfo) -> GoldTable:
        base = info.name.removeprefix("silver_")
        dim_name = safe_table_name(f"gold_dim_{base}")
        sk_col = f"{base}_sk"
        nk_col = info.pk_candidate or info.columns[0]
        col_list = ", ".join(quote_identifier(c) for c in info.columns)

        ddl = (
            f"CREATE TABLE {quote_identifier(dim_name)} (\n"
            f"  {quote_identifier(sk_col)} BIGINT NOT NULL AUTO_INCREMENT,\n"
            f"  {quote_identifier('_gold_id')} BIGINT NOT NULL,\n"
            f"  {quote_identifier('_batch_id')} VARCHAR(64) NOT NULL,\n"
            f"  {quote_identifier('_source_silver_tables')} VARCHAR(512) NOT NULL,\n"
            f"  {quote_identifier('_gold_created_at')} DATETIME NOT NULL,\n"
            f"  {quote_identifier('_gold_quality_score')} DOUBLE NULL,\n"
            + "\n".join([f"  {quote_identifier(c)} TEXT NULL," for c in info.columns])
            + f"\n  PRIMARY KEY ({quote_identifier(sk_col)}),\n"
            f"  KEY {quote_identifier('ix_' + nk_col)} ({quote_identifier(nk_col)}(255))\n"
            f") ENGINE=InnoDB {ddl_charset_clause(settings.mysql_charset, settings.mysql_collation)};"
        )
        dml = (
            f"INSERT INTO {quote_identifier(dim_name)} "
            f"({quote_identifier('_gold_id')}, {quote_identifier('_batch_id')}, "
            f"{quote_identifier('_source_silver_tables')}, {quote_identifier('_gold_created_at')}, "
            f"{quote_identifier('_gold_quality_score')}, {col_list})\n"
            f"SELECT ROW_NUMBER() OVER (ORDER BY 1), :bid, :src, :now, 1.0, {col_list}\n"
            f"  FROM {settings.db_silver}.{quote_identifier(info.name)}\n"
            f" WHERE {quote_identifier('_batch_id')} = :bid;"
        )

        self._run_ddl_and_dml(batch_id, dim_name, ddl, dml, role="dim", sources=[info.name])
        return self._register(batch_id, dim_name, role="dim", sources=[info.name])

    # ------------------------------------------------------------------
    def _build_fact(
        self,
        batch_id: str,
        info: _SilverTableInfo,
        approved: list[ApprovedRelationship],
        info_by_name: dict[str, _SilverTableInfo],
    ) -> GoldTable:
        base = info.name.removeprefix("silver_")
        fact_name = safe_table_name(f"gold_fact_{base}")

        # Determine join edges where THIS table is on the many-side
        join_clauses: list[str] = []
        select_cols: list[str] = [
            f"{quote_identifier('s')}.{quote_identifier(c)} AS {quote_identifier(c)}"
            for c in info.columns
        ]
        alias_idx = 0
        for rel in approved:
            if rel.source_table != info.name and rel.target_table != info.name:
                continue
            if rel.relation_type not in ("many_to_one", "one_to_many", "one_to_one"):
                continue

            other = rel.target_table if rel.source_table == info.name else rel.source_table
            other_info = info_by_name.get(other)
            if other_info is None:
                continue

            alias_idx += 1
            other_alias = f"d{alias_idx}"
            join_col_local = rel.source_column if rel.source_table == info.name else rel.target_column
            join_col_other = rel.target_column if rel.source_table == info.name else rel.source_column
            other_base = other.removeprefix("silver_")
            dim_table = safe_table_name(f"gold_dim_{other_base}")

            join_clauses.append(
                f"LEFT JOIN {settings.db_gold}.{quote_identifier(dim_table)} {other_alias} "
                f"  ON {other_alias}.{quote_identifier(join_col_other)} = "
                f"     {quote_identifier('s')}.{quote_identifier(join_col_local)}"
            )
            select_cols.append(
                f"{other_alias}.{quote_identifier(f'{other_base}_sk')} AS {quote_identifier(f'{other_base}_sk')}"
            )

        select_sql = ",\n  ".join(select_cols)
        join_sql = "\n".join(join_clauses)

        # FK (surrogate-key) columns referencing approved dimensions
        fk_columns: list[str] = []
        for rel in approved:
            if rel.source_table != info.name and rel.target_table != info.name:
                continue
            other = rel.target_table if rel.source_table == info.name else rel.source_table
            if other not in info_by_name:
                continue
            other_base = other.removeprefix("silver_")
            fk_col = f"{other_base}_sk"
            fk_columns.append(f"  {quote_identifier(fk_col)} BIGINT NULL")
        fk_block = (",\n" + ",\n".join(fk_columns)) if fk_columns else ""

        data_col_block = "\n".join(f"  {quote_identifier(c)} TEXT NULL," for c in info.columns)

        ddl = (
            f"CREATE TABLE {quote_identifier(fact_name)} (\n"
            f"  {quote_identifier('_gold_id')} BIGINT NOT NULL AUTO_INCREMENT,\n"
            f"  {quote_identifier('_batch_id')} VARCHAR(64) NOT NULL,\n"
            f"  {quote_identifier('_source_silver_tables')} VARCHAR(512) NOT NULL,\n"
            f"  {quote_identifier('_gold_created_at')} DATETIME NOT NULL,\n"
            f"  {quote_identifier('_gold_quality_score')} DOUBLE NULL,\n"
            f"{data_col_block}"
            f"{fk_block},\n"
            f"  PRIMARY KEY ({quote_identifier('_gold_id')})\n"
            f") ENGINE=InnoDB {ddl_charset_clause(settings.mysql_charset, settings.mysql_collation)};"
        )

        dml = (
            f"INSERT INTO {quote_identifier(fact_name)} (\n"
            f"  {quote_identifier('_batch_id')}, {quote_identifier('_source_silver_tables')},\n"
            f"  {quote_identifier('_gold_created_at')}, {quote_identifier('_gold_quality_score')},\n"
            + ",\n".join(f"  {quote_identifier(c)}" for c in info.columns)
            + "\n)\n"
            f"SELECT :bid, :src, :now, s.{quote_identifier('_quality_score')},\n  "
            + select_sql + "\n"
            f"  FROM {settings.db_silver}.{quote_identifier(info.name)} s\n"
            + (join_sql + "\n" if join_sql else "")
            + " WHERE s.`_batch_id` = :bid;"
        )

        self._run_ddl_and_dml(batch_id, fact_name, ddl, dml, role="fact", sources=[info.name])
        return self._register(batch_id, fact_name, role="fact", sources=[info.name])

    # ------------------------------------------------------------------
    def _build_flat_view(
        self,
        batch_id: str,
        fact: GoldTable,
        approved: list[ApprovedRelationship],
        info_by_name: dict[str, _SilverTableInfo],
    ) -> GoldTable:
        view_name = safe_table_name(f"gold_v_{fact.table_name.removeprefix('gold_fact_')}_flat")
        sql = (
            f"CREATE OR REPLACE VIEW {quote_identifier(view_name)} AS\n"
            f"SELECT * FROM {settings.db_gold}.{quote_identifier(fact.table_name)};"
        )
        with self.gold.begin() as conn:
            conn.execute(text(sql))
        self._persist_sql(batch_id, f"{view_name}.sql", sql, subdir="views")
        return self._register(batch_id, view_name, role="view", sources=[fact.table_name])

    def _build_kpi_view(self, batch_id: str, facts: list[GoldTable]) -> GoldTable:
        view_name = "gold_v_kpi_summary"
        if not facts:
            sql = (
                f"CREATE OR REPLACE VIEW {quote_identifier(view_name)} AS\n"
                "SELECT 'no_facts' AS message;"
            )
        else:
            unions = []
            for f in facts:
                unions.append(
                    f"SELECT '{f.table_name}' AS source_table, COUNT(*) AS row_count, "
                    f"AVG(`_gold_quality_score`) AS avg_quality "
                    f"FROM {settings.db_gold}.{quote_identifier(f.table_name)} "
                    f"WHERE `_batch_id` = '{batch_id}'"
                )
            sql = (
                f"CREATE OR REPLACE VIEW {quote_identifier(view_name)} AS\n"
                + "\nUNION ALL\n".join(unions) + ";"
            )
        with self.gold.begin() as conn:
            conn.execute(text(sql))
        self._persist_sql(batch_id, f"{view_name}.sql", sql, subdir="views")
        return self._register(batch_id, view_name, role="kpi_view",
                              sources=[f.table_name for f in facts])

    # ------------------------------------------------------------------
    def _run_ddl_and_dml(
        self, batch_id: str, table_name: str, ddl: str, dml: str, *,
        role: str, sources: list[str],
    ) -> None:
        with self.gold.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {quote_identifier(table_name)}"))
            conn.execute(text(ddl))
            conn.execute(
                text(dml),
                {"bid": batch_id, "src": ",".join(sources), "now": datetime.utcnow()},
            )
        self._persist_sql(batch_id, f"create_{table_name}.sql",
                          ddl + "\n\n" + dml, subdir="gold")

    def _persist_sql(self, batch_id: str, filename: str, sql: str, *, subdir: str) -> None:
        out = settings.batch_sql_dir(batch_id) / subdir
        out.mkdir(parents=True, exist_ok=True)
        (out / filename).write_text(sql, encoding="utf-8")

    def _register(
        self, batch_id: str, table_name: str, *, role: str, sources: list[str]
    ) -> GoldTable:
        row = GoldTable(
            batch_id=batch_id,
            table_name=table_name,
            role=role,
            source_silver_tables=",".join(sources),
            row_count=0,
            column_count=0,
        )
        self.session.add(row)
        self.session.commit()
        return row

    # ------------------------------------------------------------------
    def list_tables(self, batch_id: str) -> list[GoldTable]:
        return (
            self.session.query(GoldTable)
            .filter(GoldTable.batch_id == batch_id)
            .order_by(GoldTable.created_at)
            .all()
        )
