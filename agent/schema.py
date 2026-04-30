# agent/schema.py
"""
Pydantic models for all data produced by the PersonIntelAgent.

Key design decisions
────────────────────
- SourceEntry replaces bare URL strings so each source carries a quality tag
  that the UI uses to indicate reliability at a glance.
- FieldConfidence carries one confidence level per research dimension so users
  know exactly which parts of a profile need extra verification, rather than
  applying one rating to the whole report.
- All optional fields default to None / empty list so Pydantic never rejects a
  partial response from Gemini.
"""
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional


# ── Enums ─────────────────────────────────────────────────────────────────────

class SourceQuality(str, Enum):
    OFFICIAL    = "Resmi"           # Government sites, official institutions
    NATIONAL    = "Media Nasional"  # Kompas, Tempo, Detik, CNN Indonesia
    LOCAL       = "Media Lokal"     # Regional newspapers / news sites
    PROFESSIONAL = "Profesional"    # LinkedIn, company websites, annual reports
    OTHER       = "Lainnya"         # Blogs, wikis, unclassified


class ConfidenceLevel(str, Enum):
    HIGH   = "high"    # Multiple independent sources agree
    MEDIUM = "medium"  # Partially confirmed
    LOW    = "low"     # Single source or uncertain


# ── Sub-models ────────────────────────────────────────────────────────────────

class SourceEntry(BaseModel):
    """A single research source with a reliability tag."""
    url:     str
    title:   Optional[str] = None
    quality: SourceQuality = SourceQuality.OTHER


class FieldConfidence(BaseModel):
    """Per-dimension confidence scores — one level per research category."""
    jabatan:           ConfidenceLevel = ConfidenceLevel.MEDIUM
    partai:            ConfidenceLevel = ConfidenceLevel.MEDIUM
    keluarga:          ConfidenceLevel = ConfidenceLevel.MEDIUM
    jabatan_khusus:    ConfidenceLevel = ConfidenceLevel.MEDIUM
    tni_polri:         ConfidenceLevel = ConfidenceLevel.MEDIUM
    usaha:             ConfidenceLevel = ConfidenceLevel.MEDIUM
    status_hidup:      ConfidenceLevel = ConfidenceLevel.MEDIUM
    riwayat_pekerjaan: ConfidenceLevel = ConfidenceLevel.MEDIUM


class FamilyMember(BaseModel):
    name:     str
    relation: str                   # e.g. "Istri", "Anak", "Ayah"
    role:     Optional[str] = None  # e.g. "Anggota DPR RI", "Komisaris"
    notes:    Optional[str] = None


class CorporateAffiliation(BaseModel):
    entity_name: str
    role:        Optional[str] = None  # e.g. "Komisaris Utama"
    group:       Optional[str] = None  # e.g. "Grup Bakrie"


class TniPolriInfo(BaseModel):
    is_tni_polri: bool           = False
    branch:       Optional[str]  = None   # e.g. "TNI AD", "POLRI"
    last_rank:    Optional[str]  = None   # e.g. "Jenderal"
    status:       Optional[str]  = None   # "Aktif" | "Purnawirawan"


class JobEntry(BaseModel):
    """One employment record — covers all job types, not just strategic roles."""
    title:      str
    company:    str
    industry:   Optional[str] = None
    start_year: Optional[str] = None
    end_year:   Optional[str] = None   # "Sekarang" if still active
    location:   Optional[str] = None
    source:     Optional[str] = None   # e.g. "LinkedIn", "Website Perusahaan"


class DisambiguationCandidate(BaseModel):
    """One candidate returned by the disambiguation pre-check."""
    name:        str
    description: str   # Short role/context: "Mantan Bupati Garut, Jawa Barat"


# ── Root model ────────────────────────────────────────────────────────────────

class PersonProfile(BaseModel):
    full_name:     str
    also_known_as: list[str] = Field(default_factory=list)

    # Vital status
    is_alive:   Optional[bool] = None
    death_info: Optional[str]  = None

    # Strategic / government roles
    current_roles: list[str] = Field(default_factory=list)
    past_roles:    list[str] = Field(default_factory=list)

    # Full employment history (all job types, sourced from LinkedIn etc.)
    job_history: list[JobEntry] = Field(default_factory=list)

    # Government classification flags
    is_minister:       bool = False
    is_deputy_minister: bool = False
    is_dpr_member:     bool = False
    is_dprd_member:    bool = False
    is_staf_khusus:    bool = False
    is_high_official:  bool = False

    # Military / police
    tni_polri: TniPolriInfo = Field(default_factory=TniPolriInfo)

    # Political
    party_affiliations: list[str]   = Field(default_factory=list)
    political_notes:    Optional[str] = None

    # Family
    family_members: list[FamilyMember] = Field(default_factory=list)

    # Corporate
    corporate_affiliations: list[CorporateAffiliation] = Field(default_factory=list)

    # Metadata
    sources:          list[SourceEntry]  = Field(default_factory=list)
    field_confidence: FieldConfidence    = Field(default_factory=FieldConfidence)
    analyst_notes:    Optional[str]      = None


# Mapping of common Gemini variants → canonical SourceQuality values.
# Gemini often abbreviates or mistranslates quality labels; this map normalises
# them before Pydantic validates so one bad tag does not reject the whole article.
_QUALITY_ALIASES: dict[str, SourceQuality] = {
    # Exact values (identity)
    "resmi":            SourceQuality.OFFICIAL,
    "media nasional":   SourceQuality.NATIONAL,
    "media lokal":      SourceQuality.LOCAL,
    "profesional":      SourceQuality.PROFESSIONAL,
    "lainnya":          SourceQuality.OTHER,
    # Common Gemini abbreviations / mistranslations
    "official":         SourceQuality.OFFICIAL,
    "government":       SourceQuality.OFFICIAL,
    "national":         SourceQuality.NATIONAL,
    "nasional":         SourceQuality.NATIONAL,
    "national media":   SourceQuality.NATIONAL,
    "local":            SourceQuality.LOCAL,
    "lokal":            SourceQuality.LOCAL,
    "local media":      SourceQuality.LOCAL,
    "professional":     SourceQuality.PROFESSIONAL,
    "linkedin":         SourceQuality.PROFESSIONAL,
    "other":            SourceQuality.OTHER,
    "others":           SourceQuality.OTHER,
    "lain":             SourceQuality.OTHER,
}


def _normalise_quality(value) -> SourceQuality:
    """Coerces any quality string into a valid SourceQuality, defaulting to OTHER."""
    if isinstance(value, SourceQuality):
        return value
    if not isinstance(value, str):
        return SourceQuality.OTHER
    return _QUALITY_ALIASES.get(value.strip().lower(), SourceQuality.OTHER)


class NewsArticle(BaseModel):
    """
    A single news article or related publication about the searched person.

    Published date is stored as a plain string because news sources use
    inconsistent formats — we display it as-is rather than risk parse errors.

    The quality field is normalised via _normalise_quality so minor variations
    in Gemini's output (e.g. "Nasional" vs "Media Nasional") don't cause
    validation errors.
    """
    title:          str
    summary:        str                        # 2-4 sentence summary of the article
    published_date: Optional[str]  = None      # e.g. "23 April 2026", "April 2026"
    source_name:    str            = "Unknown" # e.g. "Kompas", "Tempo"
    url:            str            = ""
    quality:        SourceQuality  = SourceQuality.OTHER

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        # Normalise quality before Pydantic sees it
        if isinstance(obj, dict) and "quality" in obj:
            obj = {**obj, "quality": _normalise_quality(obj["quality"])}
        return super().model_validate(obj, *args, **kwargs)
