import unittest
from pathlib import Path

import untap_parser


FIXTURE_DIR = Path(__file__).with_name("testdata")

MENU2 = (FIXTURE_DIR / "menu2.txt").read_text(encoding="utf-8")
MENU3 = (FIXTURE_DIR / "menu3.txt").read_text(encoding="utf-8")
MENU4 = (FIXTURE_DIR / "menu4.txt").read_text(encoding="utf-8")

EXPECTED_MENU2 = [
    {'original': 'Fuzzy — 4.2% ABV', 'brewery': 'CLOUDWATER', 'beer': 'Fuzzy', 'style': None, 'menu_abv': 4.2, 'query': 'CLOUDWATER Fuzzy'},
    {'original': 'Chubbles — 10%', 'brewery': 'CLOUDWATER', 'beer': 'Chubbles', 'style': None, 'menu_abv': 10.0, 'query': 'CLOUDWATER Chubbles'},
    {'original': 'Putty — 8%', 'brewery': 'VERDANT', 'beer': 'Putty', 'style': None, 'menu_abv': 8.0, 'query': 'VERDANT Putty'},
    {'original': 'Lightbulb — 4.5%', 'brewery': 'VERDANT', 'beer': 'Lightbulb', 'style': None, 'menu_abv': 4.5, 'query': 'VERDANT Lightbulb'},
]

EXPECTED_MENU3 = [
    {'original': 'A Moment of Now IPA - New England / Hazy', 'brewery': 'Factory Brewing', 'beer': 'A Moment of Now', 'style': 'IPA - New England / Hazy', 'menu_abv': 7.3, 'query': 'Factory Brewing A Moment of Now'},
    {'original': 'Barrel Aged Vanilla Blend Stout - Imperial / Double', 'brewery': 'Factory Brewing', 'beer': 'Barrel Aged Vanilla Blend', 'style': 'Stout - Imperial / Double', 'menu_abv': 12.0, 'query': 'Factory Brewing Barrel Aged Vanilla Blend'},
]

EXPECTED_MENU4 = [
    {'original': 'Double Reveries Of... Motueka 2026 IPA - Imperial / Double New England / Hazy', 'brewery': 'Factory Brewing', 'beer': 'Double Reveries Of... Motueka 2026', 'style': 'IPA - Imperial / Double New England / Hazy', 'menu_abv': 8.0, 'query': 'Factory Brewing Double Reveries Of... Motueka 2026'},
    {'original': 'The Executioner 2026 IPA - Triple New England / Hazy', 'brewery': 'Factory Brewing', 'beer': 'The Executioner 2026', 'style': 'IPA - Triple New England / Hazy', 'menu_abv': 10.0, 'query': 'Factory Brewing The Executioner 2026'},
    {'original': 'Tipping Point IPA - Imperial / Double New England / Hazy', 'brewery': 'Factory Brewing', 'beer': 'Tipping Point', 'style': 'IPA - Imperial / Double New England / Hazy', 'menu_abv': 8.0, 'query': 'Factory Brewing Tipping Point'},
]


MENU7 = """Oktoberfest (2026)
Festbier / Wiesnbier | 6%
Sierra Nevada Brewing Co.
KBS - Iced MochaKBS - Iced Mocha
American Strong Ale | 11%
Founders Brewing Company
Rye da TigerRye da Tiger
Rye Beer | 7.5%
3 Floyds Brewing Co.
TrooperTrooper
American IPA | 6.6%
Lagunitas Brewing Company
ArabesqueArabesque
English Barleywine | 15.8%
Phase Three Brewing Company
Envie - 4XDHEnvie - 4XDH
Hazy Pale Ale | 5.5%
Parish Brewing Company
"""

MENU8 = """Bad Bones - EKG Double New England IPA
Regular price€15,50 EUR
Bad Bones - THE RAMP Double New England IPA
Bad Bones - THE RAMP Double New England IPA
Regular price€15,50 EUR
Lolev x Autodidact - Eagle Double New England IPA
Lolev x Autodidact - Eagle Double New England IPA
Regular price€14,00 EUR
Lolev - Rubico III Double New England IPA
Lolev - Rubico III Double New England IPA
Regular price€14,00 EUR
BreWskey - Psychedelic Superdelic Double New England IPA Double New Zealand IPA
BreWskey - Psychedelic Superdelic Double New England IPA Double New Zealand IPA
Regular price€13,50 EUR
Badlands x CLAG - Can You PHO? Double New England IPA
Badlands x CLAG - Can You PHO? Double New England IPA
Regular price€14,50 EUR
Nano Cinco - Mosaïque 2026 Double New England IPA
Nano Cinco - Mosaïque 2026 Double New England IPA
Regular price€14,00 EUR
"""

MENU9 = """All My Friends\tBetrayal\t6,8%\tIPA
Brasserie du Bas-Canada x Herman\tÉlixir-IPA\t7,0%\tIPA
Brujos\tPopulus w/ Citra\t7,5%\tIPA
Messorem\tDemoliri #0031 - XTRM Turbo\t7,0%\tIPA
Mortalis\tGemini | Bomb Pop\t7,0%\tSmoothie Sour
Sante Adairius Rustic Ales\tSilent Spaces\t6,3%\tBarrel Aged Saison
Wax Wings\t8 Streamers\t7,2%\tIPA
"""

ZERO_ABV = """Heineken // 0% // Non-Alcoholic
"""

EXPECTED_MENU7 = [
    {'original': 'Oktoberfest (2026)', 'brewery': 'Sierra Nevada Brewing Co.', 'beer': 'Oktoberfest (2026)', 'style': 'Festbier / Wiesnbier', 'menu_abv': 6.0, 'query': 'Sierra Nevada Brewing Co. Oktoberfest (2026)'},
    {'original': 'KBS - Iced Mocha', 'brewery': 'Founders Brewing Company', 'beer': 'KBS Iced Mocha', 'style': 'American Strong Ale', 'menu_abv': 11.0, 'query': 'Founders Brewing Company KBS Iced Mocha'},
    {'original': 'Rye da Tiger', 'brewery': '3 Floyds Brewing Co.', 'beer': 'Rye da Tiger', 'style': 'Rye Beer', 'menu_abv': 7.5, 'query': '3 Floyds Brewing Co. Rye da Tiger'},
    {'original': 'Trooper', 'brewery': 'Lagunitas Brewing Company', 'beer': 'Trooper', 'style': 'American IPA', 'menu_abv': 6.6, 'query': 'Lagunitas Brewing Company Trooper'},
    {'original': 'Arabesque', 'brewery': 'Phase Three Brewing Company', 'beer': 'Arabesque', 'style': 'English Barleywine', 'menu_abv': 15.8, 'query': 'Phase Three Brewing Company Arabesque'},
    {'original': 'Envie - 4XDH', 'brewery': 'Parish Brewing Company', 'beer': 'Envie 4XDH', 'style': 'Hazy Pale Ale', 'menu_abv': 5.5, 'query': 'Parish Brewing Company Envie 4XDH'},
]

EXPECTED_MENU8 = [
    {'original': 'Bad Bones - EKG Double New England IPA', 'brewery': 'Bad Bones', 'beer': 'EKG', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Bad Bones EKG'},
    {'original': 'Bad Bones - THE RAMP Double New England IPA', 'brewery': 'Bad Bones', 'beer': 'THE RAMP', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Bad Bones THE RAMP'},
    {'original': 'Lolev x Autodidact - Eagle Double New England IPA', 'brewery': 'Lolev x Autodidact', 'beer': 'Eagle', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Lolev Autodidact Eagle'},
    {'original': 'Lolev - Rubico III Double New England IPA', 'brewery': 'Lolev', 'beer': 'Rubico III', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Lolev Rubico III'},
    {'original': 'BreWskey - Psychedelic Superdelic Double New England IPA Double New Zealand IPA', 'brewery': 'BreWskey', 'beer': 'Psychedelic Superdelic', 'style': 'Double New England IPA Double New Zealand IPA', 'menu_abv': None, 'query': 'BreWskey Psychedelic Superdelic'},
    {'original': 'Badlands x CLAG - Can You PHO? Double New England IPA', 'brewery': 'Badlands x CLAG', 'beer': 'Can You PHO?', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Badlands CLAG Can You PHO?'},
    {'original': 'Nano Cinco - Mosaïque 2026 Double New England IPA', 'brewery': 'Nano Cinco', 'beer': 'Mosaïque 2026', 'style': 'Double New England IPA', 'menu_abv': None, 'query': 'Nano Cinco Mosaïque 2026'},
]

EXPECTED_MENU9 = [
    {'original': 'All My Friends\tBetrayal\t6,8%\tIPA', 'brewery': 'All My Friends', 'beer': 'Betrayal', 'style': 'IPA', 'menu_abv': 6.8, 'query': 'All My Friends Betrayal'},
    {'original': 'Brasserie du Bas-Canada x Herman\tÉlixir-IPA\t7,0%\tIPA', 'brewery': 'Brasserie du Bas-Canada x Herman', 'beer': 'Élixir-IPA', 'style': 'IPA', 'menu_abv': 7.0, 'query': 'Brasserie du Bas-Canada Herman Élixir-IPA'},
    {'original': 'Brujos\tPopulus w/ Citra\t7,5%\tIPA', 'brewery': 'Brujos', 'beer': 'Populus w/ Citra', 'style': 'IPA', 'menu_abv': 7.5, 'query': 'Brujos Populus w/ Citra'},
    {'original': 'Messorem\tDemoliri #0031 - XTRM Turbo\t7,0%\tIPA', 'brewery': 'Messorem', 'beer': 'Demoliri #0031 - XTRM Turbo', 'style': 'IPA', 'menu_abv': 7.0, 'query': 'Messorem Demoliri #0031 - XTRM Turbo'},
    {'original': 'Mortalis\tGemini | Bomb Pop\t7,0%\tSmoothie Sour', 'brewery': 'Mortalis', 'beer': 'Gemini | Bomb Pop', 'style': 'Smoothie Sour', 'menu_abv': 7.0, 'query': 'Mortalis Gemini | Bomb Pop'},
    {'original': 'Sante Adairius Rustic Ales\tSilent Spaces\t6,3%\tBarrel Aged Saison', 'brewery': 'Sante Adairius Rustic Ales', 'beer': 'Silent Spaces', 'style': 'Barrel Aged Saison', 'menu_abv': 6.3, 'query': 'Sante Adairius Rustic Ales Silent Spaces'},
    {'original': 'Wax Wings\t8 Streamers\t7,2%\tIPA', 'brewery': 'Wax Wings', 'beer': '8 Streamers', 'style': 'IPA', 'menu_abv': 7.2, 'query': 'Wax Wings 8 Streamers'},
]

EXPECTED_ZERO_ABV = [
    {'original': 'Heineken // 0% // Non-Alcoholic', 'brewery': None, 'beer': 'Heineken', 'style': 'Non-Alcoholic', 'menu_abv': 0.0, 'query': 'Heineken'},
]


class ParserContractTests(unittest.TestCase):
    def test_trailing_brewery_format(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU7.splitlines()), EXPECTED_MENU7)

    def test_catalog_format(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU8.splitlines()), EXPECTED_MENU8)

    def test_tabular_format(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU9.splitlines()), EXPECTED_MENU9)

    def test_zero_abv_double_slash_format(self):
        self.assertEqual(untap_parser.parse_menu_lines(ZERO_ABV.splitlines()), EXPECTED_ZERO_ABV)

    def test_v76_brewery_heading_fixture(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU2.splitlines()), EXPECTED_MENU2)

    def test_v76_metadata_pair_fixture(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU3.splitlines()), EXPECTED_MENU3)

    def test_v76_tap_list_fixture(self):
        self.assertEqual(untap_parser.parse_menu_lines(MENU4.splitlines()), EXPECTED_MENU4)

    def test_parser_contract_keys(self):
        for item in untap_parser.parse_menu_lines(MENU9.splitlines()):
            self.assertEqual(set(item), {'brewery', 'beer', 'style', 'menu_abv', 'query', 'original'})

    def test_supported_formats_help_is_user_facing(self):
        help_text = untap_parser.supported_formats_help()
        self.assertIn('Tab-separated rows (recommended)', help_text)
        self.assertIn('Beer / Style + ABV / Brewery records', help_text)
        self.assertIn('Beer // ABV // Style records', help_text)
        self.assertIn('Supported webshop/catalog rows', help_text)
        self.assertIn('Brewery-heading blocks', help_text)
        self.assertIn('Beer/style + ABV/IBU/brewery pairs', help_text)
        self.assertIn('Tap-list blocks', help_text)
        self.assertIn('brewery<TAB>beer<TAB>ABV<TAB>style', help_text)


class ParserValidationTests(unittest.TestCase):
    def test_detects_supported_formats(self):
        self.assertEqual(
            untap_parser.detect_menu_format(MENU9.splitlines()),
            untap_parser.FORMAT_TABULAR,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(MENU8.splitlines()),
            untap_parser.FORMAT_CATALOG,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(MENU7.splitlines()),
            untap_parser.FORMAT_TRAILING_BREWERY,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(ZERO_ABV.splitlines()),
            untap_parser.FORMAT_DOUBLE_SLASH,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(MENU2.splitlines()),
            untap_parser.FORMAT_BREWERY_BLOCK,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(MENU3.splitlines()),
            untap_parser.FORMAT_METADATA_PAIRS,
        )
        self.assertEqual(
            untap_parser.detect_menu_format(MENU4.splitlines()),
            untap_parser.FORMAT_TAP_LIST,
        )

    def test_validate_and_parse_preserves_golden_outputs(self):
        cases = [
            (MENU7, EXPECTED_MENU7),
            (MENU8, EXPECTED_MENU8),
            (MENU9, EXPECTED_MENU9),
            (ZERO_ABV, EXPECTED_ZERO_ABV),
            (MENU2, EXPECTED_MENU2),
            (MENU3, EXPECTED_MENU3),
            (MENU4, EXPECTED_MENU4),
        ]
        for raw, expected in cases:
            with self.subTest(first_line=raw.splitlines()[0]):
                _format_name, items = untap_parser.validate_and_parse_menu_lines(
                    raw.splitlines()
                )
                self.assertEqual(items, expected)

    def test_malformed_tabular_file_fails_closed(self):
        malformed = "Badlands\tPop Pop (2026)\t6.5%\tIPA\nBrujos\tLament\t5.3%"
        with self.assertRaisesRegex(
            untap_parser.MenuValidationError,
            "expected exactly 4",
        ):
            untap_parser.validate_and_parse_menu_lines(malformed.splitlines())

    def test_malformed_double_slash_file_fails_closed(self):
        malformed = "Heineken // alcohol free // Non-Alcoholic"
        with self.assertRaisesRegex(
            untap_parser.MenuValidationError,
            "Beer // ABV // Style",
        ):
            untap_parser.validate_and_parse_menu_lines(malformed.splitlines())

    def test_unsupported_free_form_file_is_rejected(self):
        malformed = "This is some copied website text\nBuy now\nAmazing beer"
        with self.assertRaisesRegex(
            untap_parser.MenuValidationError,
            "does not match a supported raw menu format",
        ):
            untap_parser.validate_and_parse_menu_lines(malformed.splitlines())

    def test_normalized_contract_rejects_invalid_abv(self):
        bad = [dict(EXPECTED_MENU9[0], menu_abv=-1.0)]
        with self.assertRaisesRegex(
            untap_parser.MenuValidationError,
            "out-of-range ABV",
        ):
            untap_parser.validate_normalized_menu(bad)


if __name__ == '__main__':
    unittest.main()
