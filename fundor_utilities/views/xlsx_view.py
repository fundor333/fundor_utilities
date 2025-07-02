from django.http import HttpResponse
from django.utils.encoding import force_str
from django.views.generic import View
from openpyxl import Workbook
from setuptools._entry_points import _

from fundor_utilities.exception import NoModelFoundException


class XlsxExporterView(View):
    """Generic View class which handles exporting queryset to XLSX file and
    rendering the response.
    """

    http_method_names = ["options", "head", "get"]
    model = None
    """
    Name of a model. If provided, all objects of the
    model will for the queryset. If omitted, :func:`get_queryset` method must
    be overridden.
    """

    field_names = None
    """
    List of ``model`` field names written to XLSX. If provided, only those
    fields will be included in the XLSX. If omitted, values return by
    :func:`get_field_names` is used.

    .. note:: Fields will be written in the XLSX in the order of their
        occurrence in list.
    """
    filename = None
    """
    Name used for XLSX file generated. If omitted, filename returned by
    :func:`get_filename` will be used as default file name.
    """

    sheet_title = None
    """
    Name used for XLSX sheet file generated. If omitted, sheet_title returned by
    :func:`get_sheet_title` will be used as default sheet name.
    """

    add_col_names = False
    """
    Set this to ``True`` to add column names (header) to the XLSX file. Default
    value is ``False``.
    """

    col_names = None
    """
    Column names to be used for writing the header row in the XLSX file. If
    provided, those column names will be written to header row. If omitted,
    values returned by :func:``get_col_names`` are used.
    """

    _content_type = "application/ms-excel"
    """
     The content_type header of the response returned by :func:`get`` method.
     Default value is 'text/xlsx' and should not be overridden.
    """

    def get_queryset_for_xlsx(self):
        """Returns the queryset for generating XLSX.

        By default, it returns all instances of the Model class referred by
        ``model`` attribute. Override this method to provide custom queryset.

        :raises: NoModelFoundException

        :returns: :class:`QuerySet`
        """

        if self.model is not None:
            queryset = self.model.objects.all()
        else:
            exception_msg = "No model to get queryset from. Either provide " "a model or override get_queryset method."
            raise NoModelFoundException(_(exception_msg))
        return queryset

    def get_field_names(self) -> list:
        """Returns the fields names to be included in the XLSX.

        It returns the value of ``field_names`` attribute, if ``field_names``
        is not empty. Otherwise it returns names of all the fields of the
        Model class referred by ``model`` attribute.

        :raises: NoModelFoundException

        :returns: list
        """
        if self.field_names:
            return self.field_names
        if self.model is not None:
            self.field_names = []
            for f in self.model._meta.fields:
                if f.auto_created:
                    continue
                else:
                    self.field_names.append(f.name)
            return self.field_names
        else:
            exception_msg = "No model to get field names from. Either " "provide a model or override get_fields method."
            raise NoModelFoundException(_(exception_msg))

    def _get_field_verbose_names(self):
        """Returns verbose names of fields returned by :func:`get_field_names`.

        :returns: list
        """
        field_names = self.get_field_names()
        if self.model is not None:  # noqa:B950
            verbose_names = [f.verbose_name for f in self.model._meta.fields if f.name in field_names]
            return verbose_names
        else:
            exception_msg = "No model to get verbose field names from."
            raise NoModelFoundException(_(exception_msg))

    def get_col_names(self) -> list:
        """Returns column names to be used for writing header row of the XLSX.

        It returns ``col_names``, if ``col_names`` is not an empty list.
        Otherwise, it returns the verbose names of all the fields.

        :raises: TypeError

        :returns: list
        """
        if self.col_names:
            if isinstance(self.col_names, list):
                return self.col_names
            else:
                raise TypeError(_("col_names must be a list."))
        return self._get_field_verbose_names()

    def get_sheet_title(self):
        """Returns sheet title.

        :raises: NoModelFoundException

        :returns: str
        """

        if self.sheet_title is not None:
            return self.sheet_title
        if self.model is not None:
            model_name = str(self.model.__name__).lower()
            self.sheet_title = force_str(model_name + "_list.xlsx")
        else:
            exception_msg = (
                "No model to generate filename. Either provide " "model or filename or override get_filename " "method."
            )
            raise NoModelFoundException(_(exception_msg))
        return self.sheet_title

    def get_filename(self):
        """Returns filename.

        It returns the filename to be used for rendering XLSX. If explicit
        filename is provided, that filename is returned. If omitted,
        <model>_list.xlsx is returned.

        :raises: NoModelFoundException

        :returns: str
        """
        if self.filename is not None:
            return self.filename
        if self.model is not None:
            model_name = str(self.model.__name__).lower()
            self.filename = force_str(model_name + "_list.xlsx")
        else:
            exception_msg = (
                "No model to generate filename. Either provide " "model or filename or override get_filename " "method."
            )
            raise NoModelFoundException(_(exception_msg))
        return self.filename

    def get_xlsx_writer_dialect(self):
        """Returns the dialect to be used with :func:`xlsx.writer`.

        :returns: str
        """
        return self._xlsx_writer_dialect

    def get_xlsx_writer_kwargs(self, **kwargs):
        """Returns the kwargs to be passed to :func:`xlsx.writer`.

        :param kwargs: kwargs to be passed to :func:`xlsx.writer`
        :type kwargs: dict
        :returns: dict -- kwargs to be passed to :func:`xlsx.writer`
        """
        return kwargs

    def _create_xlsx(self):
        """Create XLSX and render the response.

        :raises: TypeError

        :returns: :class:`HttpResponse`
        """
        response = HttpResponse(content_type=self._content_type)  # noqa:B907
        filename = self.get_filename()
        response["Content-Disposition"] = f'attachment; filename="{filename}"'  # noqa:B907

        # TypeError is raised mostly because of unicode and byte string issues
        wb = Workbook(write_only=True)
        ws = wb.create_sheet(title=self.get_sheet_title())

        # add header column only if self.add_col_names is True
        if self.add_col_names:
            self.col_names = self.get_col_names()
            ws.append(self.col_names)

        try:
            _, queryset, _ = self.get_dated_items()
        except Exception:  # noqa: B902
            queryset = self.get_queryset()
        fields = self.get_field_names()
        if queryset is not None:
            for row in queryset.prefetch_related().values_list(*fields):
                ws.append(row)
        wb.save(response)
        return response

    def render_to_response(self, context, **response_kwargs):
        return self._create_xlsx()


class XlsxExporter(XlsxExporterView):
    pass
