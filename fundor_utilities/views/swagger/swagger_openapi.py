import re
import warnings
from collections import OrderedDict
from operator import attrgetter
from urllib.parse import urljoin
from weakref import WeakKeyDictionary

from django.core.exceptions import PermissionDenied
from django.core.validators import (
    DecimalValidator,
    EmailValidator,
    MaxLengthValidator,
    MaxValueValidator,
    MinLengthValidator,
    MinValueValidator,
    RegexValidator,
    URLValidator,
)
from django.db import models
from django.http import Http404
from django.utils.encoding import force_str, smart_str
from rest_framework import exceptions, renderers, serializers
from rest_framework.compat import uritemplate
from rest_framework.fields import empty, Field
from rest_framework.request import clone_request
from rest_framework.schemas.generators import EndpointEnumerator, get_pk_name
from rest_framework.schemas.utils import is_list_view, get_pk_description
from rest_framework.settings import api_settings
from rest_framework.utils import formatting
from rest_framework.views import APIView

from corekernel.views import log


class _UnvalidatedField(Field):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.allow_blank = True
        self.allow_null = True

    def to_internal_value(self, data):
        return data

    def to_representation(self, value):
        return value


class SortedPathSchemaGenerator:
    endpoint_inspector_cls = EndpointEnumerator

    # 'pk' isn't great as an externally exposed name for an identifier,
    # so by default we prefer to use the actual model field name for schemas.
    # Set by 'SCHEMA_COERCE_PATH_PK'.
    coerce_path_pk = None

    def __init__(
        self,
        title=None,
        url=None,
        description=None,
        patterns=None,
        urlconf=None,
        version=None,
    ):
        if url and not url.endswith("/"):
            url += "/"

        self.coerce_path_pk = api_settings.SCHEMA_COERCE_PATH_PK

        self.patterns = patterns
        self.urlconf = urlconf
        self.title = title
        self.description = description
        self.version = version
        self.url = url
        self.endpoints = None

    def _initialise_endpoints(self):
        if self.endpoints is None:
            inspector = self.endpoint_inspector_cls(self.patterns, self.urlconf)
            self.endpoints = inspector.get_api_endpoints()

    def _get_paths_and_endpoints(self, request):
        """
        Generate (path, method, view) given (path, method, callback) for paths.
        """
        paths = []
        view_endpoints = []
        for path, method, callback in self.endpoints:
            view = self.create_view(callback, method, request)
            path = self.coerce_path(path, method, view)
            if view:
                paths.append(path)
                view_endpoints.append((path, method, view))
        return paths, view_endpoints

    def _user_has_perm(self, user, endpoint_view, method):
        view_perms = endpoint_view.get_permissions()
        is_allowed = []
        for view_perm in view_perms:
            perms = view_perm.get_required_permissions(method, endpoint_view.get_serializer().Meta.model)
            is_allowed.append(all(user.has_perm(perm) if perm else True for perm in perms))
        return all(is_allowed)

    def create_view(self, callback, method, request=None):
        """
        Given a callback, return an actual view instance.
        """
        view = callback.cls(**getattr(callback, "initkwargs", {}))
        view.args = ()
        view.kwargs = {}
        view.format_kwarg = None
        view.request = None
        view.action_map = getattr(callback, "actions", None)

        actions = getattr(callback, "actions", None)
        if actions is not None:
            if method == "OPTIONS":
                view.action = "metadata"
            else:
                view.action = actions.get(method.lower())

        if request is not None:
            view.request = clone_request(request, method)
        is_allowed = True
        if not request.user.is_superuser:
            is_allowed = self._user_has_perm(request.user, view, method)
        if is_allowed:
            return view

    def coerce_path(self, path, method, view):
        """
        Coerce {pk} path arguments into the name of the model field,
        where possible. This is cleaner for an external representation.
        (Ie. "this is an identifier", not "this is a database primary key")
        """
        if not self.coerce_path_pk or "{pk}" not in path:
            return path
        model = getattr(getattr(view, "queryset", None), "model", None)
        if model:
            field_name = get_pk_name(model)
        else:
            field_name = "id"
        return path.replace("{pk}", "{%s}" % field_name)

    def has_view_permissions(self, path, method, view):
        """
        Return `True` if the incoming request has the correct view permissions.
        """
        if view.request is None:
            return True

        try:
            view.check_permissions(view.request)
        except (exceptions.APIException, Http404, PermissionDenied):
            return False
        return True

    def get_info(self):
        # Title and version are required by openapi specification 3.x
        info = {"title": self.title or "", "version": self.version or ""}

        if self.description is not None:
            info["description"] = self.description

        return info

    def get_paths(self, request=None):
        result = {}

        self._initialise_endpoints()

        paths, view_endpoints = self._get_paths_and_endpoints(request)

        # Only generate the path prefix for paths that will be included
        if not paths:
            return None

        for path, method, view in view_endpoints:
            if not self.has_view_permissions(path, method, view):
                continue
            operation = view.schema.get_operation(path, method)
            # Normalise path for any provided mount url.
            if path.startswith("/"):
                path = path[1:]
            path = urljoin(self.url or "/", path)

            result.setdefault(path, {})
            result[path][method.lower()] = operation
        return result

    def get_schema(self, request=None, public=False):
        """
        Generate a OpenAPI schema.
        """

        paths = self.get_paths(None if public else request)
        if not paths:
            return None

        schema = {
            "openapi": "3.0.2",
            "info": self.get_info(),
            "components": {
                "securitySchemes": {
                    "ApiKeyAuth": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "Authorization",
                        "value": "Token ",
                    }
                }
            },
            "servers": [
                {
                    "url": "https://kitsunetest.alilaguna.it/",
                    "description": "Sandbox server (uses test data)",
                },
                {
                    "url": "https://kitsune.alilaguna.it/",
                    "description": "Production server (uses live data)",
                },
            ],
            "paths": dict(OrderedDict(sorted(paths.items(), key=lambda t: t[0]))),
        }
        if schema is None:
            return
        return schema


class CustomAutoSchema:
    request_media_types = []
    response_media_types = []

    method_mapping = {
        "get": "Retrieve",
        "post": "Create",
        "put": "Update",
        "patch": "PartialUpdate",
        "delete": "Destroy",
    }

    header_regex = re.compile("^[a-zA-Z][0-9A-Za-z_]*:")

    def __init__(self):
        self.instance_schemas = WeakKeyDictionary()

    def __get__(self, instance, owner):
        """
        Enables `ViewInspector` as a Python _Descriptor_.

        This is how `view.schema` knows about `view`.

        `__get__` is called when the descriptor is accessed on the owner.
        (That will be when view.schema is called in our case.)

        `owner` is always the owner class. (An APIView, or subclass for us.)
        `instance` is the view instance or `None` if accessed from the class,
        rather than an instance.

        See: https://docs.python.org/3/howto/descriptor.html for info on
        descriptor usage.
        """
        if instance in self.instance_schemas:
            return self.instance_schemas[instance]

        self.view = instance
        return self

    def __set__(self, instance, other):
        self.instance_schemas[instance] = other
        if other is not None:
            other.view = instance

    @property
    def view(self):
        """View property."""
        assert self._view is not None, (
            "Schema generation REQUIRES a view instance. (Hint: you accessed "
            "`schema` from the view class rather than an instance.)"
        )
        return self._view

    @view.setter
    def view(self, value):
        self._view = value

    @view.deleter
    def view(self):
        self._view = None

    def get_description(self, path, method):
        """
        Determine a path description.

        This will be based on the method docstring if one exists,
        or else the class docstring.
        """
        view = self.view

        method_name = getattr(view, "action", method.lower())
        method_docstring = getattr(view, method_name, None).__doc__
        if method_docstring:
            # An explicit docstring on the method or action.
            return self._get_description_section(
                view, method.lower(), formatting.dedent(smart_str(method_docstring))
            )
        else:
            return self._get_description_section(
                view,
                getattr(view, "action", method.lower()),
                view.get_view_description(),
            )

    def _get_description_section(self, view, header, description):
        lines = [line for line in description.splitlines()]
        current_section = ""
        sections = {"": ""}

        for line in lines:
            if self.header_regex.match(line):
                current_section, separator, lead = line.partition(":")
                sections[current_section] = lead.strip()
            else:
                sections[current_section] += "\n" + line

        # TODO: SCHEMA_COERCE_METHOD_NAMES appears here and in `SchemaGenerator.get_keys`
        coerce_method_names = api_settings.SCHEMA_COERCE_METHOD_NAMES
        if header in sections:
            return sections[header].strip()
        if header in coerce_method_names:
            if coerce_method_names[header] in sections:
                return sections[coerce_method_names[header]].strip()
        return sections[""].strip()

    def get_operation(self, path, method):
        operation = {
            "operationId": self._get_operation_id(path, method),
            "description": self.get_description(path, method),
        }

        tags = self.get_tags(path, method)
        if tags:
            operation["tags"] = tags

        if self.is_deprecated(path, method):
            operation["deprecated"] = True

        parameters = []
        parameters += self._get_path_parameters(path)
        parameters += self._get_pagination_parameters(path, method)
        parameters += self._get_filter_parameters(path, method)

        operation["parameters"] = parameters

        request_body = self._get_request_body(path, method)
        if request_body:
            operation["requestBody"] = request_body
        operation["responses"] = self._get_responses(path, method)

        return operation

    def _get_operation_id(self, path, method):
        """
        Compute an operation ID from the model, serializer or view name.
        """
        method_name = getattr(self.view, "action", method.lower())
        if is_list_view(path, method, self.view):
            action = "list"
        elif method_name not in self.method_mapping:
            action = method_name
        else:
            action = self.method_mapping[method.lower()]

        # Try to deduce the ID from the view's model
        model = getattr(getattr(self.view, "queryset", None), "model", None)
        if model is not None:
            name = model.__name__

        # Try with the serializer class name
        elif hasattr(self.view, "get_serializer_class"):
            name = self.view.get_serializer_class().__name__
            if name.endswith("Serializer"):
                name = name[:-10]

        # Fallback to the view name
        else:
            name = self.view.__class__.__name__
            if name.endswith("APIView"):
                name = name[:-7]
            elif name.endswith("View"):
                name = name[:-4]

            # Due to camel-casing of classes and `action` being lowercase, apply title in order to find if action truly
            # comes at the end of the name
            if name.endswith(
                action.title()
            ):  # ListView, UpdateAPIView, ThingDelete ...
                name = name[: -len(action)]

        if action == "list" and not name.endswith(
            "s"
        ):  # listThings instead of listThing
            name += "s"

        return action + name

    def get_tags(self, path, method):
        """
        Compute the tags.
        """
        try:
            return self.view.tags
        except AttributeError:
            return

    def is_deprecated(self, path, method):
        """
        Is deprecated.
        """
        try:
            return self.view.deprecated
        except AttributeError:
            return False

    def _get_path_parameters(self, path):
        """
        Return a list of parameters from templated path variables.
        """
        assert (
            uritemplate
        ), "`uritemplate` must be installed for OpenAPI schema support."

        model = getattr(getattr(self.view, "queryset", None), "model", None)
        parameters = []

        for variable in uritemplate.variables(path):
            description = ""
            if model is not None:  # TODO: test this.
                # Attempt to infer a field description if possible.
                try:
                    model_field = model._meta.get_field(variable)
                except Exception:
                    model_field = None

                if model_field is not None and model_field.help_text:
                    description = force_str(model_field.help_text)
                elif model_field is not None and model_field.primary_key:
                    description = get_pk_description(model, model_field)

            parameter = {
                "name": variable,
                "in": "path",
                "required": True,
                "description": description,
                "schema": {"type": "string",},  # TODO: integer, pattern, ...
            }
            parameters.append(parameter)

        return parameters

    def _get_filter_parameters(self, path, method):
        if not self._allows_filters(path, method):
            return []
        parameters = []
        for filter_backend in self.view.filter_backends:
            parameters += filter_backend().get_schema_operation_parameters(self.view)
        return parameters

    def _allows_filters(self, path, method):
        """
        Determine whether to include filter Fields in schema.

        Default implementation looks for ModelViewSet or GenericAPIView
        actions/methods that cause filtering on the default implementation.
        """
        if getattr(self.view, "filter_backends", None) is None:
            return False
        if hasattr(self.view, "action"):
            return self.view.action in [
                "list",
                "retrieve",
                "update",
                "partial_update",
                "destroy",
            ]
        return method.lower() in ["get", "put", "patch", "delete"]

    def _get_pagination_parameters(self, path, method):
        view = self.view

        if not is_list_view(path, method, view):
            return []

        paginator = self._get_paginator()
        if not paginator:
            return []

        return paginator.get_schema_operation_parameters(view)

    def _map_field(self, field):

        # Nested Serializers, `many` or not.
        if isinstance(field, serializers.ListSerializer):
            return {"type": "array", "items": self._map_serializer(field.child)}
        if isinstance(field, serializers.Serializer):
            data = self._map_serializer(field)
            data["type"] = "object"
            return data

        # Related fields.
        if isinstance(field, serializers.ManyRelatedField):
            return {"type": "array", "items": self._map_field(field.child_relation)}
        if isinstance(field, serializers.PrimaryKeyRelatedField):
            model = getattr(field.queryset, "model", None)
            if model is not None:
                model_field = model._meta.pk
                if isinstance(model_field, models.AutoField):
                    return {"type": "integer"}

        # ChoiceFields (single and multiple).
        # Q:
        # - Is 'type' required?
        # - can we determine the TYPE of a choicefield?
        if isinstance(field, serializers.MultipleChoiceField):
            return {
                "type": "array",
                "items": {"enum": list(field.choices)},
            }

        if isinstance(field, serializers.ChoiceField):
            return {
                "enum": list(field.choices),
            }

        # ListField.
        if isinstance(field, serializers.ListField):
            mapping = {
                "type": "array",
                "items": {},
            }
            if not isinstance(field.child, _UnvalidatedField):
                map_field = self._map_field(field.child)
                items = {"type": map_field.get("type")}
                if "format" in map_field:
                    items["format"] = map_field.get("format")
                mapping["items"] = items
            return mapping

        # DateField and DateTimeField type is string
        if isinstance(field, serializers.DateField):
            return {
                "type": "string",
                "format": "date",
            }

        if isinstance(field, serializers.DateTimeField):
            return {
                "type": "string",
                "format": "date-time",
            }

        # "Formats such as "email", "uuid", and so on, MAY be used even though undefined by this specification."
        # see: https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.2.md#data-types
        # see also: https://swagger.io/docs/specification/data-models/data-types/#string
        if isinstance(field, serializers.EmailField):
            return {"type": "string", "format": "email"}

        if isinstance(field, serializers.URLField):
            return {"type": "string", "format": "uri"}

        if isinstance(field, serializers.UUIDField):
            return {"type": "string", "format": "uuid"}

        if isinstance(field, serializers.IPAddressField):
            content = {
                "type": "string",
            }
            if field.protocol != "both":
                content["format"] = field.protocol
            return content

        # DecimalField has multipleOf based on decimal_places
        if isinstance(field, serializers.DecimalField):
            content = {"type": "number"}
            if field.decimal_places:
                content["multipleOf"] = float(
                    "." + (field.decimal_places - 1) * "0" + "1"
                )
            if field.max_whole_digits:
                content["maximum"] = int(field.max_whole_digits * "9") + 1
                content["minimum"] = -content["maximum"]
            self._map_min_max(field, content)
            return content

        if isinstance(field, serializers.FloatField):
            content = {"type": "number"}
            self._map_min_max(field, content)
            return content

        if isinstance(field, serializers.IntegerField):
            content = {"type": "integer"}
            self._map_min_max(field, content)
            # 2147483647 is max for int32_size, so we use int64 for format
            if (
                int(content.get("maximum", 0)) > 2147483647
                or int(content.get("minimum", 0)) > 2147483647
            ):
                content["format"] = "int64"
            return content

        if isinstance(field, serializers.FileField):
            return {"type": "string", "format": "binary"}

        # Simplest cases, default to 'string' type:
        FIELD_CLASS_SCHEMA_TYPE = {
            serializers.BooleanField: "boolean",
            serializers.JSONField: "object",
            serializers.DictField: "object",
            serializers.HStoreField: "object",
        }
        return {"type": FIELD_CLASS_SCHEMA_TYPE.get(field.__class__, "string")}

    def _map_min_max(self, field, content):
        if field.max_value:
            content["maximum"] = field.max_value
        if field.min_value:
            content["minimum"] = field.min_value

    def _map_serializer(self, serializer):
        # Assuming we have a valid serializer instance.
        # TODO:
        #   - field is Nested or List serializer.
        #   - Handle read_only/write_only for request/response differences.
        #       - could do this with readOnly/writeOnly and then filter dict.
        required = []
        properties = {}

        for field in serializer.fields.values():
            if isinstance(field, serializers.HiddenField):
                continue

            if field.required:
                required.append(field.field_name)

            schema = self._map_field(field)
            if field.read_only:
                schema["readOnly"] = True
            if field.write_only:
                schema["writeOnly"] = True
            if field.allow_null:
                schema["nullable"] = True
            if field.default and field.default != empty:  # why don't they use None?!
                schema["default"] = field.default
            if field.help_text:
                schema["description"] = str(field.help_text)
            self._map_field_validators(field, schema)

            properties[field.field_name] = schema

        result = {"properties": properties}
        if required:
            result["required"] = required

        return result

    def _map_field_validators(self, field, schema):
        """
        map field validators
        """
        for v in field.validators:
            # "Formats such as "email", "uuid", and so on, MAY be used even though undefined by this specification."
            # https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.2.md#data-types
            if isinstance(v, EmailValidator):
                schema["format"] = "email"
            if isinstance(v, URLValidator):
                schema["format"] = "uri"
            if isinstance(v, RegexValidator):
                schema["pattern"] = v.regex.pattern
            elif isinstance(v, MaxLengthValidator):
                attr_name = "maxLength"
                if isinstance(field, serializers.ListField):
                    attr_name = "maxItems"
                schema[attr_name] = v.limit_value
            elif isinstance(v, MinLengthValidator):
                attr_name = "minLength"
                if isinstance(field, serializers.ListField):
                    attr_name = "minItems"
                schema[attr_name] = v.limit_value
            elif isinstance(v, MaxValueValidator):
                schema["maximum"] = v.limit_value
            elif isinstance(v, MinValueValidator):
                schema["minimum"] = v.limit_value
            elif isinstance(v, DecimalValidator):
                if v.decimal_places:
                    schema["multipleOf"] = float(
                        "." + (v.decimal_places - 1) * "0" + "1"
                    )
                if v.max_digits:
                    digits = v.max_digits
                    if v.decimal_places is not None and v.decimal_places > 0:
                        digits -= v.decimal_places
                    schema["maximum"] = int(digits * "9") + 1
                    schema["minimum"] = -schema["maximum"]

    def _get_paginator(self):
        pagination_class = getattr(self.view, "pagination_class", None)
        if pagination_class:
            return pagination_class()
        return None

    def map_parsers(self, path, method):
        return list(map(attrgetter("media_type"), self.view.parser_classes))

    def map_renderers(self, path, method):
        media_types = []
        for renderer in self.view.renderer_classes:
            # BrowsableAPIRenderer not relevant to OpenAPI spec
            if renderer == renderers.BrowsableAPIRenderer:
                continue
            media_types.append(renderer.media_type)
        return media_types

    def _get_serializer(self, method, path):
        view = self.view

        if not hasattr(view, "get_serializer"):
            return None

        try:
            return view.get_serializer()
        except exceptions.APIException:
            warnings.warn(
                "{}.get_serializer() raised an exception during "
                "schema generation. Serializer fields will not be "
                "generated for {} {}.".format(view.__class__.__name__, method, path)
            )
            return None

    def _get_request_body(self, path, method):
        if method not in ("PUT", "PATCH", "POST"):
            return {}

        self.request_media_types = self.map_parsers(path, method)

        serializer = self._get_serializer(path, method)

        if not isinstance(serializer, serializers.Serializer):
            return {}

        content = self._map_serializer(serializer)
        # No required fields for PATCH
        if method == "PATCH":
            content.pop("required", None)
        # No read_only fields for request.
        for name, schema in content["properties"].copy().items():
            if "readOnly" in schema:
                del content["properties"][name]

        return {"content": {ct: {"schema": content} for ct in self.request_media_types}}

    def _get_responses(self, path, method):
        # TODO: Handle multiple codes and pagination classes.
        if method == "DELETE":
            return {"204": {"description": ""}}

        self.response_media_types = self.map_renderers(path, method)

        item_schema = {}
        serializer = self._get_serializer(path, method)

        if isinstance(serializer, serializers.Serializer):
            item_schema = self._map_serializer(serializer)
            # No write_only fields for response.
            for name, schema in item_schema["properties"].copy().items():
                if "writeOnly" in schema:
                    del item_schema["properties"][name]
                    if "required" in item_schema:
                        item_schema["required"] = [
                            f for f in item_schema["required"] if f != name
                        ]

        if is_list_view(path, method, self.view):
            response_schema = {
                "type": "array",
                "items": item_schema,
            }
            paginator = self._get_paginator()
            if paginator:
                response_schema = paginator.get_paginated_response_schema(
                    response_schema
                )
        else:
            response_schema = item_schema

        return {
            "200": {
                "content": {
                    ct: {"schema": response_schema} for ct in self.response_media_types
                },
                # description is a mandatory property,
                # https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.2.md#responseObject
                # TODO: put something meaningful into it
                "description": "",
            }
        }


class AdvanceApiView(APIView):
    schema = CustomAutoSchema()
