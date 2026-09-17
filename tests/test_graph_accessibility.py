import unittest

from agent.schema import CorporateAffiliation, FamilyMember, PersonProfile
from ui.graph_renderer import _relationship_rows


class GraphAccessibilityTests(unittest.TestCase):
    def test_relationship_rows_expose_every_visual_connection_as_text(self):
        profile = PersonProfile(
            full_name="Alya Santoso",
            family_members=[
                FamilyMember(name="Bima Santoso", relation="Saudara", role="Dokter")
            ],
            corporate_affiliations=[
                CorporateAffiliation(entity_name="Nusa Group", role="Komisaris")
            ],
            party_affiliations=["Partai Contoh"],
        )

        self.assertEqual(
            _relationship_rows(profile),
            [
                {
                    "Kategori": "Keluarga",
                    "Nama": "Bima Santoso",
                    "Hubungan": "Saudara",
                    "Detail": "Dokter",
                },
                {
                    "Kategori": "Perusahaan",
                    "Nama": "Nusa Group",
                    "Hubungan": "Komisaris",
                    "Detail": "Tidak ada detail tambahan",
                },
                {
                    "Kategori": "Partai",
                    "Nama": "Partai Contoh",
                    "Hubungan": "Anggota atau afiliasi",
                    "Detail": "Tidak ada detail tambahan",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
