import django_filters
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django_filters.constants import EMPTY_VALUES
from drf_spectacular.utils import extend_schema_field
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.plumbing import build_basic_type
from django.db import models

__all__ = (
    'ContentTypeFilter',
    'MultiValueArrayFilter',
    'MultiValueCharFilter',
    'MultiValueDateFilter',
    'MultiValueDateTimeFilter',
    'MultiValueDecimalFilter',
    'MultiValueMACAddressFilter',
    'MultiValueNumberFilter',
    'MultiValueTimeFilter',
    'MultiValueWWNFilter',
    'NullableCharFieldFilter',
    'NumericArrayFilter',
    'TreeNodeMultipleChoiceFilter',
)


def multivalue_field_factory(field_class):
    """
    Given a form field class, return a subclass capable of accepting multiple values. This allows us to OR on multiple
    filter values while maintaining the field's built-in validation. Example: GET /api/dcim/devices/?name=foo&name=bar
    """
    class NewField(field_class):
        widget = forms.SelectMultiple

        def to_python(self, value):
            if not value:
                return []
            field = field_class()
            return [
                # Only append non-empty values (this avoids e.g. trying to cast '' as an integer)
                field.to_python(v) for v in value if v
            ]

        def run_validators(self, value):
            for v in value:
                super().run_validators(v)

        def validate(self, value):
            for v in value:
                super().validate(v)

    return type(f'MultiValue{field_class.__name__}', (NewField,), dict())


#
# Filters
#

@extend_schema_field(OpenApiTypes.STR)
class MultiValueCharFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.CharField)


@extend_schema_field(OpenApiTypes.DATE)
class MultiValueDateFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.DateField)


@extend_schema_field(OpenApiTypes.DATETIME)
class MultiValueDateTimeFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.DateTimeField)


@extend_schema_field(OpenApiTypes.INT32)
class MultiValueNumberFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.IntegerField)


@extend_schema_field(OpenApiTypes.DECIMAL)
class MultiValueDecimalFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.DecimalField)


@extend_schema_field(OpenApiTypes.TIME)
class MultiValueTimeFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.TimeField)


@extend_schema_field(OpenApiTypes.STR)
class MultiValueArrayFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.CharField)

    def __init__(self, *args, lookup_expr='contains', **kwargs):
        # Set default lookup_expr to 'contains'
        super().__init__(*args, lookup_expr=lookup_expr, **kwargs)

    def get_filter_predicate(self, v):
        # If filtering for null values, ignore lookup_expr
        if v is None:
            return {self.field_name: None}
        return super().get_filter_predicate(v)


@extend_schema_field(OpenApiTypes.STR)
class MultiValueMACAddressFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.CharField)

    def filter(self, qs, value):
        try:
            return super().filter(qs, value)
        except ValidationError:
            return qs.none()


@extend_schema_field(OpenApiTypes.STR)
class MultiValueWWNFilter(django_filters.MultipleChoiceFilter):
    field_class = multivalue_field_factory(forms.CharField)


class TreeNodeMultipleChoiceFilter(django_filters.ModelMultipleChoiceFilter):
    """
    Filters for a set of Models, including all descendant models within a Tree.  Example: [<Region: R1>,<Region: R2>]
    """

    _spectacular_annotation = {}

    def __init__(self, *args, **kwargs):
        if 'field_name' in kwargs and 'to_field_name' in kwargs:
            to_field = kwargs['queryset'].model._meta.get_field(kwargs['to_field_name'])
            field_type = type(to_field)
            openapi_type = self.__get_openapi_type(field_type)
            field = build_basic_type(openapi_type)
            self._spectacular_annotation = {
                'field': {
                    **field,
                    'description': kwargs['label'] if 'label' in kwargs else ''
                }
            }
        super().__init__(*args, **kwargs)

    def get_filter_predicate(self, v):
        # Null value filtering
        if v is None:
            return {f"{self.field_name}__isnull": True}
        return super().get_filter_predicate(v)

    def filter(self, qs, value):
        value = [node.get_descendants(include_self=True) if not isinstance(node, str) else node for node in value]
        return super().filter(qs, value)

    def __get_openapi_type(self, field_type):
        if isinstance(field_type, models.IntegerField) or issubclass(field_type, models.IntegerField):
            return OpenApiTypes.INT
        elif isinstance(field_type, models.FloatField) or issubclass(field_type, models.FloatField):
            return OpenApiTypes.FLOAT
        return OpenApiTypes.STR


class NullableCharFieldFilter(django_filters.CharFilter):
    """
    Allow matching on null field values by passing a special string used to signify NULL.
    """
    def filter(self, qs, value):
        if value != settings.FILTERS_NULL_CHOICE_VALUE:
            return super().filter(qs, value)
        qs = self.get_method(qs)(**{'{}__isnull'.format(self.field_name): True})
        return qs.distinct() if self.distinct else qs


class NumericArrayFilter(django_filters.NumberFilter):
    """
    Filter based on the presence of an integer within an ArrayField.
    """
    def filter(self, qs, value):
        if value:
            value = [value]
        return super().filter(qs, value)


class ContentTypeFilter(django_filters.CharFilter):
    """
    Allow specifying a ContentType by <app_label>.<model> (e.g. "dcim.site").
    """
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        try:
            app_label, model = value.lower().split('.')
        except ValueError:
            return qs.none()
        return qs.filter(
            **{
                f'{self.field_name}__app_label': app_label,
                f'{self.field_name}__model': model
            }
        )
