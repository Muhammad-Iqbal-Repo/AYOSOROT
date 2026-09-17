# config.py
from dataclasses import dataclass

# ── App identity ──────────────────────────────────────────────────────────────
APP_NAME     = "SOROT"
APP_SUBTITLE = "Sistem Observasi & Riset Online Tokoh"
APP_ICON     = "S"

# ── Research dimensions ───────────────────────────────────────────────────────
# Ordered dict: key -> (sidebar_label, prompt_text)
#
# key          : used internally and as Streamlit checkbox widget key
# sidebar_label: displayed as the checkbox label in the sidebar
# prompt_text  : injected into the Searcher prompt when the dimension is selected
#
# The riwayat_pekerjaan prompt_text contains a {name} placeholder that
# build_searcher_prompt() substitutes with the actual person name so the
# LinkedIn site: query targets the right person.
RESEARCH_DIMENSIONS: dict[str, tuple[str, str]] = {
    "jabatan": (
        "Jabatan dan instansi",
        "jabatan dan instansi tempat bekerja, saat ini maupun masa lalu",
    ),
    "partai": (
        "Afiliasi partai politik",
        "afiliasi dan keanggotaan partai politik",
    ),
    "keluarga": (
        "Relasi keluarga",
        "relasi dan anggota keluarga beserta peran publik mereka",
    ),
    "jabatan_khusus": (
        "Klasifikasi pejabat (Menteri / DPR / Staf Khusus)",
        "status sebagai Menteri, Wakil Menteri, Staf Khusus, Anggota DPR/DPRD/DPD",
    ),
    "tni_polri": (
        "Status TNI / POLRI",
        "status TNI atau POLRI (aktif atau purnawirawan) beserta pangkat terakhir",
    ),
    "usaha": (
        "Afiliasi grup usaha",
        "afiliasi grup usaha dan perusahaan sebagai komisaris, direktur, atau pemegang saham",
    ),
    "status_hidup": (
        "Status hidup / meninggal",
        "apakah masih hidup atau sudah meninggal dunia",
    ),
    "riwayat_pekerjaan": (
        "Riwayat pekerjaan (LinkedIn dan umum)",
        (
            'cari profil LinkedIn dengan query: site:linkedin.com/in "{name}" '
            "lalu ekstrak riwayat pekerjaan lengkap — semua jenis pekerjaan "
            "(bukan hanya posisi strategis): jabatan, nama perusahaan, industri, "
            "tahun mulai, tahun selesai atau Sekarang, lokasi. "
            "Jika LinkedIn tidak ditemukan, gunakan sumber lain seperti website "
            "perusahaan, berita, atau profil profesional lainnya"
        ),
    ),
}


@dataclass
class AppConfig:
    page_title: str = f"{APP_NAME} — {APP_SUBTITLE}"
    page_icon:  str = APP_ICON
    layout:     str = "wide"
