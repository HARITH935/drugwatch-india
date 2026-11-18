{#-
  dbt's default is to PREFIX a model's custom schema with the target schema: a model configured
  with `+schema: dbt_staging` against target schema `gold` would be built into `gold_dbt_staging`.
  That default exists so several developers can share one warehouse without overwriting each
  other. This project has one database per environment, so the prefix would only produce names
  nobody recognises.

  This override uses the configured schema verbatim, so the schemas are exactly:
    staging          the loader's landing table (not dbt's - dbt only reads it)
    dbt_staging      dbt's thin views over the source
    dbt_intermediate joins and enrichment on the way to gold
    gold             the marts Superset, the API and the ML pipeline read
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
