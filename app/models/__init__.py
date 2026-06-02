"""SQLAlchemy ORM models for the metadata database (``dw_metadata``).

Importing this package is sufficient to register every model on the shared
:class:`app.core.database.Base`. ``init_metadata_tables()`` can then create
all tables in one shot.
"""

from .approved_relationship import ApprovedRelationship
from .batch import Batch
from .bronze_table import BronzeTable
from .column_profile import ColumnProfile
from .export_job import ExportJob
from .gold_table import GoldTable
from .quality_issue import QualityIssue
from .relationship_suggestion import RelationshipSuggestion
from .silver_table import SilverTable
from .table_profile import TableProfile
from .uploaded_file import UploadedFile

__all__ = [
    "ApprovedRelationship",
    "Batch",
    "BronzeTable",
    "ColumnProfile",
    "ExportJob",
    "GoldTable",
    "QualityIssue",
    "RelationshipSuggestion",
    "SilverTable",
    "TableProfile",
    "UploadedFile",
]
