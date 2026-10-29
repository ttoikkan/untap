import unittest
from pathlib import Path
import untap.parser as untap_parser
MENU9 = """All My Friends\tBetrayal\t6,8%\tIPA
Brasserie du Bas-Canada x Herman\tÉlixir-IPA\t7,0%\tIPA
Brujos\tPopulus w/ Citra\t7,5%\tIPA
Messorem\tDemoliri #0031 - XTRM Turbo\t7,0%\tIPA
Mortalis\tGemini | Bomb Pop\t7,0%\tSmoothie Sour
Sante Adairius Rustic Ales\tSilent Spaces\t6,3%\tBarrel Aged Saison
Wax Wings\t8 Streamers\t7,2%\tIPA
"""

EXPECTED_MENU9 = [
    {'original': 'All My Friends\tBetrayal\t6,8%\tIPA', 'brewery': 'All My Friends', 'beer': 'Betrayal', 'style': 'IPA', 'menu_abv': 6.8, 'query': 'All My Friends Betrayal'},
    {'original': 'Brasserie du Bas-Canada x Herman\tÉlixir-IPA\t7,0%\tIPA', 'brewery': 'Brasserie du Bas-Canada x Herman', 'beer': 'Élixir-IPA', 'style': 'IPA', 'menu_abv': 7.0, 'query': 'Brasserie du Bas-Canada Herman Élixir-IPA'},
    {'original': 'Brujos\tPopulus w/ Citra\t7,5%\tIPA', 'brewery': 'Brujos', 'beer': 'Populus w/ Citra', 'style': 'IPA', 'menu_abv': 7.5, 'query': 'Brujos Populus w/ Citra'},
    {'original': 'Messorem\tDemoliri #0031 - XTRM Turbo\t7,0%\tIPA', 'brewery': 'Messorem', 'beer': 'Demoliri #0031 - XTRM Turbo', 'style': 'IPA', 'menu_abv': 7.0, 'query': 'Messorem Demoliri #0031 - XTRM Turbo'},
    {'original': 'Mortalis\tGemini | Bomb Pop\t7,0%\tSmoothie Sour', 'brewery': 'Mortalis', 'beer': 'Gemini | Bomb Pop', 'style': 'Smoothie Sour', 'menu_abv': 7.0, 'query': 'Mortalis Gemini | Bomb Pop'},
    {'original': 'Sante Adairius Rustic Ales\tSilent Spaces\t6,3%\tBarrel Aged Saison', 'brewery': 'Sante Adairius Rustic Ales', 'beer': 'Silent Spaces', 'style': 'Barrel Aged Saison', 'menu_abv': 6.3, 'query': 'Sante Adairius Rustic Ales Silent Spaces'},
    {'original': 'Wax Wings\t8 Streamers\t7,2%\tIPA', 'brewery': 'Wax Wings', 'beer': '8 Streamers', 'style': 'IPA', 'menu_abv': 7.2, 'query': 'Wax Wings 8 Streamers'},
]

class ParserContractTests(unittest.TestCase):
    def test_tabular_golden_output_is_preserved(self):
        name, items = untap_parser.validate_and_parse_menu_lines(MENU9.splitlines())
        self.assertEqual(name, untap_parser.FORMAT_TABULAR)
        self.assertEqual(items, EXPECTED_MENU9)

    def test_header_blank_lines_bom_zero_abv_and_empty_style(self):
        _, items = untap_parser.validate_and_parse_menu_lines([
            "\ufeffbrewery\tbeer\tABV\tstyle\r\n", "\n", " Example \t Zero IPA | X-Ray \t0%\t\r\n"])
        self.assertEqual(items[0]['menu_abv'], 0)
        self.assertEqual(items[0]['beer'], 'Zero IPA | X-Ray')
        self.assertIsNone(items[0]['style'])

    def test_invalid_rows_fail_with_source_line_number(self):
        for row in ['Brewery\tBeer', '\tBeer\t5%\tIPA',
                    'Brewery\t\t5%\tIPA', 'Brewery\tBeer\tunknown\tIPA',
                    'Brewery\tBeer\t101%\tIPA', 'Brewery\tBeer\tNaN%\tIPA']:
            with self.subTest(row=row), self.assertRaisesRegex(untap_parser.MenuValidationError, 'Line 2'):
                untap_parser.parse_menu_lines(['\n', row])

    def test_empty_and_header_only_menus_are_rejected(self):
        for lines in [[], ['\n'], ['brewery\tbeer\tabv\tstyle'], ['brewery\tbeer\tabv']]:
            with self.subTest(lines=lines), self.assertRaises(untap_parser.MenuValidationError):
                untap_parser.parse_menu_lines(lines)

    def test_legacy_layouts_require_conversion(self):
        for name in ('menu2.txt', 'menu3.txt', 'menu4.txt'):
            lines = Path(__file__).with_name('testdata').joinpath(name).read_text().splitlines()
            with self.subTest(name=name), self.assertRaisesRegex(untap_parser.MenuValidationError, 'Convert older menu layouts'):
                untap_parser.parse_menu_lines(lines)
        for text in ['Heineken // 0% // Non-Alcoholic', 'Beer\nIPA | 5%\nBrewery',
                     'Beer IPA\nRegular price€15,50 EUR']:
            with self.assertRaises(untap_parser.MenuValidationError):
                untap_parser.parse_menu_lines(text.splitlines())

    def test_help_describes_only_tsv(self):
        text = untap_parser.supported_formats_help()
        self.assertIn('brewery<TAB>beer<TAB>ABV<TAB>style', text)
        self.assertNotIn('webshop', text)


class OptionalStyleTests(unittest.TestCase):
    def test_complete_three_column_menu(self):
        path = Path(__file__).with_name('testdata') / 'menu_without_style.tsv'
        name, items = untap_parser.read_validated_menu(str(path))
        self.assertEqual(name, untap_parser.FORMAT_TABULAR)
        self.assertEqual(len(items), 21)
        self.assertTrue(all(item['style'] is None for item in items))
        self.assertEqual([item['menu_abv'] for item in items],
                         [7., 6.5, 7., 7.5, 6.5, 7.5, 8., 5.2, 5.3, 6.6, 7., 7.1,
                          6.5, 7., 7., 7., 7., 8., 6., 8., 8.])
        self.assertEqual([item['original'] for item in items], path.read_text().splitlines())
        self.assertEqual(items[13]['query'], 'Messorem Demoliri #0037 - XTRM Turbo')
        self.assertEqual(items[15]['beer'], 'Hydra | Boysenberry + Prickly Pear + Pineapple')
        self.assertEqual(items[19]['beer'], 'Paire d’As')

    def test_both_headers_and_mixed_row_widths(self):
        for header in ('BREWERY\tBeer\tABV', 'brewery\tbeer\tabv\tstyle'):
            with self.subTest(header=header):
                _, items = untap_parser.validate_and_parse_menu_lines([
                    '\ufeff' + header + '\r\n', '\n', 'Brewery\tFirst Beer\t6,5\r\n',
                    'Brewery\tSecond Beer\t7%\tIPA\n', 'Brewery\tThird Beer\t0\t\n'])
                self.assertEqual([item['style'] for item in items], [None, 'IPA', None])
                self.assertEqual([item['menu_abv'] for item in items], [6.5, 7., 0.])

    def test_omitted_and_empty_style_have_same_normalized_fields(self):
        short = 'Brewery\tBeer\t6,5'
        records = untap_parser.parse_menu_lines([short, short + '\t'])
        self.assertEqual(records[0]['original'], short)
        self.assertEqual(records[1]['original'], short + '\t')
        self.assertEqual({k: v for k, v in records[0].items() if k != 'original'},
                         {k: v for k, v in records[1].items() if k != 'original'})

    def test_percent_sign_is_optional_for_both_widths(self):
        for abv, expected in [('0', 0.), ('0,0', 0.), ('6.55', 6.55), ('7,0', 7.),
                              ('7,0%', 7.), ('7% ABV', 7.), ('100', 100.)]:
            for suffix in ('', '\tIPA'):
                with self.subTest(abv=abv, suffix=suffix):
                    item = untap_parser.parse_menu_lines(['Brewery\tBeer\t' + abv + suffix])[0]
                    self.assertEqual(item['menu_abv'], expected)

    def test_invalid_abv_and_field_counts_remain_rejected(self):
        for abv in ('', '-1', '101', '1,000', '7,123', 'NaN', 'inf', '1e1', '7,0%%', '7,0IPA'):
            for suffix in ('', '\tIPA'):
                with self.subTest(abv=abv, suffix=suffix), self.assertRaisesRegex(untap_parser.MenuValidationError, 'Line 2'):
                    untap_parser.parse_menu_lines(['\n', 'Brewery\tBeer\t' + abv + suffix])
        for row in ('Brewery\tBeer', 'Brewery\tBeer\t7\tIPA\textra'):
            with self.subTest(row=row), self.assertRaisesRegex(untap_parser.MenuValidationError, 'expected 3 or 4'):
                untap_parser.parse_menu_lines([row])
