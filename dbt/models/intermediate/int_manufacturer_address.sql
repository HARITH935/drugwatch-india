-- One normalised copy of each manufacturer's address, for every model that has to read it.
--
-- Two models need the address prepared the same way (the state-name matcher and the PIN
-- extractor), so it is prepared once here. Doing it twice would let the two drift apart - and
-- since the PIN map is *learned* from the name matcher's answers, a difference between them would
-- quietly corrupt the map.
--
-- Three columns come out of it:
--
-- `address_norm` - lower case, dots dropped ("H.P." -> "hp", "(M.P)" -> "mp"), every other
--   punctuation mark turned into a space, '&' kept so "J&K" survives, and a space at each end so
--   a state name at the very start or end still has a word boundary.
--
-- `own_address_norm` - the same, cut at the first marketer marker. 47 addresses carry a SECOND
--   company's address after "Mrkt:" or "Marketed By", often in another state, and the manufacturer
--   is the one printed first. The markers are the whole words that actually occur, counted:
--   mrkt (30), marketed (7), mrk (6), mkt (2), markt (1). **"market" is deliberately not one**,
--   though it occurs 4 times: it belongs to real addresses like "Vasavi Pharma Market Complex",
--   and cutting there would lose the state.
--
-- `pin_code` - the last 6-digit postal code, read from the ORIGINAL text rather than the
--   normalised copy, and that is the whole point: only whitespace is allowed between the two
--   halves ("247 667" is a PIN), so punctuation-joined numbers are rejected. Found by holding the
--   learned PIN map out against known states: "Khasra No. 140-141" and "393/394, Melli Jorethang
--   Road" are plot numbers, and reading them off the flattened string turned them into the PINs
--   140141 and 393394. With this rule the first yields nothing and the second correctly finds the
--   real PIN later in the address (737121, Sikkim).

with manufacturers as (

    select * from {{ ref('int_manufacturer') }}

)

select
    manufacturer_id,
    canonical_name,
    latest_address,
    first_alert_month,
    last_alert_month,
    name_variants,
    name_variant_count,

    ' ' || regexp_replace(
        lower(replace(coalesce(latest_address, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
    ) || ' ' as address_norm,

    regexp_replace(
        ' ' || regexp_replace(
            lower(replace(coalesce(latest_address, ''), '.', '')), '[^a-z0-9&]+', ' ', 'g'
        ) || ' ',
        '\m(mrkt|mrk|marketed|markt|mktd|mkt)\M.*', ''
    ) as own_address_norm,

    -- `with ordinality ... order by ord desc limit 1` = the LAST match, because a postal code
    -- comes at the end of an address while plot and survey numbers come at the start.
    (
        select matched[1] || matched[2]
        from regexp_matches(
            coalesce(latest_address, ''),
            '([1-9][0-9]{2})[[:space:]]?([0-9]{3})(?![0-9])',
            'g'
        ) with ordinality as pins(matched, ord)
        order by ord desc
        limit 1
    ) as pin_code

from manufacturers
