{#
  Indexes that exist for the API's searches, not for dbt's own builds.

  They live here because dbt owns `gold`: it drops and recreates every mart on each run, so an
  index created by hand disappears the next time the pipeline runs - and nobody notices until a
  search that used to take 8 ms takes 800. Creating them as a post-hook means the index is part
  of the table's definition rather than a thing somebody remembered to re-add.

  `pg_trgm` splits text into three-character pieces and indexes those, which is what makes
  "telmisartan" find "Telmisartan Tablets IP 40 mg" and tolerate a typo. Decision B of Phase 9:
  the alternative was hand-written fuzzy matching over 5,651 product names in Java.
#}

{% macro create_extension_pg_trgm() %}
    {#
      Run once per dbt invocation, before any model. CREATE EXTENSION needs rights the API's own
      role does not have, which is the reason it happens here - dbt connects as the warehouse
      owner - rather than in a Flyway migration.
    #}
    {% if execute %}
        {% do run_query("create extension if not exists pg_trgm") %}
        {{ log("pg_trgm extension is present", info=true) }}
    {% endif %}
{% endmacro %}


{% macro trigram_index(column) %}
    {#
      A GIN trigram index on one text column of the model being built. GIN rather than GiST: this
      table is rebuilt monthly and read constantly, and GIN answers similarity searches faster at
      the cost of a slower build nobody waits for.
    #}
    create index if not exists {{ this.identifier }}_{{ column }}_trgm_idx
        on {{ this }} using gin ({{ column }} gin_trgm_ops)
{% endmacro %}
