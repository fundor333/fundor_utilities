from export_csv.views import ExportCSV


class ExportTSV(ExportCSV):
    _csv_writer_dialect = "excel_tab"
