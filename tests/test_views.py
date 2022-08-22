from django.test import TestCase

from django.contrib.auth.models import User

from fundor_utilities.views.xlsx_view import XlsxExporterView
from tests.model import Book


class MokXLSView(XlsxExporterView):
    model = Book

class TestXlsxExporter(TestCase):

    def test(self):
        moka = MokXLSView()
        self.assertEqual(moka.model, Book)
        self.assertEqual( moka.get_col_names(), ["title","price","average rating"])

